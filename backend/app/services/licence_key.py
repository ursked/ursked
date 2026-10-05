"""The licence: which paid plugins this install may run (ops/PLUGINS_AND_LICENSING.md 3).

A key is

    URSKED1.<base64url(payload JSON)>.<base64url(Ed25519 signature)>

signed over the text before the last dot. The store holds the private key;
this file holds only the PUBLIC keys, by key id, so nothing here can make a
key, and changing any character of a key's payload (seats, dates, plugins,
install ID) breaks its signature. That is checked here, offline, every time a
key is read: no call home is ever needed to run a licensed plugin.

The payload:

    {"v": 1, "kid": "2026-a", "lid": "LIC-...", "iid": "<install id>",
     "customer": {"name": ..., "email": ...}, "issued": "<ISO UTC>",
     "grace_days": 14,
     "entitlements": [{"plugin": "slack", "model": "flat",
                       "expires": "2027-10-05", "seats": null,
                       "trial": false, "via": "connectors"}]}

Bundles are expanded by the store when it signs, so the key always names
plugins, never bundles ("via" only says which bundle a line came from).

What a licence can never do: lock the core app or company data. It only
decides whether a plugin runs. Expiry gives `grace_days` of grace with a
banner; going over an employee limit gives OVER_LIMIT_GRACE; adding an
employee is never refused.

Time. Expiry is judged against an effective "now" that never goes backwards:
the latest of the server clock, the high-water mark the hourly job keeps in
site_settings.licence_state, and the applied key's own signed issue time.
Winding the clock back therefore un-expires nothing. A clock wrongly set into
the future is repaired by applying a newer key: applying one resets the mark
to that key's (signed) issue time.
"""

# Pure: no database and no app imports, so the signing tool and the store can
# load this file on its own (ops/licence/ursked-licence).

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from typing import Dict, Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

PREFIX = "URSKED1"
DEFAULT_GRACE_DAYS = 14
OVER_LIMIT_GRACE = timedelta(days=30)
WARN_AT = 0.9  # share of an employee limit at which the Licence tab warns

# kid -> raw Ed25519 public key, base64. A new kid is added here when the
# signing key is rotated; a retired kid is removed in the release that retires
# it, which ends every key it signed.
TRUSTED_KEYS: Dict[str, str] = {
    "2026-a": "rkMgUZgGIL8mHN1oaWBLKagJJ0POJaOVjL18qBVyBU4=",
}

# Entitlement states. RUNNING_STATES are the ones in which a plugin runs.
NONE = "none"            # not in the key, or no key
ACTIVE = "active"
TRIAL = "trial"
GRACE = "grace"          # expired, inside grace_days: runs, with a renewal banner
OVER_LIMIT = "over_limit"  # more active employees than seats: runs, with a banner
PAUSED_OVER_LIMIT = "paused_over_limit"  # over the limit for OVER_LIMIT_GRACE
EXPIRED = "expired"      # past grace: paused
RUNNING_STATES = frozenset({ACTIVE, TRIAL, GRACE, OVER_LIMIT})


class LicenceError(ValueError):
    """A key that cannot be used, with a message an administrator can act on."""


@dataclass(frozen=True)
class Entitlement:
    plugin: str
    state: str = NONE
    model: Optional[str] = None
    expires: Optional[date] = None
    grace_until: Optional[date] = None
    seats: Optional[int] = None
    used: Optional[int] = None
    trial: bool = False
    via: Optional[str] = None
    over_since: Optional[date] = None

    @property
    def runs(self) -> bool:
        return self.state in RUNNING_STATES

    @property
    def near_limit(self) -> bool:
        return bool(self.seats and self.used is not None and self.used >= self.seats * WARN_AT)

    def as_dict(self) -> dict:
        return {
            "plugin": self.plugin,
            "state": self.state,
            "runs": self.runs,
            "model": self.model,
            "expires": self.expires.isoformat() if self.expires else None,
            "grace_until": self.grace_until.isoformat() if self.grace_until else None,
            "seats": self.seats,
            "used": self.used,
            "near_limit": self.near_limit,
            "trial": self.trial,
            "via": self.via,
            "over_since": self.over_since.isoformat() if self.over_since else None,
        }


@dataclass(frozen=True)
class Licence:
    lid: str
    iid: str
    kid: str
    issued: datetime
    customer: dict
    grace_days: int
    lines: tuple  # of dicts, as signed


@dataclass
class LicenceView:
    install_id: str
    licence: Optional[Licence] = None
    error: Optional[str] = None
    active_employees: int = 0
    now: Optional[datetime] = None
    entitlements: Dict[str, Entitlement] = field(default_factory=dict)

    def get(self, plugin_id: str) -> Entitlement:
        return self.entitlements.get(plugin_id) or Entitlement(plugin=plugin_id)


# ── the key ─────────────────────────────────────────────────────────────────


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _trusted(kid: str) -> Optional[Ed25519PublicKey]:
    raw = TRUSTED_KEYS.get(kid)
    if not raw:
        return None
    return Ed25519PublicKey.from_public_bytes(base64.b64decode(raw))


