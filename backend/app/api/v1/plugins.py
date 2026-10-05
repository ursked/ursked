"""Admin › Plugins: installed plugins, their settings, and the licence
(ops/PLUGINS_AND_LICENSING.md 2.6, 3).

Administration, so admin dashboard only: require_role(["tenant_admin"]) passes
only in a session opened at the administrator door (session_portal).
Turning a plugin on or off, changing its settings and applying or removing a
licence key are audited, and every other administrator is told (the rule for
admin changes since CE_AUDIT_FIXES 5.20).
"""

from __future__ import annotations

import html
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings as app_settings
from app.database import get_db
from app.middleware.auth import require_role
from app.models.plugin import PluginEventOutbox
from app.models.user import User
from app.plugin_api import EVENTS, SCOPES
from app.services import audit_service, licence, plugin_host
from app.utils.timeutil import utcnow

router = APIRouter(tags=["Plugins"])

admin_only = require_role(["tenant_admin"])

# Where "Buy" and "Start trial" send an administrator. Empty until the store
# exists: the page then says to ask the ursked provider, quoting the install ID.
STORE_URL = getattr(app_settings, "URSKED_STORE_URL", "") or ""


# ── telling the other administrators ───────────────────────────────────────


async def _announce(db: AsyncSession, actor: User, title: str, body: str, kind: str) -> None:
    from app.services import employee_access
    from app.services.email_service import EmailService
    from app.services.email_templates import _base_wrapper
    from app.services.notification_service import NotificationService

    others = await employee_access.active_admin_ids(db, actor.tenant_id) - {actor.id}
    if not others:
        return
    rows = (await db.execute(select(User).where(User.id.in_(others)))).scalars().all()
    for other in rows:
        await NotificationService.notify(db, actor.tenant_id, other.id, type=kind, title=title, body=body)
        if other.email:
            page = _base_wrapper(
                f"<h2 style=\"margin:0 0 12px\">{html.escape(title)}</h2>"
                f"<p style=\"margin:0\">{html.escape(body)}</p>"
            )
            EmailService.fire_and_forget(
                lambda db, to=other.email, t=title, pg=page: EmailService.send_email(db, to, t, pg, log_type=kind)
            )


# ── plugins ────────────────────────────────────────────────────────────────


async def _activity_counts(db: AsyncSession, tenant_id, plugin_id: str) -> Dict[str, int]:
    rows = (await db.execute(
        select(PluginEventOutbox.status, func.count(PluginEventOutbox.id))
        .where(PluginEventOutbox.tenant_id == tenant_id, PluginEventOutbox.plugin_id == plugin_id)
        .group_by(PluginEventOutbox.status)
    )).all()
    return {status: int(n) for status, n in rows}


async def _describe(db: AsyncSession, plugin: plugin_host.Plugin, tenant_id, view: licence.LicenceView) -> dict:
    row = await plugin_host.setting_row(db, tenant_id, plugin.id)
    ent = view.get(plugin.id)
    return {
        "id": plugin.id,
        "name": plugin.name,
        "version": plugin.version,
        "tier": plugin.tier,
        "summary": plugin.summary,
        "description": plugin.description,
        "loaded": plugin.loaded,
        "error": plugin.error,
        "events": [{"key": e, "label": EVENTS[e]} for e in plugin.events],
        "scopes": [{"key": s, "label": SCOPES[s]} for s in plugin.scopes],
        "fields": [f.as_dict() for f in plugin.fields],
        "values": plugin_host.public_values(plugin, row),
        "missing": plugin_host.missing_required(plugin, row),
        "enabled": bool(row and row.enabled),
        "runs": plugin_host.runs_under(plugin, view),
        "has_test": plugin.tester is not None,
        "entitlement": ent.as_dict() if plugin.tier == "paid" else None,
        "last_test": (
            {"at": row.last_test_at.isoformat(), "ok": row.last_test_ok, "message": row.last_test_message}
            if row and row.last_test_at else None
        ),
        "activity": await _activity_counts(db, tenant_id, plugin.id),
    }


