"""How many leave days a request consumes, and which ones.

Leave used to be counted Monday to Friday, whatever the roster said. On the
live install that meant 922 weekend work shifts could be taken as leave for
free (weekend workers were told "No business days"), 912 weekday rest days
were charged as leave, and holidays inside a leave consumed credits.

Decision (2026-09): a day counts when the employee has a scheduled WORKING
shift that day (status category "work", draft or published) and it is not a
holiday. For a day with nothing on the roster, fall back to the company work
week (AppSettings.work_week_days) minus holidays. A half-day request is a
single day and counts 0.5.

Holidays come only from holiday_calendar, so recurring holidays count.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.schedule import Shift
from app.models.settings import AppSettings, ShiftStatusType
from app.services.holiday_calendar import holidays_between

DEFAULT_WORK_WEEK = [0, 1, 2, 3, 4]
WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# What the system status codes mean when a tenant has no shift_status_types row
# for them (very old installs, and the test database). Anything else unknown is
# treated as "not work", matching the grid's own fallback.
_BUILTIN_CATEGORY = {"scheduled": "work", "rest_day": "rest", "holiday_off": "rest"}


@dataclass
class DayCount:
    days: float
    breakdown: List[dict] = field(default_factory=list)

    @property
    def by_year(self) -> Dict[int, float]:
        return days_by_year(self.breakdown)


def days_by_year(breakdown: Optional[List[dict]]) -> Dict[int, float]:
    out: Dict[int, float] = defaultdict(float)
    for d in breakdown or []:
        out[int(str(d["date"])[:4])] += float(d.get("days") or 0)
    return dict(out)


def legacy_days_in_year(start: date, end: date, days_requested: float, year: int) -> float:
    """The share of an old (pre-breakdown) request falling in `year`.

    Those requests were counted Monday to Friday, so split them the same way:
    a request is never re-priced after the fact, only apportioned.
    """
    total = 0
    in_year = 0
    d = start
    while d <= end:
        if d.weekday() < 5:
            total += 1
            if d.year == year:
                in_year += 1
        d += timedelta(days=1)
    if total == 0:
        return float(days_requested) if start.year == year else 0.0
    return round(float(days_requested) * in_year / total, 4)


async def work_week(db: AsyncSession, tenant_id: UUID) -> List[int]:
    row = (
        await db.execute(
            select(AppSettings.work_week_days).where(AppSettings.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if not row:
        return list(DEFAULT_WORK_WEEK)
    return sorted({int(d) for d in row if 0 <= int(d) <= 6}) or list(DEFAULT_WORK_WEEK)


async def count_leave_days(
    db: AsyncSession,
    tenant_id: UUID,
    employee_id: int,
    start: date,
    end: date,
    *,
    half_day: Optional[str] = None,
    application_id: Optional[int] = None,
) -> DayCount:
    """Count the leave days in [start, end] for one employee.

    `application_id` is the request being recounted, if any. Once approved, its
    own leave has been painted onto the roster; those shifts are read as what
    they were before the overlay (original_status), and a shift the overlay
    created from nothing is ignored, so recounting an approved request gives
    the same answer as counting it the first time.
    """
    if end < start:
        return DayCount(0.0, [])

    holidays = await holidays_between(db, tenant_id, start, end)
    week = set(await work_week(db, tenant_id))

    cats = dict(_BUILTIN_CATEGORY)
    for code, category in (
        await db.execute(
            select(ShiftStatusType.code, ShiftStatusType.category).where(
                ShiftStatusType.tenant_id == tenant_id
            )
        )
    ).all():
        cats[code] = category

    shifts_by_day: Dict[date, List[str]] = defaultdict(list)
    for s in (
        await db.execute(
            select(Shift).where(
                Shift.tenant_id == tenant_id,
                Shift.employee_id == employee_id,
                Shift.date >= start,
                Shift.date <= end,
            )
        )
    ).scalars().all():
        status = s.status
        if application_id is not None and s.leave_application_id == application_id:
            if s.original_status is None:
                continue  # created by this request's own overlay
            status = s.original_status
        shifts_by_day[s.date].append(status)

    breakdown: List[dict] = []
    total = 0.0
    d = start
    while d <= end:
        entry = {"date": d.isoformat(), "days": 0.0}
        statuses = shifts_by_day.get(d)
        if d in holidays:
            entry.update(reason="holiday", label=f"Holiday: {holidays[d].title}")
        elif statuses:
            categories = {cats.get(st, "leave") for st in statuses}
            if "work" in categories:
                entry.update(days=1.0, reason="shift", label="Scheduled to work")
            elif "rest" in categories:
                entry.update(reason="rest_day", label="Rest day on the schedule")
            else:
                entry.update(reason="other_leave", label="Already on leave or off that day")
        elif d.weekday() in week:
            entry.update(days=1.0, reason="work_week", label=f"Normal working day ({WEEKDAY_NAMES[d.weekday()]})")
        else:
            entry.update(reason="day_off", label=f"Not a working day ({WEEKDAY_NAMES[d.weekday()]})")

        if half_day and entry["days"]:
            entry["days"] = 0.5
            entry["label"] += f" (half day, {half_day.upper()})"
        total += entry["days"]
        breakdown.append(entry)
        d += timedelta(days=1)

    return DayCount(round(total, 2), breakdown)


def application_days_in_year(app, year: int) -> float:
    """Days of a stored request that belong to `year`."""
    if app.start_date.year == year and app.end_date.year == year:
        return float(app.days_requested or 0)
    if app.day_breakdown:
        return float(days_by_year(app.day_breakdown).get(year, 0.0))
    return legacy_days_in_year(app.start_date, app.end_date, app.days_requested or 0, year)
