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
from app.services import employee_access, employee_field_service
from app.services.configurable_type_service import ConfigurableTypeService
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
    current = set(user.role_codes)
    wanted = set(role_codes) | {"employee"}
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
    return sorted(current), sorted(wanted)


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
