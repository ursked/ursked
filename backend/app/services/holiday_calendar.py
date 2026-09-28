"""The one answer to "which days are holidays?".

Before this, five places answered it differently. Attendance expanded
recurring holidays by month and day; the grid, payroll holiday pay, auto
holiday-off, schedule lint and the payout business-day adjustment all matched
the literal stored date. So a holiday marked "repeats every year" silently
stopped paying the holiday premium, marking the grid and skipping the payout
day the following January.

Every caller that needs holidays uses `holidays_between`. Rules:

  * Only DateRemark rows with is_holiday=True count. Other remarks are notes.
  * A recurring holiday applies on the same month and day of every year. A
    29 February recurring holiday applies only in leap years.
  * A holiday stored for an exact date wins over a recurring one landing on the
    same day, so a one-off correction (e.g. a moved holiday) takes precedence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Dict, Optional
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.schedule import DateRemark


@dataclass(frozen=True)
class HolidayDay:
    date: date
    title: str
    is_special: bool
    is_recurring: bool
    remark_id: int


def _on_year(d: date, year: int) -> Optional[date]:
    try:
        return d.replace(year=year)
    except ValueError:  # 29 Feb in a non-leap year
        return None


async def holidays_between(
    db: AsyncSession, tenant_id: UUID, start: date, end: date
) -> Dict[date, HolidayDay]:
    """All holidays from `start` to `end` inclusive, keyed by date."""
    if end < start:
        return {}

    rows = (
        await db.execute(
            select(DateRemark).where(
                DateRemark.tenant_id == tenant_id,
                DateRemark.is_holiday == True,  # noqa: E712
                or_(
                    and_(DateRemark.date >= start, DateRemark.date <= end),
                    DateRemark.is_recurring == True,  # noqa: E712
                ),
            )
        )
    ).scalars().all()

    out: Dict[date, HolidayDay] = {}

    # Recurring first, so exact-date rows overwrite them below.
    for r in rows:
        if not r.is_recurring:
            continue
        for year in range(start.year, end.year + 1):
            d = _on_year(r.date, year)
            if d is not None and start <= d <= end:
                out[d] = HolidayDay(d, r.title, bool(r.is_special), True, r.id)

    for r in rows:
        if start <= r.date <= end:
            out[r.date] = HolidayDay(
                r.date, r.title, bool(r.is_special), bool(r.is_recurring), r.id
            )

    return out


async def holiday_on(db: AsyncSession, tenant_id: UUID, d: date) -> Optional[HolidayDay]:
    return (await holidays_between(db, tenant_id, d, d)).get(d)
