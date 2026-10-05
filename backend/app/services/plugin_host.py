"""Runs plugins: loads them, queues their events, delivers them, keeps their
settings, and decides whether each may run (ops/PLUGINS_AND_LICENSING.md 2).

Loading. plugin_registry finds the packages under app/plugins; this module
reads each one's full MANIFEST and calls its register(ctx), which is the only
moment a plugin can attach anything. A plugin that fails to load is listed
with its error and never runs; it cannot stop the app or another plugin.

Events. Core calls publish(db, tenant_id, event, data) inside the change's
transaction. That only adds plugin_event_outbox rows, one per enabled and
licensed plugin that subscribed, so a change that rolls back reported
nothing. The scheduler's TICK job delivers them afterwards (deliver), with
the email outbox's backoff. publish never raises: a fault in plugin plumbing
must not fail an approval.

The licence is checked separately at each door a paid plugin goes through
(PLUGINS_AND_LICENSING 3.5): when an event is queued, when it is delivered,
when its secrets are decrypted, when its routes answer and when its jobs run.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings as app_settings
from app.models.plugin import PluginEventOutbox, PluginSetting
from app.plugin_api import EVENTS, SCOPES, SETTING_TYPES, TIMEOUT, PluginError, Runtime, envelope
from app.services import crypto, licence, plugin_registry
from app.services.email_service import retry_delay
from app.utils.timeutil import utcnow

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 6
BATCH = 50
HANDLER_TIMEOUT = 30  # seconds one delivery, test or job may take
TICK, HOURLY = "tick", "hourly"


# ── plugins ─────────────────────────────────────────────────────────────────


@dataclass
class Field:
    key: str
    label: str
    type: str = "text"
    required: bool = False
    default: Any = None
    help: Optional[str] = None
    options: List[Dict[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "key": self.key, "label": self.label, "type": self.type, "required": self.required,
            "default": self.default, "help": self.help, "options": self.options,
        }


@dataclass
class Plugin:
    id: str
    name: str
    version: str
    tier: str = "paid"
    summary: str = ""
    description: str = ""
    events: List[str] = field(default_factory=list)
    scopes: List[str] = field(default_factory=list)
    fields: List[Field] = field(default_factory=list)
    min_core: Optional[str] = None
    # A multiselect setting listing the events the company wants; events not
    # ticked there are not queued at all (MANIFEST "event_setting").
    event_setting: Optional[str] = None
    handlers: Dict[str, Callable] = field(default_factory=dict)
    tester: Optional[Callable] = None
    router: Any = None
    jobs: List[Tuple[str, Callable]] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def loaded(self) -> bool:
        return self.error is None

    def field(self, key: str) -> Optional[Field]:
        return next((f for f in self.fields if f.key == key), None)


class Registrar:
    """The `ctx` a plugin's register(ctx) receives."""

    def __init__(self, plugin: Plugin):
        self._plugin = plugin

    def on(self, event: str, fn: Optional[Callable] = None):
        if event not in EVENTS:
            raise ValueError(f"unknown event {event!r}")

        def add(f):
            self._plugin.handlers[event] = f
            return f

        return add(fn) if fn else add

    def test(self, fn: Callable) -> Callable:
        self._plugin.tester = fn
        return fn

    def router(self, router) -> None:
        self._plugin.router = router

    def job(self, cadence: str, fn: Callable) -> Callable:
        if cadence not in (TICK, HOURLY):
            raise ValueError(f"unknown cadence {cadence!r}")
        self._plugin.jobs.append((cadence, fn))
        return fn


def _version(text: Optional[str]) -> tuple:
    out = []
    for part in str(text or "0").split("-")[0].split("."):
        out.append(int(part) if part.isdigit() else 0)
    return tuple(out)