def _parse_date(value, what: str) -> date:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        raise LicenceError(f"This key has an unreadable {what}.") from None


@lru_cache(maxsize=32)
def parse(key: str) -> Licence:
    """Verify a key and return what it says. Raises LicenceError. Cached: a
    key's meaning never changes, only the time it is judged at."""
    text = "".join((key or "").split())  # tolerate line breaks from email
    parts = text.split(".")
    if len(parts) != 3 or parts[0] != PREFIX:
        raise LicenceError("This is not an ursked licence key. A key starts with URSKED1.")
    try:
        payload_raw = _b64d(parts[1])
        signature = _b64d(parts[2])
        payload = json.loads(payload_raw)
    except (ValueError, json.JSONDecodeError):
        raise LicenceError("This licence key is damaged. Copy it again, in full.") from None
    if not isinstance(payload, dict) or payload.get("v") != 1:
        raise LicenceError("This licence key is for a newer version of ursked. Update ursked first.")
    public_key = _trusted(str(payload.get("kid")))
    if public_key is None:
        raise LicenceError("This licence key was not signed by a key this version of ursked trusts.")
    try:
        public_key.verify(signature, f"{parts[0]}.{parts[1]}".encode())
    except InvalidSignature:
        raise LicenceError("This licence key has been changed or is not genuine.") from None

    try:
        issued = datetime.fromisoformat(str(payload["issued"]).replace("Z", "+00:00"))
        if issued.tzinfo is None:
            issued = issued.replace(tzinfo=timezone.utc)
        lines = payload["entitlements"]
        assert isinstance(lines, list)
        for line in lines:
            assert isinstance(line, dict) and isinstance(line.get("plugin"), str)
            _parse_date(line.get("expires"), "expiry date")
        return Licence(
            lid=str(payload["lid"]),
            iid=str(payload["iid"]),
            kid=str(payload["kid"]),
            issued=issued,
            customer=dict(payload.get("customer") or {}),
            grace_days=int(payload.get("grace_days", DEFAULT_GRACE_DAYS)),
            lines=tuple(lines),
        )
    except (KeyError, TypeError, ValueError, AssertionError):
        raise LicenceError("This licence key is incomplete.") from None


def sign(payload: dict, private_key) -> str:
    """Make a key. Used by the signing tool and the tests; ursked itself never
    has a private key to call it with."""
    body = _b64e(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    signature = private_key.sign(f"{PREFIX}.{body}".encode())
    return f"{PREFIX}.{body}.{_b64e(signature)}"


# ── judging it ──────────────────────────────────────────────────────────────


def effective_now(now: datetime, state: Optional[dict], licence: Optional[Licence]) -> datetime:
    candidates = [now]
    mark = (state or {}).get("high_water")
    if mark:
        try:
            candidates.append(datetime.fromisoformat(mark))
        except ValueError:
            pass
    if licence is not None:
        candidates.append(licence.issued)
    return max(candidates)


def evaluate(
    licence: Licence, *, now: datetime, active_employees: int, state: Optional[dict] = None
) -> Dict[str, Entitlement]:
    """Every plugin's entitlement under `licence`, judged at `now` (already
    effective). Where a plugin appears on several lines the best one wins."""
    today = now.date()
    over = (state or {}).get("over_since") or {}
    rank = {ACTIVE: 6, TRIAL: 6, OVER_LIMIT: 5, GRACE: 4, PAUSED_OVER_LIMIT: 2, EXPIRED: 1, NONE: 0}
    out: Dict[str, Entitlement] = {}
    for line in licence.lines:
        plugin = line["plugin"]
        expires = _parse_date(line.get("expires"), "expiry date")
        grace_until = expires + timedelta(days=licence.grace_days)
        seats = line.get("seats")
        seats = int(seats) if seats not in (None, "") else None
        trial = bool(line.get("trial"))
        over_since = None
        if today <= expires:
            st = TRIAL if trial else ACTIVE
        elif today <= grace_until and not trial:
            st = GRACE
        else:
            st = EXPIRED
        if st in (ACTIVE, TRIAL, GRACE) and seats is not None and active_employees > seats:
            raw = over.get(plugin)
            over_since = date.fromisoformat(raw) if raw else today
            st = PAUSED_OVER_LIMIT if today - over_since >= OVER_LIMIT_GRACE else OVER_LIMIT
        ent = Entitlement(
            plugin=plugin, state=st, model=line.get("model"), expires=expires,
            grace_until=None if trial else grace_until, seats=seats,
            used=active_employees if seats is not None else None,
            trial=trial, via=line.get("via"), over_since=over_since,
        )
        best = out.get(plugin)
        if best is None or rank[st] > rank[best.state] or (
            rank[st] == rank[best.state] and expires > (best.expires or date.min)
        ):
            out[plugin] = ent
    return out
