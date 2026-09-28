"""The two clocks the app runs on: the instant (always UTC) and the company's day.

Instants. Every stored timestamp column is `timestamptz`. The code used to
write naive `datetime.utcnow()` into them, which PostgreSQL interprets in the
*session's* timezone — so a container started with `TZ=Asia/Manila` stored
every timestamp eight hours off. An aware UTC datetime means the same instant
whatever the container clock says. Use `utcnow()` for "now", never
`datetime.utcnow()` or a bare `datetime.now()`.

Comparisons. PostgreSQL hands `timestamptz` values back aware; SQLite (the
test database) hands them back naive (in UTC, because we only ever write UTC).
Python refuses to compare the two, so anything read from the database that is
compared with `utcnow()` goes through `as_utc()` first.

The company's day. "Today" for leave, payroll, analytics and report periods is
the date where the company is (AppSettings.timezone, the Settings screen's
Organization Timezone), not the server's date: in Manila the first eight hours
of every day would otherwise still be yesterday. `company_today()` is the one
way to ask for it.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def utcnow() -> datetime:
    """The current instant as an aware UTC datetime."""
    return datetime.now(timezone.utc)


def as_utc(value: Optional[datetime]) -> Optional[datetime]:
    """An aware UTC datetime for `value` (None passes through). A naive value
    is taken to be UTC already, which is what everything we write is."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def zone(tz_name: Optional[str]) -> ZoneInfo:
    """ZoneInfo for a stored timezone name, UTC when unset or unknown (a typo
    in settings must not stop a job or a page)."""
    try:
        return ZoneInfo(tz_name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def local_today(tz_name: Optional[str], now: Optional[datetime] = None) -> date:
    """The date in `tz_name` at instant `now` (default: this instant)."""
    return (as_utc(now) or utcnow()).astimezone(zone(tz_name)).date()


async def company_today(db, tenant_id) -> date:
    """Today where the company is, from the canonical timezone setting."""
    # Imported here: models import this module for utcnow(), and the settings
    # service imports the models.
    from app.services.settings_service import SettingsService

    return local_today(await SettingsService.get_tenant_timezone(db, tenant_id))
