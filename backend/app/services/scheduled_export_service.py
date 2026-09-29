"""
Scheduled Export Service

Manages CRUD for scheduled exports and handles execution of due schedules.

Three things this module guarantees, each the fix for something that went
wrong in production:

  * A due schedule is sent ONCE. CE runs the scheduler loop in every uvicorn
    worker (4 on the live install), and each worker used to read the same due
    rows and send them, so recipients got the same report 2-4 times. Now a
    worker first CLAIMS a schedule by moving its next_run_at forward with a
    conditional UPDATE (`... WHERE id = :id AND next_run_at = :old`); only the
    worker whose update matched sends. The claim is committed before sending.

  * One failing schedule cannot re-send the others. Each schedule is claimed,
    run and recorded in its own transaction. The whole batch used to share one
    commit at the end, so an exception mid-batch rolled back every
    next_run_at and the batch went out again a minute later.

  * "08:00" means 08:00 where the company is. The time is interpreted in the
    company's timezone (AppSettings.timezone, via SettingsService) and
    next_run_at is stored as an aware UTC instant. It used to be read as UTC,
    so 08:00 went out at 16:00 in Manila.

A schedule runs as its OWNER (created_by, or whoever last edited it): the
report covers the employees the owner may report on and shows the custom
fields the owner may see, and a report with pay data needs the owner to still
be an approved salary viewer. Nobody gets data by editing someone else's
schedule, because editing it makes them the owner.
"""

import html
import logging
from calendar import monthrange
from datetime import datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.models.data_export import DataExportConfig, ScheduledExport
from app.services.data_export_service import DataExportService
from app.services.data_source_registry import spec_touches_salary
from app.services.email_service import EmailService

logger = logging.getLogger(__name__)

# How many due schedules one tick looks at. The rest wait a minute.
BATCH = 50


def _config_touches_salary(config: DataExportConfig) -> bool:
    """Whether a saved export config references salary/pay data anywhere."""
    from app.api.v1.data_export import spec_from_config

    return spec_touches_salary(spec_from_config(config))


class SalaryAccessRevoked(Exception):
    """Raised when a scheduled export carrying salary data no longer has an
    enrolled salary-viewer behind it. Handled as a normal run failure so the
    schedule is skipped (not silently exfiltrating salary) and the reason is
    recorded in the run ledger."""


class OwnerUnavailable(Exception):
    """The schedule's owner can no longer run reports (deactivated, removed, or
    no longer allowed). The run is skipped and says why, rather than sending
    data on behalf of someone who could not download it themselves."""


