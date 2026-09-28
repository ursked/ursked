"""Separating and reinstating an employee, and everything that has to follow.

Separating used to flip is_active and stop there (audit E-14): the person
stayed head of their unit, so approvals kept routing to someone who had gone;
their shifts after the leaving date stayed on the grid, counted as cover that
would never turn up; and every session they had open kept working until it
expired. Reinstating then revived any of those tokens that had not.

Everything here runs in the caller's transaction, so a separation either
happens with all of its clean-up or not at all (a payroll-lock handler vetoing
the shift deletion, for example, cancels the whole separation).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Dict, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.org_hierarchy import OrgNode
from app.models.schedule import Shift
from app.models.user import User, UserInviteToken
from app.services import domain_events
from app.services.user_service import UserService


async def separate(
    db: AsyncSession,
    *,
    actor: User,
    user: User,
    separation_type: Optional[str],
    separation_date: Optional[date],
    reason: Optional[str],
    delete_future_shifts: bool,
) -> Dict[str, int]:
    """Deactivate `user` and clean up after them. Returns what was done, for
    the response and the audit entry. Guards (who may do this) are the
    caller's job: employee_access.assert_may_change_active_status."""
    user.is_active = False
    user.separation_type = separation_type
    user.separation_date = separation_date
    user.separation_reason = reason
    user.separated_by = actor.id

    # Heads and deputies: a unit headed by someone who has left routes every
    # approval to nobody. Cleared outright; the Organization page shows the
    # unit as headless so someone picks a successor.
    headed = (
        await db.execute(
            update(OrgNode)
            .where(OrgNode.tenant_id == user.tenant_id, OrgNode.head_user_id == user.id)
            .values(head_user_id=None)
        )
    ).rowcount or 0
    deputised = (
        await db.execute(
            update(OrgNode)
            .where(OrgNode.tenant_id == user.tenant_id, OrgNode.deputy_head_user_id == user.id)
            .values(deputy_head_user_id=None)
        )
    ).rowcount or 0

    shifts_deleted = 0
    if delete_future_shifts and separation_date is not None:
        shifts = (
            await db.execute(
                select(Shift).where(
                    Shift.tenant_id == user.tenant_id,
                    Shift.employee_id == user.id,
                    Shift.date > separation_date,
                )
            )
        ).scalars().all()
        if shifts:
            changes = sorted({(s.employee_id, s.date) for s in shifts})
            # Through the shift events, so a finalized payroll period can veto
            # and attendance can re-derive, exactly as for any other deletion.
            await domain_events.emit(
                "shift.before_write", db=db, tenant_id=user.tenant_id, actor=actor, changes=changes
            )
            for s in shifts:
                await db.delete(s)
            await db.flush()
            await domain_events.emit(
                "shift.after_write", db=db, tenant_id=user.tenant_id, actor=actor, changes=changes
            )
            shifts_deleted = len(shifts)

    # Sign them out everywhere, and make any unused activation link useless:
    # reinstating must never revive access that existed before.
    sessions = await UserService.revoke_all_sessions(db, user)
    now = datetime.now(timezone.utc)
    await db.execute(
        update(UserInviteToken)
        .where(UserInviteToken.user_id == user.id, UserInviteToken.used_at.is_(None))
        .values(used_at=now)
    )
    await db.flush()

    # Area L reassigns the approvals this person was due to decide.
    await domain_events.emit(
        "employee.separated", db=db, tenant_id=user.tenant_id, actor=actor, user=user
    )
    return {
        "units_headed_cleared": int(headed),
        "units_deputised_cleared": int(deputised),
        "future_shifts_deleted": shifts_deleted,
        "sessions_revoked": sessions,
    }


async def reinstate(db: AsyncSession, *, user: User) -> None:
    user.is_active = True
    user.separation_type = None
    user.separation_date = None
    user.separation_reason = None
    user.separated_by = None
    # A fresh cutoff: anything minted before reinstatement stays dead, even a
    # token issued before the separation that has not expired yet.
    user.tokens_valid_from = datetime.now(timezone.utc)
    await db.flush()
