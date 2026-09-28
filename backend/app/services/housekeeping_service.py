"""Daily housekeeping, and the "due for deletion" retention report.

Nothing was ever pruned: on the live install 82 of 83 login sessions had
expired and were still there, and read notifications, login events and audit
entries only ever grew. The daily job (registered in app.services.scheduler,
run once per company-local day after CLEANUP_HOUR) removes housekeeping data
only:

  * login sessions that have expired (they can no longer be used or revoked);
  * notifications the recipient has read, after read_notification_retention_days;
  * sign-in events (login_success / login_failure audit rows), after
    login_history_retention_days;
  * every other audit entry, after audit_log_retention_days (two years by
    default);
  * finished email_outbox rows, email_logs, old job_runs and spent
    password-reset tokens (fixed windows below).

It never deletes business records: shifts, attendance, leave, payroll,
compensation and employees are only ever REPORTED. `data_retention_days`
drives `retention_report`, which counts the records of employees separated
longer than that window, by type, for an administrator to act on. Deleting
payroll or leave history automatically is an irreversible decision with legal
record-keeping implications, and is not the app's to make.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Dict, Optional

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import AppSettings
from app.utils.timeutil import company_today, utcnow, zone

logger = logging.getLogger(__name__)

JOB_NAME = "housekeeping"
# Local hour after which a company's daily housekeeping runs (quiet hours).
CLEANUP_HOUR = 3

# Defaults for the tenant settings, used when a row predates them.
DEFAULT_AUDIT_DAYS = 730
DEFAULT_LOGIN_HISTORY_DAYS = 180
DEFAULT_READ_NOTIFICATION_DAYS = 90

# Fixed windows for platform bookkeeping.
EMAIL_LOG_DAYS = 365
OUTBOX_FINISHED_DAYS = 30
# Over a year, so a yearly job's claim (carry-over for year Y is claimed during
# Y+1) is never pruned while it could still be claimed again.
JOB_RUN_DAYS = 400
RESET_TOKEN_DAYS = 30

# Audit actions that are sign-in noise rather than a record of a change.
LOGIN_ACTIONS = ("login_success", "login_failure")


def _days(value: Optional[int], default: int) -> int:
    return value if value and value > 0 else default


def windows(settings: Optional[AppSettings]) -> Dict[str, int]:
    """A company's retention windows in days, defaults filled in."""
    return {
        "audit": _days(getattr(settings, "audit_log_retention_days", None), DEFAULT_AUDIT_DAYS),
        "login": _days(getattr(settings, "login_history_retention_days", None), DEFAULT_LOGIN_HISTORY_DAYS),
        "notifications": _days(
            getattr(settings, "read_notification_retention_days", None), DEFAULT_READ_NOTIFICATION_DAYS
        ),
    }


async def prune_tenant(db: AsyncSession, tenant_id, days: Dict[str, int], now: datetime) -> Dict[str, int]:
    """Delete one tenant's housekeeping data that is past its window (`days`,
    from windows()). Does not commit."""
    from app.models.email_log import EmailLog
    from app.models.email_outbox import EmailOutbox
    from app.models.notification import Notification
    from app.models.site_settings import AuditLog
    from app.models.user import UserSession

    audit_days, login_days, notif_days = days["audit"], days["login"], days["notifications"]

    async def _delete(stmt) -> int:
        return (await db.execute(stmt.execution_options(synchronize_session=False))).rowcount or 0

    out = {
        "sessions": await _delete(delete(UserSession).where(
            UserSession.tenant_id == tenant_id, UserSession.expires_at < now,
        )),
        "notifications": await _delete(delete(Notification).where(
            Notification.tenant_id == tenant_id,
            Notification.is_read == True,  # noqa: E712
            Notification.created_at < now - timedelta(days=notif_days),
        )),
        "login_events": await _delete(delete(AuditLog).where(
            AuditLog.tenant_id == tenant_id,
            AuditLog.action.in_(LOGIN_ACTIONS),
            AuditLog.created_at < now - timedelta(days=login_days),
        )),
        "audit_entries": await _delete(delete(AuditLog).where(
            AuditLog.tenant_id == tenant_id,
            AuditLog.action.notin_(LOGIN_ACTIONS),
            AuditLog.created_at < now - timedelta(days=audit_days),
        )),
        "email_logs": await _delete(delete(EmailLog).where(
            EmailLog.tenant_id == tenant_id,
            EmailLog.created_at < now - timedelta(days=EMAIL_LOG_DAYS),
        )),
        "email_outbox": await _delete(delete(EmailOutbox).where(
            EmailOutbox.tenant_id == tenant_id,
            EmailOutbox.status != "queued",
            EmailOutbox.created_at < now - timedelta(days=OUTBOX_FINISHED_DAYS),
        )),
    }
    return out


async def prune_platform(db: AsyncSession, now: datetime) -> Dict[str, int]:
    """Tenant-less bookkeeping: system email, scheduler records, reset tokens.
    Does not commit."""
    from app.models.email_log import EmailLog
    from app.models.email_outbox import EmailOutbox
    from app.models.job_run import JobRun
    from app.models.user import PasswordResetToken

    async def _delete(stmt) -> int:
        return (await db.execute(stmt.execution_options(synchronize_session=False))).rowcount or 0

    return {
        "email_logs": await _delete(delete(EmailLog).where(
            EmailLog.tenant_id.is_(None),
            EmailLog.created_at < now - timedelta(days=EMAIL_LOG_DAYS),
        )),
        "email_outbox": await _delete(delete(EmailOutbox).where(
            EmailOutbox.tenant_id.is_(None),
            EmailOutbox.status != "queued",
            EmailOutbox.created_at < now - timedelta(days=OUTBOX_FINISHED_DAYS),
        )),
        "job_runs": await _delete(delete(JobRun).where(
            JobRun.status != "running",
            JobRun.started_at < now - timedelta(days=JOB_RUN_DAYS),
        )),
        "reset_tokens": await _delete(delete(PasswordResetToken).where(
            PasswordResetToken.expires_at < now - timedelta(days=RESET_TOKEN_DAYS),
        )),
    }


