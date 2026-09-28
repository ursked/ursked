from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import get_current_user, require_permission
from app.models.user import User
from app.schemas.org_hierarchy import (
    ApprovalChainResponse,
    AssignMembersRequest,
    OrgLevelResponse,
    OrgLevelsResponse,
    OrgLevelsSet,
    OrgNodeCreate,
    OrgNodeDeletePreview,
    OrgNodeMembersResponse,
    OrgNodeMemberSummary,
    OrgNodeResponse,
    OrgNodeUpdate,
    OrgTreeResponse,
    UnassignMembersRequest,
)
from app.services.org_service import OrgService

router = APIRouter(prefix="/organizations", tags=["Organizations"])


# ── Level Endpoints ──────────────────────────────────────────────────


@router.get("/levels", response_model=OrgLevelsResponse)
async def get_levels(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("organization", "view")),
):
    levels = await OrgService.get_levels(db, current_user.tenant_id)
    return OrgLevelsResponse(
        levels=[OrgLevelResponse.model_validate(l) for l in levels]
    )


@router.put("/levels", response_model=OrgLevelsResponse)
async def set_levels(
    payload: OrgLevelsSet,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("organization", "edit")),
):
    from app.services.leave_access import has_permission

    items = [item.model_dump() for item in payload.levels]
    changes = OrgService.level_changes(
        await OrgService.get_levels(db, current_user.tenant_id), items
    )
    if changes["added"] and not await has_permission(db, current_user, "organization", "create"):
        raise HTTPException(status_code=403, detail="You do not have permission to add organization levels.")
    if changes["removed"] and not await has_permission(db, current_user, "organization", "delete"):
        raise HTTPException(status_code=403, detail="You do not have permission to remove organization levels.")
    try:
        levels = await OrgService.set_levels(db, current_user.tenant_id, items)
        await db.commit()
        return OrgLevelsResponse(
            levels=[OrgLevelResponse.model_validate(l) for l in levels]
        )
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


# ── Tree Endpoint ────────────────────────────────────────────────────


@router.get("/tree", response_model=OrgTreeResponse)
async def get_tree(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tree = await OrgService.get_full_tree(db, current_user.tenant_id)
    return tree


# ── Node CRUD Endpoints ─────────────────────────────────────────────


@router.post("/nodes", response_model=OrgNodeResponse, status_code=201)
async def create_node(
    data: OrgNodeCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("organization", "create")),
):
    try:
        node = await OrgService.create_node(
            db, current_user.tenant_id, data.model_dump(exclude_none=True),
            granted_by=current_user.id,
        )
        await db.commit()
        return _node_to_response(node)
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/nodes/{node_id}", response_model=OrgNodeResponse)
async def get_node(
    node_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    node = await OrgService.get_node_by_id(db, node_id, current_user.tenant_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    # Count members for this node
    member_counts = await OrgService._count_members_per_node(
        db, current_user.tenant_id
    )
    return _node_to_response(node, member_counts.get(node.id, 0))


@router.patch("/nodes/{node_id}", response_model=OrgNodeResponse)
async def update_node(
    node_id: int,
    data: OrgNodeUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("organization", "edit")),
):
    node = await OrgService.get_node_by_id(db, node_id, current_user.tenant_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    try:
        updated = await OrgService.update_node(
            db,
            node,
            current_user.tenant_id,
            data.model_dump(exclude_unset=True),
            granted_by=current_user.id,
        )
        await db.commit()
        return _node_to_response(updated)
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/nodes/{node_id}/delete-preview", response_model=OrgNodeDeletePreview)
async def delete_node_preview(
    node_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("organization", "delete")),
):
    """What deleting this unit would change, for the confirm dialog."""
    preview = await OrgService.delete_preview(db, node_id, current_user.tenant_id)
    if preview is None:
        raise HTTPException(status_code=404, detail="Node not found")
    return preview


@router.delete("/nodes/{node_id}", status_code=204)
async def delete_node(
    node_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("organization", "delete")),
):
    """Delete one unit. Its members and sub-units move to its parent; nothing
    below it is deleted with it (see OrgService.delete_preview)."""
    try:
        deleted = await OrgService.delete_node(db, node_id, current_user.tenant_id)
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(e))
    if deleted is None:
        raise HTTPException(status_code=404, detail="Node not found")
    await db.commit()


