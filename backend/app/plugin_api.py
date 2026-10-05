"""What a plugin may import from ursked (ops/PLUGINS_AND_LICENSING.md 2.1).

A plugin imports from this module and nothing else in `app`: never models,
never services. Everything here is kept stable across releases, so core can
change underneath without breaking a plugin, and a plugin only ever sees the
data its manifest's `scopes` allow.

    from app.plugin_api import PluginError, Runtime, check_outbound_url

    MANIFEST = {...}

    def register(ctx):
        ctx.on("leave.decided", handle)
        ctx.test(check)

    async def handle(rt: Runtime, event: str, envelope: dict) -> None:
        url = check_outbound_url(rt.settings["url"], allow_private=rt.settings.get("allow_private"))
        response = await rt.http.post(url, json=envelope)
        if response.status_code >= 300:
            raise PluginError(f"{url} answered HTTP {response.status_code}")
"""

from __future__ import annotations

import ipaddress
import socket
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import urlsplit

import httpx

# Every event a plugin can subscribe to, with what it means. Payloads are the
# envelope {"id", "event", "v", "occurred_at", "data"}; "id" is unique per
# event and lets a receiver ignore a repeat (delivery is at-least-once).
EVENTS: Dict[str, str] = {
    "schedule.published": "A schedule was published",
    "shift.changed": "Shifts were added, moved or removed",
    "leave.requested": "Someone filed a leave request",
    "leave.decided": "A leave request was approved, rejected or cancelled",
    "attendance.clocked": "Someone clocked in or out",
    "attendance.missed": "A no-show was marked automatically",
    "employee.joined": "An employee was added",
    "employee.separated": "An employee was separated",
    "payroll.finalized": "A payroll period was finalized",
}

# What a plugin may receive, by scope. Without employees.contact, email
# addresses are removed from every payload before it is queued.
SCOPES: Dict[str, str] = {
    "employees.basic": "Employee names",
    "employees.contact": "Employee email addresses",
}

SETTING_TYPES = ("text", "url", "secret", "bool", "number", "select", "multiselect")

TIMEOUT = httpx.Timeout(15.0, connect=10.0)


class PluginError(Exception):
    """A failure the administrator should read as-is under the plugin's
    Activity (e.g. "https://hooks.example answered HTTP 404")."""


@dataclass
class Runtime:
    """What a plugin's handler, test or job is given."""

    plugin_id: str
    tenant_id: Any
    settings: Dict[str, Any]
    http: httpx.AsyncClient
    install_id: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)


def envelope(event: str, data: dict, *, now: Optional[datetime] = None) -> dict:
    """The JSON every event is delivered in (also for a plugin's own test event)."""
    return {
        "id": str(uuid.uuid4()),
        "event": event,
        "v": 1,
        "occurred_at": (now or datetime.now(timezone.utc)).isoformat(),
        "data": data,
    }


def check_outbound_url(url: Optional[str], *, allow_private: bool = False) -> str:
    """Refuse addresses a plugin must not call: this server itself, the cloud
    metadata service, and (unless the administrator allowed it) the local
    network. Returns the URL. Raises PluginError.

    Resolved here and connected to by name afterwards, so a hostile DNS server
    could still answer differently the second time. The URL is set by an
    administrator, which is what keeps that acceptable.
    """
    if not url:
        raise PluginError("No address is set.")
    parts = urlsplit(url)
    if parts.scheme not in ("https", "http") or not parts.hostname:
        raise PluginError("The address must start with https:// (or http://).")
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80))
    except socket.gaierror:
        raise PluginError(f"{parts.hostname} could not be found (DNS).") from None
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved:
            raise PluginError(f"{parts.hostname} points at {ip}, which plugins may not call.")
        if (ip.is_private or ip in ipaddress.ip_network("100.64.0.0/10")) and not allow_private:
            raise PluginError(
                f"{parts.hostname} is on a local network ({ip}). Turn on "
                "\"Allow local network addresses\" in this plugin's settings to use it."
            )
    return url