def _build(manifest: plugin_registry.PluginManifest) -> Plugin:
    module = importlib.import_module(manifest.module)
    raw = getattr(module, "MANIFEST", {}) or {}
    plugin = Plugin(
        id=str(raw.get("id") or manifest.name),
        name=str(raw.get("name") or manifest.name),
        version=manifest.version,
        tier="free" if raw.get("tier") == "free" else "paid",
        summary=str(raw.get("summary") or ""),
        description=str(raw.get("description") or ""),
        scopes=[s for s in raw.get("scopes", []) if s in SCOPES],
        min_core=raw.get("min_core"),
        event_setting=raw.get("event_setting"),
    )
    try:
        for spec in raw.get("settings", []):
            ftype = spec.get("type", "text")
            if ftype not in SETTING_TYPES:
                raise ValueError(f"setting {spec.get('key')!r} has unknown type {ftype!r}")
            plugin.fields.append(Field(
                key=spec["key"], label=spec.get("label", spec["key"]), type=ftype,
                required=bool(spec.get("required")), default=spec.get("default"),
                help=spec.get("help"), options=list(spec.get("options", [])),
            ))
        if plugin.min_core and _version(app_settings.APP_VERSION) < _version(plugin.min_core):
            raise ValueError(f"needs ursked {plugin.min_core} or later (this is {app_settings.APP_VERSION})")
        register = getattr(module, "register", None)
        if register is None:
            raise ValueError("has no register(ctx)")
        register(Registrar(plugin))
        plugin.events = sorted(plugin.handlers)
    except Exception as exc:  # noqa: BLE001 — a bad plugin is listed, never fatal
        logger.exception("Plugin %s failed to load", plugin.id)
        plugin.error = str(exc) or exc.__class__.__name__
        plugin.handlers.clear()
        plugin.router = None
        plugin.jobs.clear()
        plugin.tester = None
    return plugin


_plugins: Optional[Dict[str, Plugin]] = None


def plugins() -> Dict[str, Plugin]:
    """Every installed plugin by id, loaded once per process."""
    global _plugins
    if _plugins is None:
        found: Dict[str, Plugin] = {}
        for manifest in plugin_registry.discover():
            if not manifest.module:
                continue
            try:
                plugin = _build(manifest)
            except Exception as exc:  # noqa: BLE001 — import errors included
                logger.exception("Plugin %s failed to import", manifest.name)
                plugin = Plugin(id=manifest.name, name=manifest.name, version=manifest.version, error=str(exc))
            found.setdefault(plugin.id, plugin)
        _plugins = found
    return _plugins


def reset() -> None:
    """Forget loaded plugins (tests that install a temporary plugin)."""
    global _plugins
    _plugins = None
    plugin_registry.clear_cache()


def get(plugin_id: str) -> Plugin:
    plugin = plugins().get(plugin_id)
    if plugin is None:
        raise HTTPException(status_code=404, detail="No such plugin in this version of ursked.")
    return plugin


# ── licence ─────────────────────────────────────────────────────────────────


def runs_under(plugin: Plugin, view: licence.LicenceView) -> bool:
    if not plugin.loaded:
        return False
    return plugin.tier == "free" or view.get(plugin.id).runs


async def may_run(db: AsyncSession, plugin: Plugin) -> bool:
    return runs_under(plugin, await licence.current(db))


# ── settings ────────────────────────────────────────────────────────────────


async def setting_row(db: AsyncSession, tenant_id, plugin_id: str, *, create: bool = False) -> Optional[PluginSetting]:
    row = (await db.execute(
        select(PluginSetting).where(PluginSetting.tenant_id == tenant_id, PluginSetting.plugin_id == plugin_id)
    )).scalar_one_or_none()
    if row is None and create:
        row = PluginSetting(tenant_id=tenant_id, plugin_id=plugin_id, enabled=False, config={})
        db.add(row)
        await db.flush()
    return row


def _secrets(row: Optional[PluginSetting]) -> Dict[str, str]:
    if row is None or not row.secrets:
        return {}
    try:
        return json.loads(crypto.decrypt(row.secrets) or "{}")
    except Exception:  # noqa: BLE001 — a rotated key makes them unreadable
        logger.warning("Plugin %s: stored secrets could not be decrypted", row.plugin_id)
        return {}


def public_values(plugin: Plugin, row: Optional[PluginSetting]) -> Dict[str, Any]:
    """Settings as the API shows them: secrets only say whether they are set.
    Reads the encrypted blob's keys without decrypting values for display."""
    config = dict(row.config or {}) if row else {}
    secret_keys = set(_secrets(row)) if row and row.secrets else set()
    out: Dict[str, Any] = {}
    for f in plugin.fields:
        if f.type == "secret":
            out[f.key] = {"set": f.key in secret_keys}
        else:
            out[f.key] = config.get(f.key, f.default)
    return out


