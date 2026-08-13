"""Per-node schedule visibility grants (tenant_admin / hr).

Lets an admin grant a specific user visibility into a specific org node's
schedule (and, by default, its subtree), on top of the built-in scoping. See
NodeScheduleVisibility.
"""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import get_current_user, require_role
from app.models.org_hierarchy import NodeScheduleVisibility, OrgNode
from app.models.user import User
from app.services.schedule_service import ScheduleService

router = APIRouter(prefix="/schedule-visibility", tags=["Schedule Visibility"])


class GrantCreate(BaseModel):
    user_id: int
    org_node_id: int
    include_descendants: bool = True


class GrantResponse(BaseModel):
    id: int
    user_id: int
    user_name: Optional[str] = None
    org_node_id: int
    org_node_name: Optional[str] = None
    include_descendants: bool
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


async def _to_response(db: AsyncSession, grant: NodeScheduleVisibility) -> GrantResponse:
    user = await db.get(User, grant.user_id)
    node = await db.get(OrgNode, grant.org_node_id)
    return GrantResponse(
        id=grant.id,
        user_id=grant.user_id,
        user_name=(f"{user.first_name} {user.last_name}" if user else None),
        org_node_id=grant.org_node_id,
        org_node_name=(node.name if node else None),
        include_descendants=grant.include_descendants,
        created_at=grant.created_at,
    )


@router.get("", response_model=List[GrantResponse])
async def list_grants(
    user_id: Optional[int] = None,
    current_user: User = Depends(require_role(["tenant_admin", "hr"])),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(NodeScheduleVisibility).where(
        NodeScheduleVisibility.tenant_id == current_user.tenant_id
    )
    if user_id is not None:
        stmt = stmt.where(NodeScheduleVisibility.user_id == user_id)
    stmt = stmt.order_by(NodeScheduleVisibility.created_at.desc())
    rows = (await db.execute(stmt)).scalars().all()
    return [await _to_response(db, r) for r in rows]


@router.post("", response_model=GrantResponse, status_code=201)
async def create_grant(
    payload: GrantCreate,
    current_user: User = Depends(require_role(["tenant_admin", "hr"])),
    db: AsyncSession = Depends(get_db),
):
    # Both the user and the node must belong to the caller's tenant.
    user = await db.get(User, payload.user_id)
    if not user or user.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="User not found")
    node = await db.get(OrgNode, payload.org_node_id)
    if not node or node.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Org node not found")

    # Idempotent on (user, node): update the flag if it already exists.
    existing = (
        await db.execute(
            select(NodeScheduleVisibility).where(
                NodeScheduleVisibility.tenant_id == current_user.tenant_id,
                NodeScheduleVisibility.user_id == payload.user_id,
                NodeScheduleVisibility.org_node_id == payload.org_node_id,
            )
        )
    ).scalar_one_or_none()
    if existing:
        existing.include_descendants = payload.include_descendants
        await db.commit()
        await db.refresh(existing)
        return await _to_response(db, existing)

    grant = NodeScheduleVisibility(
        tenant_id=current_user.tenant_id,
        user_id=payload.user_id,
        org_node_id=payload.org_node_id,
        include_descendants=payload.include_descendants,
        created_by=current_user.id,
    )
    db.add(grant)
    await db.commit()
    await db.refresh(grant)
    return await _to_response(db, grant)


@router.delete("/{grant_id}", status_code=204)
async def delete_grant(
    grant_id: int,
    current_user: User = Depends(require_role(["tenant_admin", "hr"])),
    db: AsyncSession = Depends(get_db),
):
    grant = await db.get(NodeScheduleVisibility, grant_id)
    if not grant or grant.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Grant not found")
    await db.delete(grant)
    await db.commit()


# ── Accessible nodes (any authenticated user) ─────────────────────────

class AccessibleNode(BaseModel):
    id: int
    parent_id: Optional[int] = None
    name: str
    code: Optional[str] = None
    visible_member_count: int


class AccessibleNodesResponse(BaseModel):
    can_see_all: bool
    nodes: List[AccessibleNode]


@router.get("/accessible-nodes", response_model=AccessibleNodesResponse)
async def accessible_nodes(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The org nodes whose schedules the CURRENT user may view, with a count of
    the members they can actually see in each. Powers a node picker/tree that
    mirrors the user's real visibility (built-in scope + per-node override +
    secondary assignments + explicit grants)."""
    visible_ids = await ScheduleService.get_visible_employee_ids(
        db, current_user.tenant_id, current_user.id, current_user.role_codes
    )

    # Load the tenant's active nodes once.
    nodes = (
        await db.execute(
            select(OrgNode).where(
                OrgNode.tenant_id == current_user.tenant_id,
                OrgNode.is_active == True,  # noqa: E712
            )
        )
    ).scalars().all()

    if visible_ids is None:
        # Admin / "all" scope: every node, full membership.
        counts = await _member_counts_for_nodes(db, current_user.tenant_id, None)
        return AccessibleNodesResponse(
            can_see_all=True,
            nodes=[
                AccessibleNode(
                    id=n.id, parent_id=n.parent_id, name=n.name, code=n.code,
                    visible_member_count=counts.get(n.id, 0),
                )
                for n in nodes
            ],
        )

    counts = await _member_counts_for_nodes(
        db, current_user.tenant_id, set(visible_ids)
    )
    # Only surface nodes where the user can see at least one member.
    return AccessibleNodesResponse(
        can_see_all=False,
        nodes=[
            AccessibleNode(
                id=n.id, parent_id=n.parent_id, name=n.name, code=n.code,
                visible_member_count=counts.get(n.id, 0),
            )
            for n in nodes
            if counts.get(n.id, 0) > 0
        ],
    )


async def _member_counts_for_nodes(
    db: AsyncSession, tenant_id, visible_ids: Optional[set]
) -> dict:
    """Count active members per node (primary + secondary assignment). When
    visible_ids is given, only those users are counted; None counts everyone."""
    from app.models.configurable_types import UserOrgNode

    counts: dict[int, set] = {}

    # Primary assignment.
    primary = await db.execute(
        select(User.org_node_id, User.id).where(
            User.tenant_id == tenant_id,
            User.is_active == True,  # noqa: E712
            User.org_node_id.isnot(None),
        )
    )
    for node_id, uid in primary.all():
        if visible_ids is None or uid in visible_ids:
            counts.setdefault(node_id, set()).add(uid)

    # Secondary assignments.
    secondary = await db.execute(
        select(UserOrgNode.org_node_id, UserOrgNode.user_id)
        .join(User, User.id == UserOrgNode.user_id)
        .where(User.tenant_id == tenant_id, User.is_active == True)  # noqa: E712
    )
    for node_id, uid in secondary.all():
        if visible_ids is None or uid in visible_ids:
            counts.setdefault(node_id, set()).add(uid)

    return {node_id: len(uids) for node_id, uids in counts.items()}
