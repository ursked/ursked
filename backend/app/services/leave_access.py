"""Who may see and act on a leave request, and who counts as an approver.

The contract in permission_service is the starting point: approving a step is
governed by the approver chain, not by the matrix. The matrix governs reading
other people's leave (leave:view), filing on someone's behalf (leave:create),
configuring leave and stepping in on a stuck approval (leave:edit), and deleting
configuration (leave:delete). Scope (access_scope) decides whose requests a role
without full leave scope reaches.

Until 2026-09 every one of those questions was answered by "does the caller hold
one of four role codes", so any manager could approve any request company-wide,
an employee named as an approver could never see the request they had to
approve, and nobody could step in when an approver was stuck.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Set
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.permission import RolePermission
from app.models.role import Role, UserRole
from app.models.user import User
from app.services.access_scope import has_full_scope, managed_employee_ids
from app.services.permission_service import (
    DEFAULT_PERMISSIONS,
    FULL_SCOPE_ROLES,
)

# Roles that give a person a place to review leave in the app (the Approvals
# tab). Someone named as an approver without one of these could be routed a
# request they had no screen to act on, which is how the audit's deadlock began.
REVIEWER_ROLE_CODES = {"tenant_admin", "hr", "manager", "leave_approver"}


async def has_permission(db: AsyncSession, user: User, module: str, action: str) -> bool:
    """The matrix check `require_permission` makes, usable inside a handler."""
    if user.has_role("tenant_admin"):
        return True
    role_ids = user.role_ids
    col = {
        "view": RolePermission.can_view,
        "create": RolePermission.can_create,
        "edit": RolePermission.can_edit,
        "delete": RolePermission.can_delete,
    }.get(action)
    if not role_ids or col is None:
        return False
    # Not PermissionService.check_permission: it uses scalar_one_or_none and
    # raises when two of the user's roles both grant the action (e.g. manager +
    # leave_approver both have leave:view). Reported to area E.
    hit = (
        await db.execute(
            select(RolePermission.id)
            .where(
                RolePermission.role_id.in_(role_ids),
                RolePermission.module == module,
                col == True,  # noqa: E712
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return hit is not None


def full_name(u) -> str:
    return f"{u.first_name} {u.last_name}".strip() if u else ""


async def leave_editors(
    db: AsyncSession,
    tenant_id: UUID,
    *,
    full_scope_only: bool = False,
    exclude: Iterable[int] = (),
) -> List[tuple]:
    """Active users who hold leave:edit, as (id, first, last, role_code) rows.

    tenant_admin always has every permission, so it is included without a
    matrix row. Ordered admins first, then HR, then anyone else, then by id, so
    "the first one" is stable and predictable in the UI copy.
    """
    excluded = {e for e in exclude if e is not None}
    edit_role_ids = select(RolePermission.role_id).where(
        RolePermission.tenant_id == tenant_id,
        RolePermission.module == "leave",
        RolePermission.can_edit == True,  # noqa: E712
    )
    stmt = (
        select(User.id, User.first_name, User.last_name, Role.code)
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .where(
            User.tenant_id == tenant_id,
            User.is_active == True,  # noqa: E712
            Role.tenant_id == tenant_id,
            Role.is_active == True,  # noqa: E712
            or_(Role.code == "tenant_admin", Role.id.in_(edit_role_ids)),
        )
    )
    if full_scope_only:
        stmt = stmt.where(Role.code.in_(FULL_SCOPE_ROLES["leave"]))
    rows = (await db.execute(stmt)).all()
    rank = {"tenant_admin": 0, "hr": 1}
    best: dict[int, tuple] = {}
    for r in rows:
        if r.id in excluded:
            continue
        cur = best.get(r.id)
        if cur is None or rank.get(r.code, 9) < rank.get(cur[3], 9):
            best[r.id] = (r.id, r.first_name, r.last_name, r.code)
    return sorted(best.values(), key=lambda t: (rank.get(t[3], 9), t[0]))


async def _leave_approver_role(db: AsyncSession, tenant_id: UUID) -> Role:
    role = (
        await db.execute(
            select(Role).where(Role.tenant_id == tenant_id, Role.code == "leave_approver")
        )
    ).scalar_one_or_none()
    if role is not None:
        return role
    # Every tenant is seeded with the system roles; this only runs on a tenant
    # whose seed predates leave_approver. Create it with the default matrix row
    # so the person granted it can actually see the Approvals tab.
    role = Role(
        tenant_id=tenant_id,
        code="leave_approver",
        name="Leave Approver",
        description="Approves leave requests routed to them.",
        is_system=True,
        is_active=True,
    )
    db.add(role)
    await db.flush()
    for module, (v, c, e, d, extra) in DEFAULT_PERMISSIONS["leave_approver"].items():
        db.add(RolePermission(
            tenant_id=tenant_id, role_id=role.id, module=module,
            can_view=v, can_create=c, can_edit=e, can_delete=d,
            extra_permissions=extra or {},
        ))
    await db.flush()
    return role


async def user_role_codes(db: AsyncSession, user_id: int) -> Set[str]:
    rows = (
        await db.execute(
            select(Role.code)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id, Role.is_active == True)  # noqa: E712
        )
    ).scalars().all()
    return set(rows)


async def ensure_reviewer_role(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: int,
    *,
    granted_by: Optional[int] = None,
    context: str = "",
) -> bool:
    """Give `user_id` the leave_approver role if they have no reviewer role.

    Decision (2026-09): naming someone as an approver is the admin saying "this
    person approves leave". Refusing the save would push the admin to a second
    screen; silently saving left the named person unable to act. So the role is
    granted, the UI says so before saving, and the grant is audit-logged.
    Returns True when a role was granted.
    """
    if await user_role_codes(db, user_id) & REVIEWER_ROLE_CODES:
        return False
    role = await _leave_approver_role(db, tenant_id)
    exists = (
        await db.execute(
            select(UserRole.id).where(UserRole.user_id == user_id, UserRole.role_id == role.id)
        )
    ).scalar_one_or_none()
    if exists is None:
        db.add(UserRole(user_id=user_id, role_id=role.id, assigned_by=granted_by))
    from app.models.site_settings import AuditLog

    db.add(AuditLog(
        tenant_id=tenant_id,
        user_id=granted_by,
        action="leave_approver_role_granted",
        resource_type="user",
        resource_id=str(user_id),
        details={"reason": context or "named as a leave approver"},
    ))
    await db.flush()
    return True


async def approver_check(db: AsyncSession, tenant_id: UUID, user_id: int) -> dict:
    """What happens if an admin names `user_id` as an approver. Read-only."""
    u = (
        await db.execute(select(User).where(User.id == user_id, User.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if u is None:
        return {"user_id": user_id, "found": False, "is_active": False,
                "has_reviewer_role": False, "will_grant_role": False,
                "message": "This employee does not exist."}
    codes = await user_role_codes(db, user_id)
    has_role = bool(codes & REVIEWER_ROLE_CODES)
    name = full_name(u)
    if not u.is_active:
        msg = f"{name} is inactive and cannot approve leave. Choose someone else."
    elif has_role:
        msg = ""
    else:
        msg = (
            f"{name} does not approve leave yet. Saving will give them the "
            "Leave Approver role so they can see and act on the requests sent to them."
        )
    return {
        "user_id": u.id,
        "name": name,
        "found": True,
        "is_active": bool(u.is_active),
        "has_reviewer_role": has_role,
        "will_grant_role": bool(u.is_active and not has_role),
        "message": msg,
    }


async def assert_can_be_approver(db: AsyncSession, tenant_id: UUID, user_id: Optional[int]) -> None:
    """Refuse inactive or unknown users as approvers, with a readable reason."""
    from fastapi import HTTPException

    if user_id is None:
        return
    u = (
        await db.execute(select(User).where(User.id == user_id, User.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if u is None:
        raise HTTPException(status_code=400, detail="The chosen approver does not exist.")
    if not u.is_active:
        raise HTTPException(
            status_code=400,
            detail=f"{full_name(u)} is inactive and cannot approve leave. Choose someone else.",
        )


@dataclass
class LeaveViewer:
    """The caller's reach over leave requests, computed once per request."""

    user: User
    can_view: bool = False
    can_create: bool = False
    can_edit: bool = False
    # None = everyone (full leave scope). Otherwise the employees this user
    # manages through the org chart, themselves included.
    managed: Optional[Set[int]] = field(default=None)

    @classmethod
    async def build(cls, db: AsyncSession, user: User) -> "LeaveViewer":
        v = cls(user=user)
        v.can_view = await has_permission(db, user, "leave", "view")
        v.can_create = await has_permission(db, user, "leave", "create")
        v.can_edit = await has_permission(db, user, "leave", "edit")
        v.managed = await managed_employee_ids(db, user, "leave")
        return v

    @property
    def full_scope(self) -> bool:
        return has_full_scope(self.user, "leave")

    def manages(self, employee_id: int) -> bool:
        return self.managed is None or employee_id in self.managed

    def in_chain(self, app) -> bool:
        return any(s.approver_id == self.user.id for s in (app.approval_steps or []))

    def can_read(self, app) -> bool:
        if app.employee_id == self.user.id or self.in_chain(app):
            return True
        return self.can_view and self.manages(app.employee_id)

    def can_override(self, app) -> bool:
        """Override / reassign: leave:edit over this employee, never your own."""
        return (
            self.can_edit
            and app.employee_id != self.user.id
            and self.manages(app.employee_id)
        )
