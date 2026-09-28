"""What a day on the schedule means, in one place.

Two copies of these rules had drifted apart. The report builder's schedules
source treated a `free` shift as a working day and the formal work-schedule
exporter treated it as a rest day, so the same shift said FREE in one file and
was blank in the other. Neither knew about `holiday_off`, and both ignored the
tenant's own status types: a company that added a "Day off (swap)" status with
category "rest" saw it exported as a working day with break times.

Every export that has to decide "is this a rest day?", "what goes in
REMARKS?" or "when is the break?" asks here:

  * A status is a rest day when the tenant's status type for it has category
    "rest", or it is one of the historical spellings in LEGACY_REST_ALIASES
    (older installs and imported rosters use them without a status type).
  * A day with no shift at all is an off day too, when a report asks to show
    every calendar day.
  * REMARKS is, in order: the leave type's export code (SL, VL, ...), then
    "HOL OFF" for a holiday the employee does not work, then the shift's own
    remark. A holiday somebody works is not "HOL OFF": stamping it on worked
    rows (audit G-4) told payroll the day was unworked.
  * Breaks come from the employee's schedule format, offset from the shift
    start. Rest days have none.

Holidays themselves come from holiday_calendar.holidays_between, never from
DateRemark directly, so recurring holidays count.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any, Dict, FrozenSet, Optional, Tuple
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Historical spellings of "not working today". `free` is the one the two old
# copies disagreed about; `holiday_off` is a system status with category rest.
LEGACY_REST_ALIASES: FrozenSet[str] = frozenset(
    {"rest_day", "rest day", "restday", "day_off", "day off", "free", "holiday_off"}
)

HOLIDAY_OFF_STATUS = "holiday_off"
HOLIDAY_REMARK = "HOL OFF"
# What the Day Work Status column says on a day off, unless a report asks for
# different wording.
DEFAULT_REST_LABEL = "FREE"


def _norm(status: Optional[str]) -> str:
    return (status or "").lower().strip()


async def rest_statuses(db: AsyncSession, tenant_id: UUID) -> FrozenSet[str]:
    """Every status code that means "not working" for this tenant."""
    from app.models.settings import ShiftStatusType

    codes = (
        await db.execute(
            select(ShiftStatusType.code).where(
                ShiftStatusType.tenant_id == tenant_id,
                ShiftStatusType.category == "rest",
            )
        )
    ).scalars().all()
    return frozenset(LEGACY_REST_ALIASES | {_norm(c) for c in codes})


def is_rest(status: Optional[str], rest_set: FrozenSet[str]) -> bool:
    return _norm(status) in rest_set


async def leave_export_codes(db: AsyncSession, tenant_id: UUID) -> Dict[str, str]:
    """{leave_type_code: export_code} for the REMARKS column."""
    from app.models.leave import LeaveType

    rows = (
        await db.execute(select(LeaveType).where(LeaveType.tenant_id == tenant_id))
    ).scalars().all()
    return {lt.code: (lt.export_code or lt.code.upper()) for lt in rows}


def leave_code_for(
    leave_type_code: Optional[str], status: Optional[str], leave_codes: Dict[str, str]
) -> str:
    """The export code for a leave day, or "".

    A shift overlaid by an approved leave carries the application; a leave
    status set on the grid by hand carries only the status, which is the leave
    type's code, so both are recognised.
    """
    if leave_type_code:
        return leave_codes.get(leave_type_code, "")
    return leave_codes.get(status or "", "")


def export_remark(
    *,
    leave_code: str,
    off_day: bool,
    is_holiday: bool,
    status: Optional[str] = None,
    shift_remarks: Optional[str] = None,
) -> str:
    if leave_code:
        return leave_code
    if off_day and (is_holiday or _norm(status) == HOLIDAY_OFF_STATUS):
        return HOLIDAY_REMARK
    return shift_remarks or ""


def _add_minutes(t: time, minutes: int) -> time:
    base = datetime(2000, 1, 1, t.hour, t.minute, t.second)
    return (base + timedelta(minutes=minutes)).time()


def derive_breaks(
    fmt: Any, start: Optional[time]
) -> Tuple[Optional[time], Optional[time], Optional[time], Optional[time]]:
    """(paid_start, paid_end, unpaid_start, unpaid_end) from a schedule format.

    `fmt` is a ScheduleFormat or anything with the same four attributes. A
    break starts `*_break_after_hours` after the shift starts; an offset of 0
    means at the start, which the report builder used to show as no break at
    all while the formal exporter showed it.
    """
    paid_s = paid_e = unpaid_s = unpaid_e = None
    if fmt is None or not isinstance(start, time):
        return paid_s, paid_e, unpaid_s, unpaid_e
    paid = int(getattr(fmt, "paid_break_minutes", 0) or 0)
    unpaid = int(getattr(fmt, "unpaid_break_minutes", 0) or 0)
    if paid > 0:
        paid_s = _add_minutes(start, int(float(getattr(fmt, "paid_break_after_hours", 0) or 0) * 60))
        paid_e = _add_minutes(paid_s, paid)
    if unpaid > 0:
        unpaid_s = _add_minutes(start, int(float(getattr(fmt, "unpaid_break_after_hours", 0) or 0) * 60))
        unpaid_e = _add_minutes(unpaid_s, unpaid)
    return paid_s, paid_e, unpaid_s, unpaid_e


def formal_name(first_name: Optional[str], middle_name: Optional[str], last_name: Optional[str]) -> str:
    """LASTNAME, FIRST MIDDLE, as User.formal_name, for rows loaded as columns."""
    given = " ".join(p for p in [first_name, middle_name] if p).upper()
    last = (last_name or "").upper()
    return f"{last}, {given}".strip().rstrip(",").strip()