def _coerce(f: Field, value: Any) -> Any:
    if f.type == "bool":
        if not isinstance(value, bool):
            raise HTTPException(status_code=422, detail=f"{f.label} must be on or off.")
        return value
    if f.type == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise HTTPException(status_code=422, detail=f"{f.label} must be a number.")
        return value
    if f.type == "select":
        allowed = {o["value"] for o in f.options}
        if value not in allowed:
            raise HTTPException(status_code=422, detail=f"{f.label}: choose one of the listed options.")
        return value
    if f.type == "multiselect":
        allowed = {o["value"] for o in f.options}
        if not isinstance(value, list) or not set(value) <= allowed:
            raise HTTPException(status_code=422, detail=f"{f.label}: choose from the listed options.")
        return sorted(set(value))
    if not isinstance(value, str):
        raise HTTPException(status_code=422, detail=f"{f.label} must be text.")
    value = value.strip()
    if len(value) > 2000:
        raise HTTPException(status_code=422, detail=f"{f.label} is too long.")
    if f.type == "url" and value and not value.startswith(("https://", "http://")):
        raise HTTPException(status_code=422, detail=f"{f.label} must start with https://.")
    return value


async def save_settings(db: AsyncSession, plugin: Plugin, tenant_id, values: Dict[str, Any]) -> List[str]:
    """Apply submitted settings. A secret left out (or null) keeps its value; an
    empty string clears it. Returns the keys that changed (never values)."""
    unknown = set(values) - {f.key for f in plugin.fields}
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown setting: {', '.join(sorted(unknown))}.")
    row = await setting_row(db, tenant_id, plugin.id, create=True)
    config = dict(row.config or {})
    secret_values = _secrets(row)
    changed: List[str] = []
    for f in plugin.fields:
        if f.key not in values or values[f.key] is None:
            continue
        new = _coerce(f, values[f.key])
        if f.type == "secret":
            if new == "":
                if f.key in secret_values:
                    secret_values.pop(f.key)
                    changed.append(f.key)
            elif secret_values.get(f.key) != new:
                secret_values[f.key] = new
                changed.append(f.key)
        elif config.get(f.key, f.default) != new:
            config[f.key] = new
            changed.append(f.key)
    row.config = config
    row.secrets = crypto.encrypt(json.dumps(secret_values)) if secret_values else None
    row.updated_at = utcnow()
    if row.enabled:
        missing = missing_required(plugin, row)
        if missing:
            raise HTTPException(
                status_code=422,
                detail=f"{plugin.name} is on, so these cannot be empty: {', '.join(missing)}.",
            )
    await db.flush()
    return changed


def missing_required(plugin: Plugin, row: Optional[PluginSetting]) -> List[str]:
    values = public_values(plugin, row)
    missing = []
    for f in plugin.fields:
        if not f.required:
            continue
        v = values.get(f.key)
        if (f.type == "secret" and not v.get("set")) or (f.type != "secret" and v in (None, "", [])):
            missing.append(f.label)
    return missing


async def _runtime(db: AsyncSession, plugin: Plugin, row: PluginSetting, http: httpx.AsyncClient) -> Runtime:
    """The plugin's settings in clear, for running it. Only reached after the
    caller checked the licence; checked again here, because this is where the
    secrets are decrypted."""
    if not await may_run(db, plugin):
        raise PluginError(f"{plugin.name} is not licensed on this install.")
    values = {f.key: f.default for f in plugin.fields if f.type != "secret"}
    values.update(row.config or {})
    values.update(_secrets(row))
    site = await licence._site(db)
    return Runtime(plugin_id=plugin.id, tenant_id=row.tenant_id, settings=values, http=http, install_id=site.install_id)


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False, headers={"User-Agent": f"ursked/{app_settings.APP_VERSION}"})


# ── events ──────────────────────────────────────────────────────────────────


