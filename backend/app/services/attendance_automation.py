"""Attendance jobs: automatic clock-out and no-show absences.

`run_due(db)` is safe to call every minute and does only what is due. Area A's
scheduler registers it by dotted path:

    app.services.attendance_automation.run_due

Auto clock-out: a clock-in nobody closed used to stay open forever. It blocked
the next day's clock-in and was then closed by whatever punch came next, giving
yesterday a 24-hour day. An open punch is now closed at its shift's SCHEDULED
END (not at the moment the job notices), once auto_clockout_after_hours have
passed since that end, or, with no shift, auto_clockout_unscheduled_hours after
the clock-in. The closing punch is flagged auto_closed for review.

Auto absent: nobody was ever marked absent for not turning up, so attendance
rates only counted absences someone typed in. A published work shift that has
started (plus auto_absent_after_minutes) and ended, with no attendance record,
no punch, no approved leave and no holiday, gets an 'absent' record, flagged
auto_marked. Judged in the tenant's timezone; never for a future day.

Absences are only marked for tenants that use the time clock: without it there
is no automatic evidence that anyone came in, and a company that records
attendance by hand at the end of the week would find everyone marked absent.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attendance import AttendanceRecord, TimePunch
from app.models.leave import LeaveApplication
from app.models.schedule import Shift
from app.models.settings import AppSettings
from app.models.user import User
from app.services.attendance_service import AttendanceService, tenant_zone, to_local
from app.services.payroll_compute import span

logger = logging.getLogger(__name__)

# How far back the no-show sweep looks. Idempotent, so a scheduler that was
# down for a day or two catches up; older days are left to people.
ABSENT_LOOKBACK_DAYS = 3


async def close_forgotten_punches(
    db: AsyncSession, settings: AppSettings, now: datetime,
) -> int:
    from app.services.timeclock_service import TimeclockService

    open_punches = (await db.execute(
        select(TimePunch).where(
            TimePunch.tenant_id == settings.tenant_id,
            TimePunch.punch_type == "in",
            TimePunch.paired_punch_id.is_(None),
        ).order_by(TimePunch.punched_at)
    )).scalars().all()
    closed = 0
    for punch in open_punches:
        close_at, deadline = await TimeclockService.auto_close_times(db, punch, settings)
        if now < deadline:
            continue
        await TimeclockService.auto_close(db, punch, close_at, settings)
        closed += 1
    return closed


async def mark_no_shows(db: AsyncSession, settings: AppSettings, now: datetime) -> int:
    from app.services.holiday_calendar import holidays_between
    from app.services.payroll_service import PayrollService

    if not settings.auto_mark_absent or not settings.timeclock_enabled:
        return 0
    tenant_id = settings.tenant_id
    tz = tenant_zone(settings)
    local_now = to_local(now, tz)
    today = local_now.date()
    first = today - timedelta(days=ABSENT_LOOKBACK_DAYS)
    grace = timedelta(minutes=settings.auto_absent_after_minutes or 120)

    category_map = await AttendanceService._category_map(db, tenant_id)
    shifts = (await db.execute(
        select(Shift)
        .join(User, User.id == Shift.employee_id)
        .where(
            Shift.tenant_id == tenant_id,
            Shift.is_published == True,  # noqa: E712
            Shift.date >= first,
            Shift.date <= today,
            Shift.start_time.isnot(None),
            Shift.end_time.isnot(None),
            User.is_active == True,  # noqa: E712
        )
        .order_by(Shift.date, Shift.employee_id, Shift.sequence_number)
    )).scalars().all()

    # Per (employee, day): due once its LAST work segment has ended and its
    # first has been under way for the grace period. A split day with the
    # afternoon still to come is not a no-show yet.
    days: Dict[tuple, list] = {}
    for s in shifts:
        if not AttendanceService.is_work_status(s.status, category_map):
            continue
        days.setdefault((s.employee_id, s.date), []).append(span(s.date, s.start_time, s.end_time))
    due = [
        key for key, segs in days.items()
        if min(a for a, _ in segs) + grace <= local_now and max(b for _, b in segs) <= local_now
    ]
    if not due:
        return 0

    emp_ids = {e for e, _ in due}
    have_record = {
        (e, d) for e, d in (await db.execute(
            select(AttendanceRecord.employee_id, AttendanceRecord.date).where(
                AttendanceRecord.tenant_id == tenant_id,
                AttendanceRecord.employee_id.in_(emp_ids),
                AttendanceRecord.date >= first,
            )
        )).all()
    }
    have_punch = {
        (e, d) for e, d in (await db.execute(
            select(TimePunch.employee_id, TimePunch.business_date).where(
                TimePunch.tenant_id == tenant_id,
                TimePunch.employee_id.in_(emp_ids),
                TimePunch.business_date >= first,
            ).distinct()
        )).all()
    }
    leaves = (await db.execute(
        select(LeaveApplication.employee_id, LeaveApplication.start_date, LeaveApplication.end_date).where(
            LeaveApplication.tenant_id == tenant_id,
            LeaveApplication.employee_id.in_(emp_ids),
            LeaveApplication.status == "approved",
            LeaveApplication.start_date <= today,
            LeaveApplication.end_date >= first,
        )
    )).all()
    holidays = await holidays_between(db, tenant_id, first, today)
    locked = await PayrollService.locked_periods_for(db, tenant_id, due)

    marked = 0
    for emp_id, d in sorted(due, key=lambda k: (k[1], k[0])):
        key = (emp_id, d)
        if key in have_record or key in have_punch or key in locked or d in holidays:
            continue
        if any(e == emp_id and s <= d <= t for e, s, t in leaves):
            continue
        record = AttendanceRecord(
            tenant_id=tenant_id, employee_id=emp_id, date=d,
            auto_marked=True,
            notes="Marked absent automatically: no clock-in for a published shift.",
        )
        db.add(record)
        await db.flush()
        await AttendanceService.rederive(db, record)
        marked += 1
    return marked


async def run_due(db: AsyncSession) -> dict:
    """Close forgotten clock-ins and mark no-shows for every tenant. Commits."""
    now = datetime.now(timezone.utc)
    totals = {"auto_closed": 0, "marked_absent": 0, "errors": 0}
    tenant_ids = (await db.execute(select(AppSettings.tenant_id))).scalars().all()
    for tenant_id in tenant_ids:
        try:
            settings = (await db.execute(
                select(AppSettings).where(AppSettings.tenant_id == tenant_id)
            )).scalar_one()
            totals["auto_closed"] += await close_forgotten_punches(db, settings, now)
            totals["marked_absent"] += await mark_no_shows(db, settings, now)
            await db.commit()
        except Exception:  # noqa: BLE001 - one tenant must not stop the rest
            logger.exception("Attendance automation failed for tenant %s", tenant_id)
            await db.rollback()
            totals["errors"] += 1
    return totals
