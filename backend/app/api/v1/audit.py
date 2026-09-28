"""Read-only audit log for the tenant's own records (CE scope).

Backs the admin Audit Log page. Tenant admins can see who did what and when —
employee changes (with before/after values), roles, separations, imports, bulk
edits, custom field changes, logins and anything else that writes an entry.

`GET /settings/audit-log` is an older duplicate of this listing (owned by the
settings area); this is the endpoint the viewer uses.

CE scope: read-only, own tenant only, tenant_admin.
Paid (not built): cross-tenant audit dashboard, log retention policies, export.
"""
import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Text, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import get_current_user, require_role
from app.models.site_settings import AuditLog
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/audit", tags=["Audit"])

# Plain-English names for actions, for the filter list and descriptions.
ACTION_LABELS = {
    "login_success": "Signed in",
    "login_failure": "Failed sign-in",
    "user_create": "Added employee",
    "user_update": "Edited employee",
    "user_roles_change": "Changed roles",
    "user_separate": "Separated employee",
    "user_reinstate": "Reinstated employee",
    "user_deactivate": "Deactivated employee",
    "user_invite_resend": "Resent invite",
    "profile_update": "Edited own profile",
    "users_import": "Imported employees",
    "users_bulk_update": "Bulk edit",
    "custom_field_create": "Added custom field",
    "custom_field_update": "Changed custom field",
    "custom_field_archive": "Archived custom field",
    "custom_field_delete": "Deleted custom field",
    "custom_field_reorder": "Reordered custom fields",
    "employee_number_label_update": "Renamed employee number",
    "permissions_update": "Changed role permissions",
    "two_factor_enabled": "Turned on two-factor sign-in",
    "two_factor_disabled": "Turned off two-factor sign-in",
    "session_revoked": "Signed out a session",
}

_BULK_LABELS = {
    "set_employee_type": "set the employee type",
    "set_schedule_format": "set the schedule format",
    "set_org_unit": "moved to another unit",
    "set_reports_to": "set the line manager",
    "send_invite": "sent invites",
    "separate": "separated",
}


def _field_name(key: str) -> str:
    return key.replace("_id", "").replace("_", " ")


def describe(row: AuditLog, actor_name: Optional[str]) -> str:
    """One readable sentence for an entry."""
    d: Dict[str, Any] = row.details or {}
    who = actor_name or row.user_email or "System"
    target = d.get("target_name") or (f"employee #{row.resource_id}" if row.resource_id else "")
    a = row.action
    if a == "login_success":
        return f"{who} signed in"
    if a == "login_failure":
        return f"Failed sign-in attempt for {row.user_email or 'an unknown account'}"
    if a == "user_create":
        return f"{who} added {target}" + (" and sent an invite" if d.get("invited") else "")
    if a in ("user_update", "profile_update"):
        fields = list((d.get("changes") or {}).keys()) + [f"{k} (custom)" for k in (d.get("custom_fields") or {})]
        subject = "their own profile" if a == "profile_update" else target
        return f"{who} changed {', '.join(_field_name(f) for f in fields) or 'details'} for {subject}"
    if a == "user_roles_change":
        return f"{who} changed {target}'s roles from {', '.join(d.get('from') or [])} to {', '.join(d.get('to') or [])}"
    if a == "user_separate":
        return f"{who} marked {target} as {d.get('separation_type')} on {d.get('separation_date')}"
    if a == "user_reinstate":
        return f"{who} reinstated {target}"
    if a == "user_deactivate":
        return f"{who} deactivated {target}"
    if a == "user_invite_resend":
        return f"{who} resent the invite to {target}"
    if a == "users_import":
        return (
            f"{who} imported {d.get('filename') or 'a file'}: {d.get('created', 0)} added, "
            f"{d.get('updated', 0)} updated, {d.get('failed', 0)} failed"
        )
    if a == "users_bulk_update":
        c = d.get("counts") or {}
        return (
            f"{who} {_BULK_LABELS.get(d.get('bulk_action'), 'bulk edited')} for {c.get('updated', 0)} employee(s)"
            + (f", {c.get('error')} failed" if c.get("error") else "")
        )
    if a.startswith("custom_field_") and a != "custom_field_reorder":
        verb = ACTION_LABELS.get(a, a).lower()
        return f"{who} {verb} “{d.get('label')}”"
    if a == "employee_number_label_update":
        return f"{who} renamed the employee number field to “{d.get('to') or 'Personnel #'}”"
    return f"{who}: {ACTION_LABELS.get(a, a.replace('_', ' '))}" + (f" ({target})" if target else "")


