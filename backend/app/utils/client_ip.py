"""The caller's network address, only when it can be trusted.

Every request reaches the backend through the Next.js frontend, so the socket
peer is the frontend container, never the person. Two things went wrong with
that, found while verifying the 2026-09 audit fixes:

  * X-Forwarded-For was believed from anyone. The frontend passes a header the
    browser sets straight through, so an attacker could send a different fake
    address with every guess and never meet the per-address sign-in limit
    (password spraying across accounts; the per-account lockout still held).
  * Without the header, everyone looked like the frontend container, so the
    per-address sign-in limit (10 per 5 minutes) was really one limit for the
    whole company: the eleventh person signing in at shift change was refused.

The rule now: X-Forwarded-For is read only when a reverse proxy the operator
trusts appends to it, and then only the entry that proxy added — the one a
client cannot forge, because a client can only prepend. How many such proxies
sit in front is FORWARDED_FOR_TRUSTED_HOPS (0 by default: no proxy, header
ignored). The header is honoured only from a peer on a private network (our
own frontend container); a backend reached directly from the internet never
gets to choose its caller's address.

When no trustworthy address exists, `client_address` returns None, and the
callers fall back to limits and records that do not depend on it.
"""

from __future__ import annotations

from ipaddress import ip_address
from typing import Optional

from fastapi import Request

from app.config import settings


def _is_internal(host: Optional[str]) -> bool:
    if not host:
        return False
    try:
        addr = ip_address(host)
    except ValueError:
        # "testclient" and friends in tests; a unix socket. Not an address.
        return False
    return addr.is_private or addr.is_loopback or addr.is_link_local


def _valid(host: str) -> Optional[str]:
    try:
        return str(ip_address(host))
    except ValueError:
        return None


def client_address(request: Optional[Request]) -> Optional[str]:
    """The caller's address if it can be trusted, else None."""
    if request is None:
        return None
    peer = request.client.host if request.client else None

    hops = max(0, int(getattr(settings, "FORWARDED_FOR_TRUSTED_HOPS", 0) or 0))
    if hops and _is_internal(peer):
        entries = [e.strip() for e in request.headers.get("x-forwarded-for", "").split(",") if e.strip()]
        if len(entries) >= hops:
            return _valid(entries[-hops])
        return None

    # No trusted proxy: a private peer is our own frontend (not the person),
    # a public peer is the caller itself.
    if peer and not _is_internal(peer):
        return _valid(peer)
    return None


def rate_limit_key(prefix: str, request: Optional[Request]) -> tuple[str, bool]:
    """(key, per_address) for an address-based rate limit.

    With a trustworthy address the limit is per address. Without one, every
    caller shares `prefix:all`, and the caller should apply the generous
    company-wide backstop instead of the per-address limit, so one busy
    morning cannot lock the whole company out."""
    addr = client_address(request)
    if addr:
        return f"{prefix}:ip:{addr}", True
    return f"{prefix}:all", False