@router.get("/plugins")
async def list_plugins(db: AsyncSession = Depends(get_db), current_user: User = Depends(admin_only)):
    view = await licence.current(db)
    items = [await _describe(db, p, current_user.tenant_id, view) for p in plugin_host.plugins().values()]
    items.sort(key=lambda d: d["name"].lower())
    return {"plugins": items, "install_id": view.install_id, "store_url": STORE_URL}


class SettingsIn(BaseModel):
    values: Dict[str, Any] = Field(default_factory=dict)


@router.put("/plugins/{plugin_id}/settings")
async def save_plugin_settings(
    plugin_id: str, body: SettingsIn, request: Request,
    db: AsyncSession = Depends(get_db), current_user: User = Depends(admin_only),
):
    plugin = plugin_host.get(plugin_id)
    changed = await plugin_host.save_settings(db, plugin, current_user.tenant_id, body.values)
    if changed:
        labels = [plugin.field(k).label for k in changed]
        audit_service.record(
            db, actor=current_user, action="plugin_settings_change", resource_type="plugin",
            resource_id=plugin.id, details={"changed": changed}, request=request,
        )
        await _announce(
            db, current_user, f"{plugin.name} settings changed",
            f"{audit_service.user_label(current_user)} changed {plugin.name}: {', '.join(labels)}.",
            "plugin_change",
        )
    await db.commit()
    return await _describe(db, plugin, current_user.tenant_id, await licence.current(db))


async def _set_enabled(db, plugin_id: str, on: bool, current_user: User, request: Request) -> dict:
    plugin = plugin_host.get(plugin_id)
    row = await plugin_host.setting_row(db, current_user.tenant_id, plugin.id, create=True)
    view = await licence.current(db)
    if on:
        if not plugin.loaded:
            raise HTTPException(status_code=409, detail=f"{plugin.name} could not be loaded: {plugin.error}")
        if not plugin_host.runs_under(plugin, view):
            raise HTTPException(
                status_code=409,
                detail=f"{plugin.name} needs a licence. Apply a key that includes it under Licence.",
            )
        missing = plugin_host.missing_required(plugin, row)
        if missing:
            raise HTTPException(status_code=409, detail=f"Fill in {', '.join(missing)} first.")
    if row.enabled != on:
        row.enabled = on
        audit_service.record(
            db, actor=current_user, action="plugin_enable" if on else "plugin_disable",
            resource_type="plugin", resource_id=plugin.id, request=request,
        )
        verb = "turned on" if on else "turned off"
        await _announce(
            db, current_user, f"{plugin.name} was {verb}",
            f"{audit_service.user_label(current_user)} {verb} the {plugin.name} plugin.",
            "plugin_change",
        )
    await db.commit()
    return await _describe(db, plugin, current_user.tenant_id, view)


@router.post("/plugins/{plugin_id}/enable")
async def enable_plugin(plugin_id: str, request: Request, db: AsyncSession = Depends(get_db),
                        current_user: User = Depends(admin_only)):
    return await _set_enabled(db, plugin_id, True, current_user, request)


@router.post("/plugins/{plugin_id}/disable")
async def disable_plugin(plugin_id: str, request: Request, db: AsyncSession = Depends(get_db),
                         current_user: User = Depends(admin_only)):
    return await _set_enabled(db, plugin_id, False, current_user, request)


@router.post("/plugins/{plugin_id}/test")
async def test_plugin(plugin_id: str, db: AsyncSession = Depends(get_db), current_user: User = Depends(admin_only)):
    plugin = plugin_host.get(plugin_id)
    if not await plugin_host.may_run(db, plugin):
        raise HTTPException(status_code=409, detail=f"{plugin.name} needs a licence before it can be tested.")
    ok, message = await plugin_host.run_test(db, plugin, current_user.tenant_id)
    await db.commit()
    return {"ok": ok, "message": message}