async def run_due(db: AsyncSession, *, now: Optional[datetime] = None) -> dict:
    """Scheduler job (DAILY cadence): once per company-local day, after
    CLEANUP_HOUR local time, prune that company's housekeeping data; once per
    UTC day, the platform's. Each unit is claimed in job_runs, so extra calls
    (every hour, a second worker, a restart) do nothing."""
    from app.models.tenant import Tenant
    from app.services.job_service import JobService

    now = now or utcnow()
    totals: Dict[str, int] = {}

    def _add(res: Dict[str, int]) -> None:
        for k, v in res.items():
            totals[k] = totals.get(k, 0) + v

    tenant_ids = (await db.execute(select(Tenant.id))).scalars().all()
    # Plain values, read up front: the rollback below expires ORM objects.
    per_tenant = {
        s.tenant_id: (s.timezone, windows(s))
        for s in (await db.execute(select(AppSettings))).scalars().all()
    }
    await db.rollback()  # do not sit in a transaction while claiming

    for tenant_id in tenant_ids:
        tz_name, days = per_tenant.get(tenant_id, (None, windows(None)))
        local = now.astimezone(zone(tz_name))
        if local.hour < CLEANUP_HOUR:
            continue
        claim = await JobService.claim(JOB_NAME, local.date().isoformat(), tenant_id)
        if claim is None:
            continue
        try:
            res = await prune_tenant(db, tenant_id, days, now)
            await db.commit()
        except Exception as exc:  # noqa: BLE001 - one tenant must not stop the rest
            logger.exception("Housekeeping failed for tenant %s", tenant_id)
            await db.rollback()
            await JobService.finish(claim, status="failed", error=str(exc)[:2000])
            continue
        await JobService.finish(claim, status="success", meta=res)
        _add(res)

    claim = await JobService.claim(JOB_NAME, now.date().isoformat(), None)
    if claim is not None:
        try:
            res = await prune_platform(db, now)
            await db.commit()
            await JobService.finish(claim, status="success", meta=res)
            _add(res)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Platform housekeeping failed")
            await db.rollback()
            await JobService.finish(claim, status="failed", error=str(exc)[:2000])
    return totals


# ── Retention report (no deletion) ───────────────────────────────────

async def retention_report(db: AsyncSession, tenant_id) -> dict:
    """What `data_retention_days` flags as due for deletion: records of
    employees separated longer ago than the window, counted by type.

    Read-only. With no retention window set, nothing is due.
    """
    from app.models.attendance import AttendanceRecord, OvertimeLog, TardinessRecord, TimePunch
    from app.models.compensation import CompensationItem
    from app.models.leave import LeaveApplication
    from app.models.payroll import EmployeeSalary, PayrollItem
    from app.models.schedule import Shift
    from app.models.user import User

    days = (await db.execute(
        select(AppSettings.data_retention_days).where(AppSettings.tenant_id == tenant_id)
    )).scalar()
    today = await company_today(db, tenant_id)
    if not days:
        return {"retention_days": None, "cutoff_date": None, "employees": [], "counts": [], "total": 0}

    cutoff = today - timedelta(days=days)
    due = and_(
        User.tenant_id == tenant_id,
        User.separation_date.isnot(None),
        User.separation_date < cutoff,
        or_(User.is_active == False, User.is_active.is_(None)),  # noqa: E712 - reinstated people are not due
    )
    people = (await db.execute(
        select(User.id, User.first_name, User.last_name, User.separation_date)
        .where(due).order_by(User.separation_date, User.last_name)
    )).all()
    ids = [p.id for p in people]

    kinds = (
        ("shifts", "Schedule entries", Shift),
        ("attendance", "Attendance records", AttendanceRecord),
        ("punches", "Time clock punches", TimePunch),
        ("overtime", "Overtime records", OvertimeLog),
        ("tardiness", "Lateness records", TardinessRecord),
        ("leave", "Leave requests", LeaveApplication),
        ("salary_history", "Salary history", EmployeeSalary),
        ("compensation", "Allowances and adjustments", CompensationItem),
        ("payslips", "Payslip lines", PayrollItem),
    )
    counts = [{"type": "employees", "label": "Separated employees", "count": len(ids)}]
    for key, label, model in kinds:
        n = 0
        if ids:
            n = (await db.execute(
                select(func.count()).select_from(model).where(model.employee_id.in_(ids))
            )).scalar() or 0
        counts.append({"type": key, "label": label, "count": int(n)})
    return {
        "retention_days": days,
        "cutoff_date": cutoff.isoformat(),
        "employees": [
            {
                "id": p.id,
                "name": f"{p.first_name or ''} {p.last_name or ''}".strip(),
                "separation_date": p.separation_date.isoformat() if p.separation_date else None,
            }
            for p in people[:200]
        ],
        "counts": counts,
        "total": sum(c["count"] for c in counts),
    }
