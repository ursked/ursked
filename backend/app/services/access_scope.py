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


# Conflict of interest in the admin portal (session_portal). An administrator
# who is also an employee has every power over the company in an admin
# session, and the owner's rule is that those powers are for other people: in
# the admin portal nobody changes their own shifts, attendance, overtime, pay
# or roles, or decides their own leave. The same person does their own things
# from the employee dashboard, where they are an employee like anyone else,
# and anything that needs deciding goes to someone else. Other roles (HR,
# managers, Finance) are unaffected: they have no second portal to move to.
OWN_RECORD_MESSAGES = {
    "shifts": "Someone else has to change your own shifts.",
    "attendance": "Someone else has to change your own attendance.",
    "overtime": "Someone else has to decide your own overtime.",
    "pay": "Someone else has to change your own pay.",
    "roles": "Someone else has to change your own roles.",
    "leave": "Someone else has to approve your own leave.",
}


def assert_not_own_record(user: User, employee_ids: Iterable[Optional[int]], what: str) -> None:
    """In an admin session, refuse an action on the admin's own record."""
    if not getattr(user, "in_admin_portal", False):
        return
    if user.id in {e for e in employee_ids if e is not None}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=OWN_RECORD_MESSAGES[what]
        )


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
    *,
    own: Optional[str] = None,
) -> None:
    """Raise 403 unless `user` may act on every one of `employee_ids`.

    `own` names what a write does (a key of OWN_RECORD_MESSAGES): in an admin
    session it also refuses when the admin's own id is among the targets.
    Reads leave it out, since looking at your own record is never a conflict."""
    wanted = {e for e in employee_ids if e is not None}
    if not wanted:
        return
    if own:
        assert_not_own_record(user, wanted, own)
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
    *,
    leave_out_own: bool = False,
) -> Optional[list]:
    """Narrow a bulk operation to what `user` manages.

    `requested` None means "everyone I can act on". Returns None only when the
    caller has full scope AND asked for everyone; otherwise an explicit list, so
    a bulk delete can never silently widen to the whole tenant.

    `leave_out_own`: in an admin session, the admin's own row is taken out of
    the result (see OWN_RECORD_MESSAGES). These are the whole-view operations
    ("clear the shifts in view", "copy last week"): the grid sends every row
    it shows, the admin's own included, so refusing would make them unusable
    in the admin portal. Their previews run through here too, so the counts
    the confirmation shows are the counts that will be written.
    """
    allowed = await managed_employee_ids(db, user, module)
    if requested is None:
        result = None if allowed is None else sorted(allowed)
    else:
        wanted = set(requested)
        if allowed is not None:
            outside = wanted - allowed
            if outside:
                await assert_manages(db, user, outside, module)
        result = sorted(wanted)
    if leave_out_own and getattr(user, "in_admin_portal", False):
        if result is None:
            everyone = await db.execute(select(User.id).where(User.tenant_id == user.tenant_id))
            result = sorted(everyone.scalars().all())
        result = [e for e in result if e != user.id]
    return result
