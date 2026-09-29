"""The rules every write to an employee record follows, whichever door it comes
through: the Add/Edit form, bulk edit or CSV import. Before 2026-09 each door
had its own subset, so an import could store an employee type the form would
refuse, and a duplicate email was a 400 on create but a 500 on edit.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.org_hierarchy import OrgNode
from app.models.role import Role
from app.models.user import User
from app.schemas.user import UserResponse
from app.services import access_scope, employee_access, employee_field_service
from app.services.configurable_type_service import ConfigurableTypeService
from app.services.permission_service import ADMIN_ROLE, SELF_ASSIGNABLE_ROLES
from app.services.role_service import RoleService
from app.services.user_service import UserService

PRIVILEGED_ROLE_CODES = {"tenant_admin"}


async def validate_fields(
    db: AsyncSession,
    tenant_id,
    data: Dict[str, Any],
    target: Optional[User] = None,
) -> None:
    """Raise a readable 400 for the first thing wrong with `data` (the keys the
    caller is setting). `target` is None when creating."""
    # Only values being changed are checked: a type or format that was retired
    # after it was assigned must not block every other edit to the record.
    if data.get("employee_type") and data["employee_type"] != (target.employee_type if target else None) \
            and not await ConfigurableTypeService.validate_employee_type(
        db, tenant_id, data["employee_type"]
    ):
        raise HTTPException(
            status_code=400,
            detail=f"Unknown employee type '{data['employee_type']}'. Configure it under Employee Types first.",
        )
    if "schedule_format" in data and data["schedule_format"] != (target.schedule_format if target else None):
        await UserService.assert_valid_schedule_format(db, tenant_id, data["schedule_format"])
    if "org_node_id" in data and data["org_node_id"] != (target.org_node_id if target else None):
        await UserService.assert_valid_org_unit(db, tenant_id, data["org_node_id"])
    if "reports_to_id" in data and data["reports_to_id"] != (target.reports_to_id if target else None):
        await UserService.assert_valid_reports_to(db, target, tenant_id, data["reports_to_id"])
    await UserService.assert_no_conflict(
        db,
        tenant_id,
        email=data.get("email") if "email" in data else None,
        username=data.get("username") if "username" in data else None,
        personnel_number=data.get("personnel_number") if "personnel_number" in data else None,
        exclude_id=target.id if target else None,
    )


async def assert_roles_exist(db: AsyncSession, tenant_id, codes: Iterable[str]) -> None:
    codes = set(codes)
    known = {
        r[0]
        for r in (
            await db.execute(select(Role.code).where(Role.tenant_id == tenant_id, Role.is_active == True))  # noqa: E712
        ).all()
    }
    unknown = sorted(codes - known)
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown role: {', '.join(unknown)}.")


def assert_may_grant(actor: User, codes: Iterable[str]) -> None:
    if actor.has_role("tenant_admin"):
        return
    requested = set(codes) & PRIVILEGED_ROLE_CODES
    if requested:
        raise HTTPException(
            status_code=403,
            detail=f"Only a tenant admin may grant: {', '.join(sorted(requested))}",
        )


def assert_may_revoke(actor: User, codes: Iterable[str]) -> None:
    if actor.has_role("tenant_admin"):
        return
    privileged = set(codes) & PRIVILEGED_ROLE_CODES
    if privileged:
        raise HTTPException(
            status_code=403,
            detail=f"Only a tenant admin may revoke: {', '.join(sorted(privileged))}",
        )


async def set_roles(db: AsyncSession, actor: User, user: User, role_codes: Sequence[str]) -> Tuple[List[str], List[str]]:
    """Make the user's roles exactly `role_codes` (+ employee). Returns
    (before, after) sorted; equal lists mean nothing changed."""
    # Stored roles, not the ones in force for this request: `user` may be the
    # caller themselves, whose tenant_admin is dormant in an employee session,
    # and re-granting a role they already hold would duplicate it.
    current = set(user.stored_role_codes)
    wanted = set(role_codes) | {"employee"}
    own = user.id == actor.id and wanted != current
    if own:
        assert_may_change_own_roles(actor, current, wanted)
    # Authority first: "you may not grant that" is the answer whether or not
    # the role happens to exist.
    assert_may_grant(actor, wanted - current)
    assert_may_revoke(actor, current - wanted)
    await assert_roles_exist(db, user.tenant_id, wanted - current)
    if "tenant_admin" in current - wanted:
        await employee_access.assert_may_remove_admin_role(db, user)
    for code in current - wanted:
        await RoleService.remove_role(db, user.id, code, user.tenant_id)
    for code in wanted - current:
        await RoleService.assign_role(db, user.id, code, user.tenant_id, assigned_by=actor.id)
    if wanted != current:
        # A role change alters what the account may do, so every existing
        # session must re-authenticate to pick it up.
        user.tokens_valid_from = datetime.now(timezone.utc)
    if own:
        await announce_own_role_change(db, actor, sorted(current), sorted(wanted))
    return sorted(current), sorted(wanted)


# Your own roles (owner, 2026-09-29). Administration and operations are
# separate (permission_service), so an administrator who also schedules,
# approves leave or reads reports needs that role as well, and in a one-person
# company nobody else can give it to them. So an administrator, in the admin
# dashboard, may give themselves or drop the operational roles; it is never
# silent (audit log, and every other administrator is told in-app and by
# email). Their OWN administrator role and active status stay someone else's
# to change, and nobody changes their own roles from the regular dashboard.
def assert_may_change_own_roles(actor: User, current: set, wanted: set) -> None:
    changed = current ^ wanted
    if ADMIN_ROLE in changed:
        raise HTTPException(status_code=403, detail=access_scope.OWN_RECORD_MESSAGES["roles"])
    if not getattr(actor, "in_admin_portal", False) or not actor.has_role(ADMIN_ROLE):
        raise HTTPException(
            status_code=403,
            detail=(
                "You cannot change your own roles here. An administrator can, "
                "from the admin dashboard."
            ),
        )
    refused = sorted(changed - SELF_ASSIGNABLE_ROLES - {"employee"})
    if refused:
        raise HTTPException(
            status_code=403,
            detail=(
                f"You cannot give yourself or remove from yourself: {', '.join(refused)}. "
                "Another administrator has to."
            ),
        )


async def announce_own_role_change(db: AsyncSession, actor: User, before: list, after: list) -> None:
    """Audit an administrator's change to their own roles and tell every other
    active administrator, in-app and by email."""
    import html

    from app.services import audit_service
    from app.services.email_service import EmailService
    from app.services.email_templates import _base_wrapper
    from app.services.notification_service import NotificationService

    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    audit_service.record(
        db, actor=actor, action="own_roles_change", resource_type="user", resource_id=actor.id,
        details={"added": added, "removed": removed, "from": before, "to": after},
    )
    name = audit_service.user_label(actor)
    parts = []
    if added:
        parts.append(f"gave themselves {', '.join(_role_label(c) for c in added)}")
    if removed:
        parts.append(f"removed {', '.join(_role_label(c) for c in removed)} from themselves")
    body = f"{name} {' and '.join(parts)}."
    if "finance" in added:
        body += " Salary figures still need another person's approval (salary access)."
    title = "An administrator changed their own roles"
    others = await employee_access.active_admin_ids(db, actor.tenant_id) - {actor.id}
    if not others:
        return
    rows = (await db.execute(select(User).where(User.id.in_(others)))).scalars().all()
    for other in rows:
        await NotificationService.notify(
            db, actor.tenant_id, other.id, type="own_roles_change", title=title, body=body,
        )
        if other.email:
            page = _base_wrapper(
                f"<h2 style=\"margin:0 0 12px\">{html.escape(title)}</h2>"
                f"<p style=\"margin:0\">{html.escape(body)}</p>"
            )
            EmailService.fire_and_forget(
                lambda db, to=other.email, t=title, pg=page: EmailService.send_email(
                    db, to, t, pg, log_type="own_roles_change"
                )
            )


_ROLE_LABELS = {
    "manager": "Manager",
    "hr": "HR",
    "schedule_editor": "Schedule Editor",
    "leave_approver": "Leave Approver",
    "report_viewer": "Reports & data",
    "finance": "Finance",
}


def _role_label(code: str) -> str:
    return _ROLE_LABELS.get(code, code)


async def creation_access(db: AsyncSession, actor: User) -> employee_field_service.ViewerAccess:
    """Field access for filling in a record the actor is creating: whoever may
    add an employee may fill in every field they can see, before the new
    person has an org unit that would put them in the actor's scope."""
    access = await employee_field_service.viewer_access(db, actor)
    access.can_view = True
    access.can_edit = True
    access.read_scope = None
    access.edit_scope = None
    return access


