"""This install's licence, read from site_settings and judged now.

The key format, the trusted public keys and the rules for judging a key live in
licence_key.py (no database, so the signing tool can use the same code). This
module adds the install: its ID, the applied key, the active-employee count,
the clock high-water mark, and the hourly job that maintains them. See
ops/PLUGINS_AND_LICENSING.md 3.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.licence_key import (  # noqa: F401  (re-exported for callers)
    ACTIVE, EXPIRED, GRACE, NONE, OVER_LIMIT, PAUSED_OVER_LIMIT, RUNNING_STATES, TRIAL,
    Entitlement, Licence, LicenceError, LicenceView, effective_now, evaluate, parse, sign,
)
from app.utils.timeutil import utcnow


async def _site(db: AsyncSession):
    from app.models.site_settings import SiteSettings

    row = (await db.execute(select(SiteSettings).order_by(SiteSettings.id).limit(1))).scalar_one_or_none()
    if row is None:
        row = SiteSettings()
        db.add(row)
        await db.flush()
    if not row.install_id:
        row.install_id = str(uuid.uuid4())
        await db.flush()
    return row


async def active_employees(db: AsyncSession) -> int:
    """People who count against an employee limit: every active account."""
    from app.models.user import User

    return int((await db.execute(select(func.count(User.id)).where(User.is_active.is_(True)))).scalar() or 0)


async def current(db: AsyncSession, *, now: Optional[datetime] = None) -> LicenceView:
    """This install's licence and every entitlement, judged now."""
    site = await _site(db)
    view = LicenceView(install_id=site.install_id)
    if not site.licence_key:
        return view
    try:
        lic = parse(site.licence_key)
    except LicenceError as exc:
        view.error = str(exc)
        return view
    if lic.iid != site.install_id:
        view.error = "The applied licence key belongs to a different install. Apply this install's own key."
        return view
    view.licence = lic
    view.active_employees = await active_employees(db)
    view.now = effective_now(now or utcnow(), site.licence_state, lic)
    view.entitlements = evaluate(
        lic, now=view.now, active_employees=view.active_employees, state=site.licence_state
    )
    return view


async def entitlement(db: AsyncSession, plugin_id: str) -> Entitlement:
    return (await current(db)).get(plugin_id)


async def apply(db: AsyncSession, key: str, *, now: Optional[datetime] = None) -> Licence:
    """Validate `key` for this install and make it the applied key. Raises
    LicenceError. The caller commits (and audits)."""
    site = await _site(db)
    lic = parse(key)
    if lic.iid != site.install_id:
        raise LicenceError(
            f"This key was issued for a different install ({lic.iid}). "
            f"This install's ID is {site.install_id}."
        )
    if site.licence_key:
        try:
            old = parse(site.licence_key)
        except LicenceError:
            old = None
        if old is not None and old.iid == site.install_id and old.issued > lic.issued:
            raise LicenceError(
                "This key is older than the one already applied. Use the newest key you were sent."
            )
    site.licence_key = "".join(key.split())
    state = dict(site.licence_state or {})
    # A signed issue time is trusted evidence of the real time: it resets the
    # high-water mark, which repairs a clock that was once set into the future.
    state["high_water"] = max(now or utcnow(), lic.issued).isoformat()
    site.licence_state = state
    await db.flush()
    return lic


async def remove(db: AsyncSession) -> None:
    site = await _site(db)
    site.licence_key = None
    await db.flush()


async def run_hourly(db: AsyncSession) -> dict:
    """Scheduler job: advance the clock high-water mark and remember when each
    employee-limited plugin went over its limit. Commits."""
    site = await _site(db)
    state = dict(site.licence_state or {})
    now = utcnow()
    mark = state.get("high_water")
    if not mark or datetime.fromisoformat(mark) < now:
        state["high_water"] = now.isoformat()
    result = {"over_limit": 0}
    over = dict(state.get("over_since") or {})
    lic = None
    if site.licence_key:
        try:
            lic = parse(site.licence_key)
        except LicenceError:
            lic = None
    if lic is not None:
        used = await active_employees(db)
        today = effective_now(now, state, lic).date().isoformat()
        limited = {}
        for line in lic.lines:
            if line.get("seats") not in (None, ""):
                limited[line["plugin"]] = max(limited.get(line["plugin"], 0), int(line["seats"]))
        for plugin, seats in limited.items():
            if used > seats:
                over.setdefault(plugin, today)
                result["over_limit"] += 1
            else:
                over.pop(plugin, None)
        for plugin in list(over):
            if plugin not in limited:
                over.pop(plugin)
    else:
        over = {}
    state["over_since"] = over
    site.licence_state = state
    await db.commit()
    return result


def describe(lic: Licence) -> dict:
    return {
        "lid": lic.lid,
        "customer": lic.customer,
        "issued": lic.issued.isoformat(),
        "grace_days": lic.grace_days,
    }
