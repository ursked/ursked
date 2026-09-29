"""Writing the admin audit trail.

Until 2026-09 the audit log recorded logins and little else: who changed an
employee's email, who granted a role, who separated someone and why, which
import created forty accounts — none of it was written down. Every change to an
employee record now leaves an entry with what it was before and what it became,
so "who did this?" has an answer.

Entries are added to the caller's session and committed with the change they
describe; if the change rolls back, so does its entry, and nothing is recorded
that did not happen.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, Iterable, Optional
from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.site_settings import AuditLog
from app.models.user import User
from app.utils.client_ip import client_address

# The employee fields whose changes are recorded, in display order.
USER_FIELDS = (
    "first_name", "middle_name", "last_name", "email", "username", "contact_number",
    "personnel_number", "typecode", "id_number", "rank", "job_title", "hiring_date",
    "employee_type", "schedule_format", "org_node_id", "reports_to_id",
)

# Never stored in the audit log, whatever a caller passes.
_NEVER = {"password", "password_hash", "totp_secret", "backup_codes"}


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (UUID, Decimal)):
        return str(value)
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items() if str(k) not in _NEVER}
    if isinstance(value, (set, frozenset)):
        return sorted(json_safe(v) for v in value)
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    return str(value)


def snapshot_user(user: User, fields: Iterable[str] = USER_FIELDS) -> Dict[str, Any]:
    return {f: json_safe(getattr(user, f, None)) for f in fields}


def diff(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """{field: {"from": old, "to": new}} for every field whose value changed."""
    out: Dict[str, Dict[str, Any]] = {}
    for key in list(before.keys()) + [k for k in after.keys() if k not in before]:
        if key in _NEVER:
            continue
        old, new = json_safe(before.get(key)), json_safe(after.get(key))
        if old != new:
            out[key] = {"from": old, "to": new}
    return out


def _client_ip(request: Optional[Request]) -> Optional[str]:
    # A browser can set X-Forwarded-For, so an audit trail that believed it
    # recorded whatever address the actor chose. Only a trusted proxy's word
    # counts now (app/utils/client_ip.py); otherwise the entry has no address.
    addr = client_address(request)
    return addr[:50] if addr else None


def record(
    db: AsyncSession,
    *,
    actor: Optional[User],
    action: str,
    tenant_id: Any = None,
    resource_type: Optional[str] = None,
    resource_id: Any = None,
    details: Optional[Dict[str, Any]] = None,
    request: Optional[Request] = None,
) -> AuditLog:
    """Add one audit entry to the session (committed with the caller's change)."""
    entry = AuditLog(
        tenant_id=tenant_id if tenant_id is not None else (actor.tenant_id if actor else None),
        user_id=actor.id if actor else None,
        user_email=actor.email if actor else None,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        details=json_safe(details or {}),
        ip_address=_client_ip(request),
        user_agent=(request.headers.get("user-agent", "")[:500] if request else None),
    )
    db.add(entry)
    return entry


def user_label(user: User) -> str:
    return f"{user.first_name} {user.last_name}".strip() or user.email