@router.get("/plugins/{plugin_id}/activity")
async def plugin_activity(
    plugin_id: str, limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db), current_user: User = Depends(admin_only),
):
    plugin = plugin_host.get(plugin_id)
    rows = (await db.execute(
        select(PluginEventOutbox)
        .where(PluginEventOutbox.tenant_id == current_user.tenant_id, PluginEventOutbox.plugin_id == plugin.id)
        .order_by(PluginEventOutbox.created_at.desc(), PluginEventOutbox.id.desc())
        .limit(limit)
    )).scalars().all()
    return [
        {
            "id": r.id, "event": r.event, "label": EVENTS.get(r.event, r.event), "status": r.status,
            "attempts": r.attempts, "last_error": r.last_error,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "delivered_at": r.delivered_at.isoformat() if r.delivered_at else None,
            "next_attempt_at": r.next_attempt_at.isoformat() if r.status == "queued" and r.next_attempt_at else None,
        }
        for r in rows
    ]


@router.post("/plugins/{plugin_id}/activity/{row_id}/retry")
async def retry_delivery(plugin_id: str, row_id: int, db: AsyncSession = Depends(get_db),
                         current_user: User = Depends(admin_only)):
    row = await db.get(PluginEventOutbox, row_id)
    if row is None or row.plugin_id != plugin_id or row.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Not Found")
    if row.status not in ("failed", "skipped"):
        raise HTTPException(status_code=409, detail="Only a failed or skipped delivery can be retried.")
    row.status = "queued"
    row.attempts = 0
    row.next_attempt_at = utcnow()
    await db.commit()
    return {"ok": True}


# ── licence ────────────────────────────────────────────────────────────────


def _licence_body(view: licence.LicenceView) -> dict:
    plugins = plugin_host.plugins()
    lines: List[dict] = []
    for plugin_id, ent in sorted(view.entitlements.items()):
        d = ent.as_dict()
        p = plugins.get(plugin_id)
        d["name"] = p.name if p else plugin_id
        d["installed"] = p is not None
        lines.append(d)
    return {
        "install_id": view.install_id,
        "store_url": STORE_URL,
        "applied": view.licence is not None or view.error is not None,
        "error": view.error,
        "licence": (
            {
                "lid": view.licence.lid,
                "customer": view.licence.customer,
                "issued": view.licence.issued.isoformat(),
                "grace_days": view.licence.grace_days,
            }
            if view.licence else None
        ),
        "active_employees": view.active_employees,
        "entitlements": lines,
    }


@router.get("/licence")
async def get_licence(db: AsyncSession = Depends(get_db), current_user: User = Depends(admin_only)):
    view = await licence.current(db)
    await db.commit()  # an install ID created on first read is kept
    return _licence_body(view)


class KeyIn(BaseModel):
    key: str = Field(..., min_length=10, max_length=20000)


@router.put("/licence")
async def apply_licence(body: KeyIn, request: Request, db: AsyncSession = Depends(get_db),
                        current_user: User = Depends(admin_only)):
    try:
        lic = await licence.apply(db, body.key)
    except licence.LicenceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    plugins = sorted({line["plugin"] for line in lic.lines})
    audit_service.record(
        db, actor=current_user, action="licence_apply", resource_type="licence", resource_id=lic.lid,
        details={"plugins": plugins, "issued": lic.issued.isoformat()}, request=request,
    )
    await _announce(
        db, current_user, "A licence key was applied",
        f"{audit_service.user_label(current_user)} applied licence {lic.lid} ({', '.join(plugins)}).",
        "licence_change",
    )
    await db.commit()
    return _licence_body(await licence.current(db))


@router.delete("/licence")
async def remove_licence(request: Request, db: AsyncSession = Depends(get_db),
                         current_user: User = Depends(admin_only)):
    view = await licence.current(db)
    if view.licence is None and view.error is None:
        return _licence_body(view)
    await licence.remove(db)
    audit_service.record(
        db, actor=current_user, action="licence_remove", resource_type="licence",
        resource_id=view.licence.lid if view.licence else None, request=request,
    )
    await _announce(
        db, current_user, "The licence key was removed",
        f"{audit_service.user_label(current_user)} removed the licence key. Paid plugins stop running.",
        "licence_change",
    )
    await db.commit()
    return _licence_body(await licence.current(db))