async def serialize(
    db: AsyncSession,
    users: Sequence[User],
    viewer: User,
    *,
    listing: bool = False,
    access: Optional[employee_field_service.ViewerAccess] = None,
) -> List[UserResponse]:
    """UserResponse for each user, with the names, invite state and custom
    fields `viewer` may see, and the separation reason removed for anyone
    without company-wide employee scope."""
    if not users:
        return []
    tenant_id = viewer.tenant_id
    ids = [u.id for u in users]

    node_ids = {u.org_node_id for u in users if u.org_node_id}
    node_names = {}
    if node_ids:
        node_names = dict(
            (await db.execute(select(OrgNode.id, OrgNode.name).where(OrgNode.id.in_(node_ids)))).all()
        )
    mgr_ids = {u.reports_to_id for u in users if u.reports_to_id}
    mgr_names = {}
    if mgr_ids:
        mgr_names = {
            i: f"{f} {l}".strip()
            for i, f, l in (
                await db.execute(select(User.id, User.first_name, User.last_name).where(User.id.in_(mgr_ids)))
            ).all()
        }
    invites = await UserService.pending_invites(db, ids)
    if access is None:
        access = await employee_field_service.viewer_access(db, viewer)
    custom = await employee_field_service.values_for(db, tenant_id, ids, access, listing=listing)
    full_scope = employee_access.has_full_employee_scope(viewer)

    out = []
    for u in users:
        r = UserResponse.model_validate(u)
        r.org_node_name = node_names.get(u.org_node_id)
        r.reports_to_name = mgr_names.get(u.reports_to_id)
        r.invite_pending = u.id in invites
        r.invite_expired = invites.get(u.id, False)
        r.custom_fields = custom.get(u.id, {})
        if u.id != viewer.id and not full_scope:
            r.separation_reason = None
        out.append(r)
    return out
