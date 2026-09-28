"""Who a user may act ON, as distinct from what they may do.

The permission matrix answers "may this role edit shifts?". It cannot answer
"whose shifts?", and until 2026-09 nothing did: a manager limited on the grid to
their own team could still create, move, delete and publish anyone's shifts by
calling the API, and "Clear all" deleted the whole company's range.

Every write that targets another employee goes through `assert_manages`. The
rule is deliberately simple so it can be explained in one sentence on screen:

    Roles listed in FULL_SCOPE_ROLES for the module act on everyone. Anyone else
    acts on the members of the org units they head or deputise, including every
    unit below them, plus themselves.

Read visibility is a separate, looser concept (ScheduleService
.get_visible_employee_ids): an employee can SEE teammates in their own unit
without being able to change them.
"""

from __future__ import annotations

from typing import Iterable, Optional, Set

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.org_hierarchy import OrgNode
from app.models.user import User
from app.services.permission_service import FULL_SCOPE_ROLES


def has_full_scope(user: User, module: str) -> bool:
    return bool(set(user.role_codes) & FULL_SCOPE_ROLES.get(module, {"tenant_admin"}))


async def managed_employee_ids(
    db: AsyncSession, user: User, module: str
) -> Optional[Set[int]]:
    """Employee ids `user` may act on in `module`. None means everyone."""
    if has_full_scope(user, module):
        return None

    # Imported here: schedule_service imports a great deal and this module is
    # imported by routers that schedule_service itself does not need.
    from app.services.schedule_service import ScheduleService

    head_ids = (
        await db.execute(
            select(OrgNode.id).where(
                OrgNode.tenant_id == user.tenant_id,
                OrgNode.is_active == True,  # noqa: E712
                or_(
                    OrgNode.head_user_id == user.id,
                    OrgNode.deputy_head_user_id == user.id,
                ),
            )
        )
    ).scalars().all()

    ids: Set[int] = {user.id}
    if head_ids:
        node_ids = await ScheduleService._get_descendant_node_ids(
            db, list(head_ids), user.tenant_id
        )
        ids.update(
            await ScheduleService._get_node_member_ids(db, list(node_ids), user.tenant_id)
        )
    return ids


async def assert_manages(
    db: AsyncSession,
    user: User,
    employee_ids: Iterable[Optional[int]],
    module: str,
) -> None:
    """Raise 403 unless `user` may act on every one of `employee_ids`."""
    wanted = {e for e in employee_ids if e is not None}
    if not wanted:
        return
    allowed = await managed_employee_ids(db, user, module)
    if allowed is None:
        return
    outside = wanted - allowed
    if outside:
        n = len(outside)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"{n} of the selected employees {'is' if n == 1 else 'are'} outside "
                "the teams you manage."
            ),
        )


async def scope_employee_ids(
    db: AsyncSession,
    user: User,
    requested: Optional[Iterable[int]],
    module: str,
) -> Optional[list]:
    """Narrow a bulk operation to what `user` manages.

    `requested` None means "everyone I can act on". Returns None only when the
    caller has full scope AND asked for everyone; otherwise an explicit list, so
    a bulk delete can never silently widen to the whole tenant.
    """
    allowed = await managed_employee_ids(db, user, module)
    if requested is None:
        return None if allowed is None else sorted(allowed)
    wanted = set(requested)
    if allowed is not None:
        outside = wanted - allowed
        if outside:
            await assert_manages(db, user, outside, module)
    return sorted(wanted)
