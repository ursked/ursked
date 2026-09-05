"""
Scheduled Export Service

Manages CRUD for scheduled exports and handles execution of due schedules.
"""

import logging
from datetime import datetime, time, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.data_export import DataExportConfig, ScheduledExport
from app.services.data_export_service import DataExportService
from app.services.data_source_registry import (
    get_source,
    namespaced_columns_touch_salary,
    request_touches_salary,
)
from app.services.email_service import EmailService

logger = logging.getLogger(__name__)


def _config_touches_salary(config: DataExportConfig) -> bool:
    """Whether a saved export config references salary/pay data."""
    if config.data_source == "multi":
        return namespaced_columns_touch_salary(config.columns or [])
    return request_touches_salary(config.data_source, config.columns or [])


class SalaryAccessRevoked(Exception):
    """Raised when a scheduled export carrying salary data no longer has an
    enrolled salary-viewer behind it. Handled as a normal run failure so the
    schedule is skipped (not silently exfiltrating salary) and the reason is
    recorded in the run ledger."""


class ScheduledExportService:

    # ── CRUD ──────────────────────────────────────────────────────

    @staticmethod
    async def list_schedules(
        db: AsyncSession, tenant_id: UUID
    ) -> List[ScheduledExport]:
        stmt = (
            select(ScheduledExport)
            .options(joinedload(ScheduledExport.export_config))
            .where(ScheduledExport.tenant_id == tenant_id)
            .order_by(ScheduledExport.created_at.desc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().unique().all())

    @staticmethod
    async def get_schedule(
        db: AsyncSession, tenant_id: UUID, schedule_id: int
    ) -> Optional[ScheduledExport]:
        stmt = (
            select(ScheduledExport)
            .options(joinedload(ScheduledExport.export_config))
            .where(
                ScheduledExport.tenant_id == tenant_id,
                ScheduledExport.id == schedule_id,
            )
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def create_schedule(
        db: AsyncSession,
        tenant_id: UUID,
        data: Dict[str, Any],
        created_by: int,
    ) -> ScheduledExport:
        # Validate export config exists and belongs to tenant
        config_stmt = select(DataExportConfig).where(
            DataExportConfig.tenant_id == tenant_id,
            DataExportConfig.id == data["export_config_id"],
        )
        result = await db.execute(config_stmt)
        config = result.scalar_one_or_none()
        if not config:
            raise ValueError("Export configuration not found")

        schedule_time = _parse_time(data["schedule_time"])

        schedule = ScheduledExport(
            tenant_id=tenant_id,
            export_config_id=data["export_config_id"],
            schedule_type=data["schedule_type"],
            schedule_day=data.get("schedule_day"),
            schedule_time=schedule_time,
            recipient_emails=data["recipient_emails"],
            is_active=data.get("is_active", True),
            created_by=created_by,
        )

        # Compute first next_run_at
        if schedule.is_active:
            schedule.next_run_at = compute_next_run(
                schedule.schedule_type,
                schedule.schedule_day,
                schedule_time,
            )

        db.add(schedule)
        return schedule

    @staticmethod
    async def update_schedule(
        db: AsyncSession,
        tenant_id: UUID,
        schedule_id: int,
        data: Dict[str, Any],
    ) -> Optional[ScheduledExport]:
        schedule = await ScheduledExportService.get_schedule(db, tenant_id, schedule_id)
        if not schedule:
            return None

        if "export_config_id" in data:
            config_stmt = select(DataExportConfig).where(
                DataExportConfig.tenant_id == tenant_id,
                DataExportConfig.id == data["export_config_id"],
            )
            result = await db.execute(config_stmt)
            if not result.scalar_one_or_none():
                raise ValueError("Export configuration not found")

        if "schedule_time" in data and data["schedule_time"] is not None:
            data["schedule_time"] = _parse_time(data["schedule_time"])

        for key, value in data.items():
            if hasattr(schedule, key):
                setattr(schedule, key, value)

        # Recompute next_run_at
        if schedule.is_active:
            schedule.next_run_at = compute_next_run(
                schedule.schedule_type,
                schedule.schedule_day,
                schedule.schedule_time,
            )
        else:
            schedule.next_run_at = None

        return schedule

    @staticmethod
    async def delete_schedule(
        db: AsyncSession, tenant_id: UUID, schedule_id: int
    ) -> bool:
        schedule = await ScheduledExportService.get_schedule(db, tenant_id, schedule_id)
        if not schedule:
            return False
        await db.delete(schedule)
        return True

    # ── Execution ─────────────────────────────────────────────────

    @staticmethod
    async def execute_export(db: AsyncSession, schedule: ScheduledExport) -> None:
        """Generate CSV from the linked config and email it to all recipients."""
        config = schedule.export_config
        if not config:
            raise ValueError("Export configuration not found")

        # Salary gate: a schedule that carries salary/pay data may only run while
        # the user who owns it is still an active salary-viewer. If enrollment was
        # revoked (or the config was edited to add salary), skip the run rather
        # than emailing salary out unattended.
        if _config_touches_salary(config):
            from app.services.salary_enrollment_service import SalaryEnrollmentService

            owner_id = schedule.created_by
            owner_ok = owner_id is not None and await SalaryEnrollmentService.is_viewer(
                db, schedule.tenant_id, owner_id
            )
            if not owner_ok:
                raise SalaryAccessRevoked(
                    "Export contains salary data but its owner is not an approved "
                    "salary-viewer; run skipped."
                )

        # Run through the SAME path preview and download use. Previously this
        # called query_data directly, which meant a multi-source config raised
        # "Unknown data source: multi" on every single run — permanently, and
        # silently, for every schedule built from a joined report.
        from app.api.v1.data_export import spec_from_config

        spec = spec_from_config(config)
        rows, total, output_columns = await DataExportService.run_export(
            db, schedule.tenant_id, spec
        )

        from app.services.settings_service import SettingsService
        currency_code = await SettingsService.get_tenant_currency(db, schedule.tenant_id)
        if currency_code:
            from app.api.v1.data_export import _suffix_currency
            output_columns = _suffix_currency(
                output_columns, config.data_source, currency_code, config.column_aliases or {}
            )

        payload, mime, ext = DataExportService.serialise(
            rows, output_columns, config.output_format or "csv", sheet_name=config.name
        )

        # Build email
        from app.services.email_templates import scheduled_export_email
        subject, html_body = scheduled_export_email(
            config_name=config.name,
            schedule_type=schedule.schedule_type,
            row_count=total,
        )

        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M")
        filename = f"{config.data_source}_{timestamp}.{ext}"

        # Send to each recipient. A False return means SMTP is unconfigured or
        # refused the message; the run used to be recorded as a success anyway,
        # so nobody found out the report had not arrived.
        delivered = 0
        for email in schedule.recipient_emails:
            ok = await EmailService.send_email_with_attachment(
                db=db,
                to_email=email,
                subject=subject,
                html_body=html_body,
                attachment_content=payload,
                attachment_filename=filename,
                attachment_mime=mime,
            )
            if ok:
                delivered += 1

        if schedule.recipient_emails and delivered == 0:
            raise RuntimeError(
                "Export generated but could not be emailed to any recipient — "
                "check the SMTP settings."
            )

    @staticmethod
    async def check_and_run_due(db: AsyncSession) -> None:
        """Find all active schedules where next_run_at <= now, execute them."""
        now = datetime.utcnow()
        stmt = (
            select(ScheduledExport)
            .options(joinedload(ScheduledExport.export_config))
            .where(
                ScheduledExport.is_active == True,
                ScheduledExport.next_run_at != None,
                ScheduledExport.next_run_at <= now,
            )
        )
        result = await db.execute(stmt)
        due_schedules = list(result.scalars().unique().all())

        for schedule in due_schedules:
            status = "success"
            error = None
            try:
                await ScheduledExportService.execute_export(db, schedule)
                schedule.last_run_at = now
                schedule.last_run_status = "success"
                schedule.last_run_error = None
            except Exception as e:
                logger.exception("Scheduled export %d failed", schedule.id)
                schedule.last_run_at = now
                schedule.last_run_status = "failed"
                schedule.last_run_error = str(e)[:500]
                status = "failed"
                error = str(e)[:500]

            # Record the run in the JobRun ledger for the run-history UI.
            await ScheduledExportService._record_run(
                schedule.tenant_id, schedule.id, now, status, error
            )

            # Advance next_run_at
            schedule.next_run_at = compute_next_run(
                schedule.schedule_type,
                schedule.schedule_day,
                schedule.schedule_time,
            )

        if due_schedules:
            await db.commit()

    @staticmethod
    async def _record_run(tenant_id, schedule_id: int, when, status: str, error) -> None:
        from app.services.job_service import JobService
        await JobService.record(
            "scheduled_export",
            f"{schedule_id}:{when.isoformat()}",
            tenant_id=tenant_id,
            status=status,
            error=error,
            meta={"schedule_id": schedule_id},
        )

    @staticmethod
    async def get_run_history(
        db: AsyncSession, tenant_id: UUID, schedule_id: int, limit: int = 20
    ) -> list[dict]:
        """Recent JobRun rows for one schedule, newest first."""
        from app.models.job_run import JobRun
        stmt = (
            select(JobRun)
            .where(
                JobRun.job_name == "scheduled_export",
                JobRun.tenant_id == tenant_id,
                JobRun.period_key.like(f"{schedule_id}:%"),
            )
            .order_by(JobRun.started_at.desc())
            .limit(limit)
        )
        rows = (await db.execute(stmt)).scalars().all()
        return [
            {
                "id": r.id,
                "status": r.status,
                "error": r.error,
                "ran_at": r.started_at.isoformat() if r.started_at else None,
            }
            for r in rows
        ]


# ── Helpers ───────────────────────────────────────────────────────

def _parse_time(value) -> time:
    """Parse a time value from string 'HH:MM' or time object."""
    if isinstance(value, time):
        return value
    if isinstance(value, str):
        parts = value.split(":")
        return time(int(parts[0]), int(parts[1]))
    raise ValueError(f"Invalid time: {value}")


def compute_next_run(
    schedule_type: str,
    schedule_day: Optional[int],
    schedule_time: time,
    from_dt: Optional[datetime] = None,
) -> datetime:
    """Compute the next execution datetime."""
    now = from_dt or datetime.utcnow()
    today = now.date()

    if schedule_type == "daily":
        candidate = datetime.combine(today, schedule_time)
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate

    elif schedule_type == "weekly":
        # schedule_day: 0=Mon, 6=Sun
        target_weekday = schedule_day or 0
        days_ahead = target_weekday - today.weekday()
        if days_ahead < 0:
            days_ahead += 7
        candidate = datetime.combine(today + timedelta(days=days_ahead), schedule_time)
        if candidate <= now:
            candidate += timedelta(weeks=1)
        return candidate

    elif schedule_type == "monthly":
        target_day = schedule_day or 1
        # Try this month first
        try:
            candidate = datetime(today.year, today.month, target_day,
                                 schedule_time.hour, schedule_time.minute)
        except ValueError:
            # Day doesn't exist this month (e.g., Feb 30), skip to next month
            candidate = None

        if candidate and candidate > now:
            return candidate

        # Try next month
        if today.month == 12:
            next_month, next_year = 1, today.year + 1
        else:
            next_month, next_year = today.month + 1, today.year

        try:
            return datetime(next_year, next_month, target_day,
                            schedule_time.hour, schedule_time.minute)
        except ValueError:
            # Day doesn't exist next month either, skip another month
            if next_month == 12:
                next_month, next_year = 1, next_year + 1
            else:
                next_month += 1
            return datetime(next_year, next_month, min(target_day, 28),
                            schedule_time.hour, schedule_time.minute)

    raise ValueError(f"Unknown schedule type: {schedule_type}")
