from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import get_current_user, require_role
from app.models.user import User
from app.schemas.org_hierarchy import (
    ApprovalChainResponse,
    AssignMembersRequest,
    OrgLevelResponse,
    OrgLevelsResponse,
    OrgLevelsSet,
    OrgNodeCreate,
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
    _=Depends(require_role(["tenant_admin", "hr"])),
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
    _=Depends(require_role(["tenant_admin"])),
):
    try:
        levels = await OrgService.set_levels(
            db,
            current_user.tenant_id,
            [item.model_dump() for item in payload.levels],
        )
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
    _=Depends(require_role(["tenant_admin", "hr"])),
):
    try:
        node = await OrgService.create_node(
            db, current_user.tenant_id, data.model_dump(exclude_none=True)
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
    _=Depends(require_role(["tenant_admin", "hr"])),
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
        )
        await db.commit()
        return _node_to_response(updated)
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/nodes/{node_id}", status_code=204)
async def delete_node(
    node_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(["tenant_admin"])),
):
    deleted = await OrgService.delete_node(db, node_id, current_user.tenant_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Node not found")
    await db.commit()


# ── Member Endpoints ─────────────────────────────────────────────────


@router.get("/nodes/{node_id}/members", response_model=OrgNodeMembersResponse)
async def get_node_members(
    node_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(["tenant_admin", "hr", "manager"])),
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
    _=Depends(require_role(["tenant_admin", "hr"])),
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
    _=Depends(require_role(["tenant_admin", "hr"])),
):
    count = await OrgService.unassign_members(
        db, data.user_ids, current_user.tenant_id
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
    _=Depends(require_role(["tenant_admin", "hr"])),
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
    _=Depends(require_role(["tenant_admin", "hr"])),
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
    _=Depends(require_role(["tenant_admin", "hr", "manager"])),
):
    # Get user info for the response
    from sqlalchemy import select

    user_stmt = select(User).where(
        User.id == user_id, User.tenant_id == current_user.tenant_id
    )
    result = await db.execute(user_stmt)
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    chain = await OrgService.get_approval_chain(
        db, user_id, current_user.tenant_id
    )
    return ApprovalChainResponse(
        employee_id=user.id,
        employee_name=user.full_name,
        chain=chain,
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
    )