@router.get("/actions")
async def list_actions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(["tenant_admin"])),
):
    """Actions present in this tenant's log, with labels, for the filter."""
    rows = await db.execute(
        select(AuditLog.action).where(AuditLog.tenant_id == current_user.tenant_id).distinct()
    )
    actions = sorted({r[0] for r in rows.all()} | set(ACTION_LABELS))
    return [{"action": a, "label": ACTION_LABELS.get(a, a.replace("_", " ").capitalize())} for a in actions]


@router.get("/logs")
async def list_audit_logs(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(["tenant_admin"])),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    action: Optional[str] = Query(None, description="Filter by action (e.g. login_success, user_create)"),
    user_id: Optional[int] = Query(None, description="Filter by acting user ID"),
    target_user_id: Optional[int] = Query(None, description="Entries about this employee"),
    resource_type: Optional[str] = Query(None, max_length=100),
    resource_id: Optional[str] = Query(None, max_length=100),
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
):
    """Paginated audit log for this tenant, newest first. Read-only."""
    base = select(AuditLog).where(
        AuditLog.tenant_id == current_user.tenant_id,
    )
    if action:
        base = base.where(AuditLog.action == action)
    if user_id:
        base = base.where(AuditLog.user_id == user_id)
    if target_user_id:
        # Direct entries about the employee, plus batch entries (import, bulk)
        # that list them.
        tid = str(target_user_id)
        as_text = cast(AuditLog.details, Text)
        listed = or_(*(as_text.like(p) for p in (f"%[{tid}]%", f"%[{tid},%", f"%, {tid},%", f"%, {tid}]%")))
        base = base.where(
            or_(
                (AuditLog.resource_type == "user") & (AuditLog.resource_id == tid),
                AuditLog.action.in_(("users_import", "users_bulk_update")) & listed,
            )
        )
    if resource_type:
        base = base.where(AuditLog.resource_type == resource_type)
    if resource_id:
        base = base.where(AuditLog.resource_id == resource_id)
    if date_from:
        base = base.where(AuditLog.created_at >= datetime.combine(date_from, time.min, tzinfo=timezone.utc))
    if date_to:
        base = base.where(
            AuditLog.created_at < datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=timezone.utc)
        )

    total = await db.scalar(select(func.count()).select_from(base.subquery()))

    stmt = (
        base
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()

    actor_ids = {r.user_id for r in rows if r.user_id}
    names = {}
    if actor_ids:
        names = {
            i: f"{f} {l}".strip()
            for i, f, l in (
                await db.execute(select(User.id, User.first_name, User.last_name).where(User.id.in_(actor_ids)))
            ).all()
        }

    return {
        "items": [
            {
                "id": r.id,
                "user_id": r.user_id,
                "user_email": r.user_email,
                "user_name": names.get(r.user_id),
                "action": r.action,
                "action_label": ACTION_LABELS.get(r.action, r.action.replace("_", " ").capitalize()),
                "description": describe(r, names.get(r.user_id)),
                "resource_type": r.resource_type,
                "resource_id": r.resource_id,
                "details": r.details,
                "ip_address": r.ip_address,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
        "total": total or 0,
        "page": page,
        "per_page": per_page,
        "total_pages": ((total or 0) + per_page - 1) // per_page,
    }