def _scoped(data: Any, scopes: List[str]) -> Any:
    """Drop what the plugin's scopes do not allow (email without employees.contact)."""
    if isinstance(data, dict):
        return {
            k: _scoped(v, scopes) for k, v in data.items()
            if not (k == "email" and "employees.contact" not in scopes)
        }
    if isinstance(data, list):
        return [_scoped(v, scopes) for v in data]
    return data


async def publish(db: AsyncSession, tenant_id, event: str, data: dict) -> int:
    """Queue `event` for every enabled, licensed plugin that subscribed, in the
    caller's transaction. Returns how many were queued. Never raises."""
    if event not in EVENTS:
        logger.error("publish: unknown plugin event %s", event)
        return 0
    try:
        listeners = [p for p in plugins().values() if event in p.handlers]
        if not listeners:
            return 0
        enabled = dict((await db.execute(
            select(PluginSetting.plugin_id, PluginSetting.config).where(
                PluginSetting.tenant_id == tenant_id,
                PluginSetting.enabled.is_(True),
                PluginSetting.plugin_id.in_([p.id for p in listeners]),
            )
        )).all())
        if not enabled:
            return 0
        view = await licence.current(db)
        base = envelope(event, data)
        queued = 0
        for plugin in listeners:
            if plugin.id not in enabled or not runs_under(plugin, view):
                continue
            wanted = (enabled[plugin.id] or {}).get(plugin.event_setting) if plugin.event_setting else None
            if isinstance(wanted, list) and event not in wanted:
                continue
            payload = dict(base, data=_scoped(json.loads(json.dumps(data, default=str)), plugin.scopes))
            db.add(PluginEventOutbox(tenant_id=tenant_id, plugin_id=plugin.id, event=event, payload=payload))
            queued += 1
        return queued
    except Exception:  # noqa: BLE001 — see module docstring
        logger.exception("publish: could not queue %s for plugins", event)
        return 0


async def deliver(db: AsyncSession, *, now: Optional[datetime] = None, limit: int = BATCH) -> dict:
    """Deliver queued events that are due, each committed on its own. The
    attempt is recorded before the plugin runs, so a crash mid-delivery
    retries after the backoff; delivery is at-least-once (the envelope id
    lets a receiver drop a repeat)."""
    now = now or utcnow()
    ids = (await db.execute(
        select(PluginEventOutbox.id)
        .where(PluginEventOutbox.status == "queued", PluginEventOutbox.next_attempt_at <= now)
        .order_by(PluginEventOutbox.next_attempt_at, PluginEventOutbox.id)
        .limit(limit)
    )).scalars().all()
    counts = {"due": len(ids), "sent": 0, "retrying": 0, "failed": 0, "skipped": 0}
    if not ids:
        return counts
    view = await licence.current(db)
    async with _client() as http:
        for oid in ids:
            row = await db.get(PluginEventOutbox, oid)
            if row is None or row.status != "queued":
                continue
            plugin = plugins().get(row.plugin_id)
            setting = await setting_row(db, row.tenant_id, row.plugin_id)
            reason = None
            if plugin is None or not plugin.loaded:
                reason = "This plugin is no longer installed."
            elif setting is None or not setting.enabled:
                reason = "The plugin was turned off before this was sent."
            elif not runs_under(plugin, view):
                reason = "The plugin's licence was not active when this was due."
            elif row.event not in plugin.handlers:
                reason = "The plugin no longer handles this event."
            if reason:
                row.status = "skipped"
                row.last_error = reason
                await db.commit()
                counts["skipped"] += 1
                continue

            row.attempts = (row.attempts or 0) + 1
            row.next_attempt_at = now + retry_delay(row.attempts)
            await db.commit()

            error = None
            try:
                rt = await _runtime(db, plugin, setting, http)
                await asyncio.wait_for(plugin.handlers[row.event](rt, row.event, row.payload), HANDLER_TIMEOUT)
            except asyncio.TimeoutError:
                error = f"No answer within {HANDLER_TIMEOUT} seconds."
            except PluginError as exc:
                error = str(exc)
            except httpx.HTTPError as exc:
                error = f"Connection failed: {exc.__class__.__name__}: {exc}"
            except Exception as exc:  # noqa: BLE001 — the plugin's own bug
                logger.exception("Plugin %s failed on %s", plugin.id, row.event)
                error = f"The plugin failed: {exc.__class__.__name__}: {exc}"
            if error is None:
                row.status = "sent"
                row.delivered_at = utcnow()
                row.last_error = None
                counts["sent"] += 1
            else:
                row.last_error = error[:2000]
                if row.attempts >= MAX_ATTEMPTS:
                    row.status = "failed"
                    counts["failed"] += 1
                else:
                    counts["retrying"] += 1
            await db.commit()
    return counts


