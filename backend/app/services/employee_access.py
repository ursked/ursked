"""Who may do what to an employee record.

The permission matrix (permission_service) says what a role may do in the
employees module and access_scope says to whom. Neither can express the rules
that protect the tenant itself, and until 2026-09 nothing did: HR could change
the administrator's email address, request a password reset to it and sign in
as the administrator, or simply deactivate them. These rules sit on top of the
matrix and cannot be switched off from the Permissions screen:

  * Only a tenant_admin may change the sign-in details (email, username,
    password) or the active status of a user who holds tenant_admin.
  * Nobody changes their own active status. Separation is something done TO
    you, and a self-deactivation by mistake would lock the only admin out.
  * The last active tenant_admin can never be separated, deactivated or lose
    the role, whoever asks. A company with no administrator cannot be fixed
    from inside the app.
"""

from __future__ import annotations

from typing import Iterable, Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.role import Role, UserRole
from app.models.user import User
from app.services import access_scope
from app.services.permission_service import FULL_SCOPE_ROLES, PermissionService

# Fields that decide who can sign in as a user. Changing any of them on an
# administrator is an account takeover path, so it is reserved to administrators.
SIGN_IN_FIELDS = {"email", "username", "password"}

_ACTION_WORDS = {
    "view": "view",
    "create": "add",
    "edit": "edit",
    "delete": "separate or reinstate",
}


async def has_permission(db: AsyncSession, user: User, module: str, action: str) -> bool:
    if user.has_role("tenant_admin"):
        return True
    role_ids = [ur.role_id for ur in user.user_roles]
    return await PermissionService.check_permission(db, user.tenant_id, role_ids, module, action)


async def require(db: AsyncSession, user: User, module: str, action: str) -> None:
    """Raise a readable 403 unless `user` holds module:action."""
    if await has_permission(db, user, module, action):
        return
    if module == "employees":
        detail = f"You do not have permission to {_ACTION_WORDS.get(action, action)} employees."
    elif module == "settings":
        detail = "You do not have permission to change company settings." if action != "view" else (
            "You do not have permission to view company settings."
        )
    else:
        detail = f"You do not have permission to {action} {module}."
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def has_full_employee_scope(user: User) -> bool:
    return bool(set(user.role_codes) & FULL_SCOPE_ROLES["employees"])


async def is_hr_level(db: AsyncSession, user: User) -> bool:
    """HR-level = may edit any employee record company-wide.

    This is the audience for 'HR only' custom fields and for separation
    reasons: a team manager granted employees:edit for their own team is not
    HR, and neither is Finance, which reads everyone but edits no one.
    """
    if user.has_role("tenant_admin"):
        return True
    return has_full_employee_scope(user) and await has_permission(db, user, "employees", "edit")


async def readable_employee_ids(db: AsyncSession, user: User):
    """Ids `user` may read in the employee directory. None means everyone.

    Reading someone else's record needs employees:view; whose records is the
    same org-chart scope that governs writes, so a manager sees their own
    teams, not the whole company's contact details.
    """
    if not await has_permission(db, user, "employees", "view"):
        return {user.id}
    return await access_scope.managed_employee_ids(db, user, "employees")


async def assert_can_read(db: AsyncSession, viewer: User, target_id: int) -> None:
    """404 rather than 403 for records outside the caller's scope, so the
    directory cannot be used to probe which ids exist."""
    if target_id == viewer.id:
        return
    allowed = await readable_employee_ids(db, viewer)
    if allowed is not None and target_id not in allowed:
        raise HTTPException(status_code=404, detail="Employee not found")


async def assert_manages(db: AsyncSession, actor: User, ids: Iterable[Optional[int]]) -> None:
    await access_scope.assert_manages(db, actor, ids, "employees")


async def active_admin_ids(db: AsyncSession, tenant_id) -> set:
    rows = await db.execute(
        select(User.id)
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .where(
            User.tenant_id == tenant_id,
            User.is_active == True,  # noqa: E712
            Role.code == "tenant_admin",
            Role.is_active == True,  # noqa: E712
        )
    )
    return {r[0] for r in rows.all()}


def assert_may_change_sign_in(actor: User, target: User, fields: Iterable[str]) -> None:
    touched = SIGN_IN_FIELDS & set(fields)
    if not touched:
        return
    if target.has_role("tenant_admin") and not actor.has_role("tenant_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Only an administrator can change the email address, username or "
                "password of an administrator."
            ),
        )


async def assert_may_change_active_status(db: AsyncSession, actor: User, target: User, deactivating: bool) -> None:
    if target.id == actor.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot change the active status of your own account.",
        )
    if target.has_role("tenant_admin"):
        if not actor.has_role("tenant_admin"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only an administrator can separate, deactivate or reinstate an administrator.",
            )
        if deactivating:
            others = await active_admin_ids(db, target.tenant_id) - {target.id}
            if not others:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"{target.first_name} {target.last_name} is the last active administrator. "
                        "Make someone else an administrator first."
                    ),
                )


async def assert_may_remove_admin_role(db: AsyncSession, target: User) -> None:
    others = await active_admin_ids(db, target.tenant_id) - {target.id}
    if target.is_active and not others:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"{target.first_name} {target.last_name} is the last active administrator, "
                "so the Administrator role cannot be removed. Make someone else an administrator first."
            ),
        )


async def count_active_admins(db: AsyncSession, tenant_id) -> int:
    return len(await active_admin_ids(db, tenant_id))


__all__ = [
    "SIGN_IN_FIELDS",
    "active_admin_ids",
    "assert_can_read",
    "assert_manages",
    "assert_may_change_active_status",
    "assert_may_change_sign_in",
    "assert_may_remove_admin_role",
    "count_active_admins",
    "has_full_employee_scope",
    "has_permission",
    "is_hr_level",
    "readable_employee_ids",
    "require",
]