def _utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Aware UTC. Some drivers (and SQLite in tests) hand timestamps back naive."""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _zone(tz_name: Optional[str]) -> ZoneInfo:
    try:
        return ZoneInfo(tz_name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


async def tenant_timezone(db: AsyncSession, tenant_id: UUID) -> str:
    from app.services.settings_service import SettingsService

    return await SettingsService.get_tenant_timezone(db, tenant_id)


def describe_next_run(next_run_at: Optional[datetime], tz_name: str) -> Optional[str]:
    """'Mon 29 Sep 2026, 08:00' in the company's timezone."""
    dt = _utc(next_run_at)
    if dt is None:
        return None
    local = dt.astimezone(_zone(tz_name))
    return local.strftime("%a %d %b %Y, %H:%M")


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
            .execution_options(populate_existing=True)
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
        schedule_day = _normalise_day(data["schedule_type"], data.get("schedule_day"))

        schedule = ScheduledExport(
            tenant_id=tenant_id,
            export_config_id=data["export_config_id"],
            schedule_type=data["schedule_type"],
            schedule_day=schedule_day,
            schedule_time=schedule_time,
            recipient_emails=[str(e) for e in data["recipient_emails"]],
            is_active=data.get("is_active", True),
            created_by=created_by,
        )

        # Compute first next_run_at
        if schedule.is_active:
            schedule.next_run_at = compute_next_run(
                schedule.schedule_type,
                schedule.schedule_day,
                schedule_time,
                tz_name=await tenant_timezone(db, tenant_id),
            )

        db.add(schedule)
        return schedule

    @staticmethod
    async def update_schedule(
        db: AsyncSession,
        tenant_id: UUID,
        schedule_id: int,
        data: Dict[str, Any],
        actor_id: Optional[int] = None,
    ) -> Optional[ScheduledExport]:
        """Edit, pause or resume.

        Changing anything other than paused/active makes the editor the owner:
        the schedule then runs with THEIR reach. Otherwise anyone allowed to
        edit schedules could add their own address to an administrator's
        schedule and receive the whole company's data every morning.
        """
        schedule = await ScheduledExportService.get_schedule(db, tenant_id, schedule_id)
        if not schedule:
            return None

        if "export_config_id" in data and data["export_config_id"] is not None:
            config_stmt = select(DataExportConfig).where(
                DataExportConfig.tenant_id == tenant_id,
                DataExportConfig.id == data["export_config_id"],
            )
            result = await db.execute(config_stmt)
            if not result.scalar_one_or_none():
                raise ValueError("Export configuration not found")

        if "schedule_time" in data and data["schedule_time"] is not None:
            data["schedule_time"] = _parse_time(data["schedule_time"])
        if "recipient_emails" in data and data["recipient_emails"] is not None:
            data["recipient_emails"] = [str(e) for e in data["recipient_emails"]]

        changes_content = any(k != "is_active" for k in data)
        for key, value in data.items():
            if value is None and key != "schedule_day":
                continue
            if hasattr(schedule, key):
                setattr(schedule, key, value)
        schedule.schedule_day = _normalise_day(schedule.schedule_type, schedule.schedule_day)
        if changes_content and actor_id is not None:
            schedule.created_by = actor_id

        # Recompute next_run_at
        if schedule.is_active:
            schedule.next_run_at = compute_next_run(
                schedule.schedule_type,
                schedule.schedule_day,
                schedule.schedule_time,
                tz_name=await tenant_timezone(db, tenant_id),
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
    async def _owner(db: AsyncSession, schedule: ScheduledExport):
        """The user the schedule runs as, if they may still run reports."""
        from app.models.role import UserRole
        from app.models.user import User as UserModel
        from app.services.permission_service import PermissionService

        if schedule.created_by is None:
            raise OwnerUnavailable(
                "Nobody owns this schedule any more, so it was not sent. Open it, check it "
                "and save it to take it over."
            )
        owner = (
            await db.execute(
                select(UserModel)
                .options(selectinload(UserModel.user_roles).selectinload(UserRole.role))
                .where(UserModel.id == schedule.created_by, UserModel.tenant_id == schedule.tenant_id)
            )
        ).scalar_one_or_none()
        if owner is None or not owner.is_active:
            raise OwnerUnavailable(
                "The person who set up this schedule no longer has an active account, so it "
                "was not sent. Open it, check it and save it to take it over."
            )
        if not owner.has_role("tenant_admin"):
            allowed = await PermissionService.check_permission(
                db, owner.tenant_id, owner.role_ids, "reports", "create"
            )
            if not allowed:
                raise OwnerUnavailable(
                    "The person who set up this schedule is no longer allowed to run reports, "
                    "so it was not sent."
                )
        return owner

    @staticmethod
    async def execute_export(db: AsyncSession, schedule: ScheduledExport) -> Dict[str, int]:
        """Build the linked report as its owner and email it to every recipient.

        Returns {"rows", "recipients", "delivered"}. Every send writes an
        email_log row (pending, then sent or failed), committed as it happens,
        so "did the report go out?" is answerable from the Email log even when
        SMTP is not set up.
        """
        config = schedule.export_config
        if not config:
            raise ValueError("Export configuration not found")

        owner = await ScheduledExportService._owner(db, schedule)

        # Run through the SAME path preview and download use. Previously this
        # called query_data directly, which meant a multi-source config raised
        # "Unknown data source: multi" on every single run — permanently, and
        # silently, for every schedule built from a joined report.
        from app.api.v1.data_export import _suffix_currency, spec_from_config

        spec = spec_from_config(config)

        # Salary gate: a schedule that touches salary/pay data anywhere may only
        # run while its owner is still an active salary-viewer. If enrollment
        # was revoked (or the report was edited to add pay), skip the run
        # rather than emailing salary out unattended.
        if spec_touches_salary(spec):
            from app.services.salary_enrollment_service import SalaryEnrollmentService

            if not await SalaryEnrollmentService.is_viewer(db, schedule.tenant_id, owner.id):
                raise SalaryAccessRevoked(
                    "Export contains salary data but its owner is not an approved "
                    "salary-viewer; run skipped."
                )

        from app.services.access_scope import managed_employee_ids

        scope = await managed_employee_ids(db, owner, "reports")
        rows, total, output_columns = await DataExportService.run_export(
            db, schedule.tenant_id, spec, viewer=owner, employee_scope=scope
        )

        from app.services.export_pipeline import resolve_date_window
        from app.services.settings_service import SettingsService

        currency_code = await SettingsService.get_tenant_currency(db, schedule.tenant_id)
        if currency_code:
            output_columns = _suffix_currency(
                output_columns, config.data_source, currency_code, config.column_aliases or {}
            )
        from app.utils.timeutil import company_today

        rfrom, rto = resolve_date_window(
            spec.get("date_preset"), spec.get("date_from"), spec.get("date_to"),
            today=await company_today(db, schedule.tenant_id),
        )
        payload, mime, ext = DataExportService.serialise(
            rows, output_columns, config.output_format or "csv", sheet_name=config.name,
            layout=config.layout,
            context={"report_name": config.name, "date_from": rfrom, "date_to": rto},
        )

        # Build email. The report name is typed by a user; escape it for HTML.
        from app.services.email_templates import scheduled_export_email
        _subject, html_body = scheduled_export_email(
            config_name=html.escape(config.name),
            schedule_type=schedule.schedule_type,
            row_count=total,
            file_format=ext,
        )
        # The template builds the subject from the escaped name; a subject is
        # plain text, so rebuild it from the real one.
        subject, _ = scheduled_export_email(
            config_name=config.name, schedule_type=schedule.schedule_type, row_count=total,
        )

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
        filename = f"{config.data_source}_{timestamp}.{ext}"

        # Send to each recipient. A False return means SMTP is unconfigured or
        # refused the message; the run used to be recorded as a success anyway,
        # so nobody found out the report had not arrived.
        from app.models.email_log import EmailLog

        recipients = list(schedule.recipient_emails or [])
        delivered = 0
        for email in recipients:
            # send_email_with_attachment has no logging hook (area A owns it),
            # so the log row is written here, the same way _send_raw writes its
            # own: pending first, so a crash mid-send still leaves a trace.
            log = EmailLog(
                tenant_id=schedule.tenant_id,
                user_id=owner.id,
                type="scheduled_export",
                to_email=email,
                subject=subject[:500],
                status="pending",
            )
            db.add(log)
            await db.commit()
            ok = await EmailService.send_email_with_attachment(
                db=db,
                to_email=email,
                subject=subject,
                html_body=html_body,
                attachment_content=payload,
                attachment_filename=filename,
                attachment_mime=mime,
            )
            log.status = "sent" if ok else "failed"
            log.sent_at = datetime.now(timezone.utc) if ok else None
            log.error_message = None if ok else (
                "Not delivered: email is not set up, or the mail server refused the message."
            )
            await db.commit()
            if ok:
                delivered += 1

        if recipients and delivered == 0:
            raise RuntimeError(
                "Export generated but could not be emailed to any recipient — "
                "check the SMTP settings."
            )
        return {"rows": total, "recipients": len(recipients), "delivered": delivered}

    @staticmethod
    async def claim(
        db: AsyncSession, schedule_id: int, old_next: datetime, new_next: Optional[datetime]
    ) -> bool:
        """Take one due run for this worker. True only for the worker whose
        conditional update matched; everyone else sees next_run_at already moved.
        Committed at once, so the claim survives a crash during the send."""
        result = await db.execute(
            update(ScheduledExport)
            .where(
                ScheduledExport.id == schedule_id,
                ScheduledExport.is_active == True,  # noqa: E712
                ScheduledExport.next_run_at == old_next,
            )
            .values(next_run_at=new_next)
            .returning(ScheduledExport.id)
            .execution_options(synchronize_session=False)
        )
        won = result.scalar_one_or_none() is not None
        await db.commit()
        return won

    @staticmethod
    async def run_one(
        db: AsyncSession, schedule_id: int, tenant_id: UUID, when: datetime, *, manual: bool = False
    ) -> Dict[str, Any]:
        """Execute one schedule and record the outcome, in its own transaction."""
        schedule = await ScheduledExportService.get_schedule(db, tenant_id, schedule_id)
        if schedule is None:
            return {"status": "missing"}
        status, error, meta, reason = "success", None, {}, None
        try:
            meta = await ScheduledExportService.execute_export(db, schedule)
        except Exception as e:  # noqa: BLE001 - every failure is recorded, none escapes
            if isinstance(e, SalaryAccessRevoked):
                reason = "salary"
            elif isinstance(e, OwnerUnavailable):
                reason = "owner"
            else:
                reason = "error"
                logger.exception("Scheduled export %d failed", schedule_id)
            await db.rollback()
            status, error = "failed", str(e)[:500]
            schedule = await ScheduledExportService.get_schedule(db, tenant_id, schedule_id)
            if schedule is None:
                return {"status": "missing"}

        schedule.last_run_at = when
        schedule.last_run_status = status
        schedule.last_run_error = error
        await ScheduledExportService._record_run(
            db, tenant_id, schedule_id, when, status, error, {**meta, "manual": manual}
        )
        await db.commit()
        return {"status": status, "error": error, "reason": reason, **meta}

    @staticmethod
    async def run_due(db: AsyncSession, now: Optional[datetime] = None) -> Dict[str, int]:
        """Claim and run every due schedule. Safe to call every minute from
        every worker at once: each due run is sent by exactly one caller.

        Returns counts for the scheduler's log: due, claimed (by this caller),
        succeeded, failed.
        """
        now = _utc(now) or datetime.now(timezone.utc)
        due = (
            await db.execute(
                select(
                    ScheduledExport.id,
                    ScheduledExport.tenant_id,
                    ScheduledExport.next_run_at,
                    ScheduledExport.schedule_type,
                    ScheduledExport.schedule_day,
                    ScheduledExport.schedule_time,
                )
                .where(
                    ScheduledExport.is_active == True,  # noqa: E712
                    ScheduledExport.next_run_at != None,  # noqa: E711
                    ScheduledExport.next_run_at <= now,
                )
                .order_by(ScheduledExport.next_run_at)
                .limit(BATCH)
            )
        ).all()
        await db.commit()

        counts = {"due": len(due), "claimed": 0, "succeeded": 0, "failed": 0}
        tz_cache: Dict[Any, str] = {}
        for sid, tenant_id, old_next, stype, sday, stime in due:
            try:
                if tenant_id not in tz_cache:
                    tz_cache[tenant_id] = await tenant_timezone(db, tenant_id)
                new_next = compute_next_run(stype, sday, stime, from_dt=now, tz_name=tz_cache[tenant_id])
                if not await ScheduledExportService.claim(db, sid, old_next, new_next):
                    continue
                counts["claimed"] += 1
                outcome = await ScheduledExportService.run_one(db, sid, tenant_id, now)
                counts["succeeded" if outcome.get("status") == "success" else "failed"] += 1
            except Exception:  # noqa: BLE001 - one broken schedule must not stop the rest
                logger.exception("Scheduled export %s could not be processed", sid)
                await db.rollback()
                counts["failed"] += 1
        return counts

    @staticmethod
    async def _record_run(
        db: AsyncSession, tenant_id, schedule_id: int, when: datetime, status: str,
        error: Optional[str], meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """One JobRun row per run, for the run-history view. Written in the
        caller's transaction so it commits (or not) with the run it describes."""
        from app.models.job_run import JobRun

        db.add(JobRun(
            job_name="scheduled_export",
            tenant_id=tenant_id,
            period_key=f"{schedule_id}:{_utc(when).isoformat()}"[:64],
            status=status,
            started_at=when,
            finished_at=datetime.now(timezone.utc),
            error=error,
            meta={"schedule_id": schedule_id, **(meta or {})},
        ))

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
            .order_by(JobRun.started_at.desc(), JobRun.id.desc())
            .limit(limit)
        )
        rows = (await db.execute(stmt)).scalars().all()
        out = []
        for r in rows:
            meta = r.meta or {}
            out.append({
                "id": r.id,
                "status": r.status,
                "error": r.error,
                "ran_at": _utc(r.started_at).isoformat() if r.started_at else None,
                "rows": meta.get("rows"),
                "delivered": meta.get("delivered"),
                "recipients": meta.get("recipients"),
            })
        return out


async def run_due(db: AsyncSession) -> Dict[str, int]:
    """Scheduler job: claim and run every due scheduled export (see module
    docstring). Idempotent and safe to call every minute from any number of
    processes."""
    return await ScheduledExportService.run_due(db)


# ── Helpers ───────────────────────────────────────────────────────

def _parse_time(value) -> time:
    """Parse a time value from string 'HH:MM' or time object."""
    if isinstance(value, time):
        return value
    if isinstance(value, str):
        parts = value.split(":")
        try:
            return time(int(parts[0]), int(parts[1]))
        except (ValueError, IndexError):
            pass
    raise ValueError(f"“{value}” is not a time. Enter a time like 08:00.")


def _normalise_day(schedule_type: str, day: Optional[int]) -> Optional[int]:
    """Weekly 0-6 (default Monday), monthly 1-31 (default the 1st), daily none.

    The old screen kept the weekday index when switching to monthly, so it
    could save "day 0 of the month", which never came round."""
    if schedule_type == "weekly":
        return day if day is not None and 0 <= day <= 6 else 0
    if schedule_type == "monthly":
        if day is None or day < 1:
            return 1
        return min(day, 31)
    return None


def compute_next_run(
    schedule_type: str,
    schedule_day: Optional[int],
    schedule_time: time,
    from_dt: Optional[datetime] = None,
    tz_name: str = "UTC",
) -> datetime:
    """The next run as an aware UTC instant, strictly after `from_dt`.

    `schedule_time` is a wall-clock time in `tz_name`. A monthly day past the
    end of a month (the 31st in April) runs on that month's last day.
    """
    tz = _zone(tz_name)
    now_utc = _utc(from_dt) or datetime.now(timezone.utc)
    local_now = now_utc.astimezone(tz)
    today = local_now.date()

    def at(d) -> datetime:
        return datetime(d.year, d.month, d.day, schedule_time.hour, schedule_time.minute, tzinfo=tz)

    if schedule_type == "daily":
        candidate = at(today)
        if candidate <= local_now:
            candidate = at(today + timedelta(days=1))
        return candidate.astimezone(timezone.utc)

    if schedule_type == "weekly":
        # schedule_day: 0=Mon, 6=Sun
        target_weekday = schedule_day or 0
        days_ahead = (target_weekday - today.weekday()) % 7
        candidate = at(today + timedelta(days=days_ahead))
        if candidate <= local_now:
            candidate = at(today + timedelta(days=days_ahead + 7))
        return candidate.astimezone(timezone.utc)

    if schedule_type == "monthly":
        want = _normalise_day("monthly", schedule_day)
        year, month = today.year, today.month
        for _ in range(3):
            day = min(want, monthrange(year, month)[1])
            candidate = at(today.replace(year=year, month=month, day=day))
            if candidate > local_now:
                return candidate.astimezone(timezone.utc)
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)

    raise ValueError(f"Unknown schedule type: {schedule_type}")