async def run_test(db: AsyncSession, plugin: Plugin, tenant_id) -> Tuple[bool, str]:
    """The Test button: the plugin's cheapest real call. Records the result."""
    row = await setting_row(db, tenant_id, plugin.id, create=True)
    if plugin.tester is None:
        ok, message = False, "This plugin has no test."
    else:
        try:
            async with _client() as http:
                rt = await _runtime(db, plugin, row, http)
                result = await asyncio.wait_for(plugin.tester(rt), HANDLER_TIMEOUT)
            ok, message = True, (str(result) if result else "It worked.")
        except asyncio.TimeoutError:
            ok, message = False, f"No answer within {HANDLER_TIMEOUT} seconds."
        except (PluginError, httpx.HTTPError) as exc:
            ok, message = False, str(exc) or exc.__class__.__name__
        except Exception as exc:  # noqa: BLE001
            logger.exception("Plugin %s test failed", plugin.id)
            ok, message = False, f"The plugin failed: {exc.__class__.__name__}: {exc}"
    row.last_test_at = utcnow()
    row.last_test_ok = ok
    row.last_test_message = message[:2000]
    await db.flush()
    return ok, message


async def _run_jobs(db: AsyncSession, cadence: str) -> dict:
    result = {"ran": 0, "errors": 0}
    with_jobs = [p for p in plugins().values() if any(c == cadence for c, _ in p.jobs)]
    if not with_jobs:
        return result
    view = await licence.current(db)
    async with _client() as http:
        for plugin in with_jobs:
            if not runs_under(plugin, view):
                continue
            rows = (await db.execute(
                select(PluginSetting).where(PluginSetting.plugin_id == plugin.id, PluginSetting.enabled.is_(True))
            )).scalars().all()
            for row in rows:
                for c, fn in plugin.jobs:
                    if c != cadence:
                        continue
                    try:
                        rt = await _runtime(db, plugin, row, http)
                        await asyncio.wait_for(fn(rt), HANDLER_TIMEOUT)
                        result["ran"] += 1
                    except Exception:  # noqa: BLE001 — one plugin cannot stop the rest
                        logger.exception("Plugin %s %s job failed", plugin.id, cadence)
                        result["errors"] += 1
    return result


async def run_due(db: AsyncSession) -> dict:
    """Scheduler job (TICK): deliver due events, then run plugins' minute jobs."""
    counts = await deliver(db)
    counts["jobs"] = await _run_jobs(db, TICK)
    return counts


async def run_hourly(db: AsyncSession) -> dict:
    """Scheduler job (HOURLY): licence upkeep, then plugins' hourly jobs."""
    result = {"licence": await licence.run_hourly(db)}
    result["jobs"] = await _run_jobs(db, HOURLY)
    return result


# ── plugin routes ───────────────────────────────────────────────────────────


def route_guard(plugin_id: str):
    """Dependency for a plugin's own routes (/api/v1/ext/<id>/...): they answer
    404 unless the plugin is licensed and turned on for some company."""
    from fastapi import Depends

    from app.database import get_db

    async def guard(db: AsyncSession = Depends(get_db)) -> None:
        plugin = plugins().get(plugin_id)
        if plugin is None or not await may_run(db, plugin):
            raise HTTPException(status_code=404, detail="Not Found")
        on = (await db.execute(
            select(PluginSetting.id).where(PluginSetting.plugin_id == plugin_id, PluginSetting.enabled.is_(True)).limit(1)
        )).scalar_one_or_none()
        if on is None:
            raise HTTPException(status_code=404, detail="Not Found")

    return guard
