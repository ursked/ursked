"""Payroll and attendance reactions to other areas' changes (domain_events).

shift.before_write: a shift inside an approved or finalized payroll period is
what that run paid. Until 2026-09 it stayed editable, so the grid and the
payslip could quietly disagree about the same day. Such writes are refused,
naming the period, and the whole change rolls back.

shift.after_write, holiday.changed: attendance, lateness, overtime and
undertime are derived from the day's published roster and its holidays.
Nothing re-derived them when either changed, so moving a shift left
yesterday's lateness standing and adding a holiday paid no holiday premium
through the policy engine. Only days that already have attendance or punches
are touched, and never a day a locked period has paid.

leave.status_changed: approving leave for a past day turns that day's
"absent" into "excused"; revoking it puts the absence back.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable, Set, Tuple

from fastapi import HTTPException, status
from sqlalchemy import select

from app.models.attendance import AttendanceRecord, TimePunch
from app.models.user import User
from app.services.domain_events import on

Pair = Tuple[int, date]


@on("shift.before_write")
async def refuse_writes_in_locked_payroll(db, tenant_id, actor, changes, **_):
    from app.services.payroll_service import PayrollService

    locked = await PayrollService.locked_periods_for(db, tenant_id, changes)
    if not locked:
        return
    (emp_id, d), period = sorted(locked.items(), key=lambda kv: (kv[0][1], kv[0][0]))[0]
    emp = await db.get(User, emp_id)
    name = f"{emp.first_name} {emp.last_name}".strip() if emp else "this employee"
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=PayrollService.locked_message(period, name, d, extra=len(locked) - 1),
    )


async def rederive_days(db, tenant_id, pairs: Iterable[Pair]) -> int:
    """Re-derive attendance for the (employee, date) pairs that already have
    a record or punches, skipping days a locked payroll period has paid.
    Returns how many days were re-derived."""
    from app.services.attendance_service import AttendanceService
    from app.services.payroll_service import PayrollService

    pairs: Set[Pair] = {(e, d) for e, d in pairs if e is not None and d is not None}
    if not pairs:
        return 0
    emp_ids = {e for e, _ in pairs}
    lo, hi = min(d for _, d in pairs), max(d for _, d in pairs)

    records = {
        (r.employee_id, r.date): r
        for r in (await db.execute(
            select(AttendanceRecord).where(
                AttendanceRecord.tenant_id == tenant_id,
                AttendanceRecord.employee_id.in_(emp_ids),
                AttendanceRecord.date >= lo,
                AttendanceRecord.date <= hi,
            )
        )).scalars().all()
        if (r.employee_id, r.date) in pairs
    }
    punch_days = {
        (e, d) for e, d in (await db.execute(
            select(TimePunch.employee_id, TimePunch.business_date).where(
                TimePunch.tenant_id == tenant_id,
                TimePunch.employee_id.in_(emp_ids),
                TimePunch.business_date >= lo,
                TimePunch.business_date <= hi,
            ).distinct()
        )).all()
        if (e, d) in pairs
    }
    todo = set(records) | punch_days
    if not todo:
        return 0
    locked = await PayrollService.locked_periods_for(db, tenant_id, todo)
    done = 0
    for key in sorted(todo, key=lambda k: (k[1], k[0])):
        if key in locked:
            continue
        rec = records.get(key)
        if rec is not None:
            await AttendanceService.rederive(db, rec)
        else:
            await AttendanceService.sync_from_punches(db, tenant_id, key[0], key[1])
        done += 1
    return done


@on("shift.after_write")
async def rederive_after_shift_write(db, tenant_id, actor, changes, **_):
    await rederive_days(db, tenant_id, changes)


@on("holiday.changed")
async def rederive_after_holiday_change(db, tenant_id, actor, dates, **_):
    dates = {d for d in dates if d is not None}
    if not dates:
        return
    # The day before too: a night shift that starts on the eve of a holiday
    # works into it.
    wanted = dates | {d - timedelta(days=1) for d in dates}
    rows = (await db.execute(
        select(AttendanceRecord.employee_id, AttendanceRecord.date).where(
            AttendanceRecord.tenant_id == tenant_id,
            AttendanceRecord.date.in_(sorted(wanted)),
        )
    )).all()
    await rederive_days(db, tenant_id, [(e, d) for e, d in rows])


@on("leave.status_changed")
async def rederive_after_leave_change(db, tenant_id, actor, application, old_status, new_status, **_):
    """Approved: the leave's days that were marked absent become excused.
    No longer approved: they go back to what the times say."""
    if "approved" not in (old_status, new_status):
        return
    start, end = application.start_date, application.end_date
    if not start or not end:
        return
    rows = (await db.execute(
        select(AttendanceRecord).where(
            AttendanceRecord.tenant_id == tenant_id,
            AttendanceRecord.employee_id == application.employee_id,
            AttendanceRecord.date >= start,
            AttendanceRecord.date <= end,
        )
    )).scalars().all()
    await rederive_days(db, tenant_id, [(r.employee_id, r.date) for r in rows])