# ── Member Endpoints ─────────────────────────────────────────────────


@router.get("/nodes/{node_id}/members", response_model=OrgNodeMembersResponse)
async def get_node_members(
    node_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("organization", "view")),
):
    node = await OrgService.get_node_by_id(db, node_id, current_user.tenant_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    members = await OrgService.get_node_members(
        db, node_id, current_user.tenant_id
    )
    return OrgNodeMembersResponse(
        node_id=node.id,
        node_name=node.name,
        members=[OrgNodeMemberSummary(**m) for m in members],
        total=len(members),
    )


@router.post("/nodes/{node_id}/members", status_code=200)
async def assign_members(
    node_id: int,
    data: AssignMembersRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("organization", "edit")),
):
    node = await OrgService.get_node_by_id(db, node_id, current_user.tenant_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    count = await OrgService.assign_members(
        db, node_id, data.user_ids, current_user.tenant_id,
        assigned_by=current_user.id,
    )
    await db.commit()
    return {"assigned": count}


@router.delete("/nodes/{node_id}/members", status_code=200)
async def unassign_members(
    node_id: int,
    data: UnassignMembersRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("organization", "edit")),
):
    count = await OrgService.unassign_members(
        db, node_id, data.user_ids, current_user.tenant_id
    )
    await db.commit()
    return {"unassigned": count}


# ── Secondary Member Endpoints ───────────────────────────────────────


@router.post("/nodes/{node_id}/secondary-members", status_code=200)
async def assign_secondary_members(
    node_id: int,
    data: AssignMembersRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("organization", "edit")),
):
    node = await OrgService.get_node_by_id(db, node_id, current_user.tenant_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    count = await OrgService.assign_secondary_members(
        db, node_id, data.user_ids, current_user.tenant_id,
        assigned_by=current_user.id,
    )
    await db.commit()
    return {"assigned": count}


@router.delete("/nodes/{node_id}/secondary-members", status_code=200)
async def remove_secondary_members(
    node_id: int,
    data: UnassignMembersRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("organization", "edit")),
):
    count = await OrgService.remove_secondary_members(
        db, node_id, data.user_ids, current_user.tenant_id,
    )
    await db.commit()
    return {"removed": count}


# ── Approval Chain Endpoint ──────────────────────────────────────────


@router.get(
    "/approval-chain/{user_id}", response_model=ApprovalChainResponse
)
async def get_approval_chain(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("organization", "view")),
):
    """Who would approve this employee's leave if they filed now.

    This used to walk the org chart on its own (OrgService.get_approval_chain)
    and so disagreed with filing whenever the policy used rules, a head was
    inactive, or the fallback applied. It now calls the same resolver filing
    uses, so the two cannot drift apart again.
    """
    from sqlalchemy import select

    from app.services.access_scope import assert_manages
    from app.services.leave_approval_service import LeaveApprovalService

    await assert_manages(db, current_user, [user_id], "organization")
    user = (
        await db.execute(
            select(User).where(User.id == user_id, User.tenant_id == current_user.tenant_id)
        )
    ).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    chain = await LeaveApprovalService.resolve_chain_for_employee(
        db, current_user.tenant_id, user
    )
    return ApprovalChainResponse(
        employee_id=user.id,
        employee_name=user.full_name,
        chain=[
            {
                "step_order": c["step_order"],
                "approver_id": c["approver_id"],
                "approver_name": c["approver_name"],
                "source": c["source"],
                "is_deputy": bool(c.get("is_deputy")),
                "node_name": c.get("node_name"),
            }
            for c in chain
        ],
    )


# ── Helpers ──────────────────────────────────────────────────────────


def _node_to_response(node, member_count: int = 0) -> OrgNodeResponse:
    return OrgNodeResponse(
        id=node.id,
        parent_id=node.parent_id,
        level_id=node.level_id,
        level_name=node.level.name if node.level else "",
        name=node.name,
        code=node.code,
        description=node.description,
        head_user_id=node.head_user_id,
        head_user_name=node.head_user.full_name if node.head_user else None,
        deputy_head_user_id=node.deputy_head_user_id,
        deputy_head_user_name=(
            node.deputy_head_user.full_name if node.deputy_head_user else None
        ),
        sort_order=node.sort_order,
        is_active=node.is_active,
        member_count=member_count,
        schedule_visibility=node.schedule_visibility,
    )
