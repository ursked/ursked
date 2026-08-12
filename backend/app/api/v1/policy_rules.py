from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import get_current_user, require_permission
from app.models.user import User
from app.schemas.policy import (
    PolicyRuleCreate,
    PolicyRuleResponse,
    PolicyRuleUpdate,
    PolicySimulateRequest,
    PolicySimulateResponse,
)
from app.services.attendance_service import AttendanceService
from app.services.policy_rule_service import PolicyRuleService

router = APIRouter(prefix="/policy-rules", tags=["policy-rules"])


@router.post("/simulate", response_model=PolicySimulateResponse)
async def simulate_policy_rules(
    data: PolicySimulateRequest,
    current_user: User = Depends(require_permission("settings", "view")),
    db: AsyncSession = Depends(get_db),
):
    """Dry-run the active rules over a date range and report the effects they
    WOULD apply, without writing anything (rule sandbox / what-if)."""
    return await AttendanceService.simulate_policy_rules(
        db, current_user.tenant_id, data.start_date, data.end_date, data.employee_ids
    )


@router.get("", response_model=List[PolicyRuleResponse])
async def list_policy_rules(
    rule_type: Optional[str] = Query(None),
    active_only: bool = Query(True),
    current_user: User = Depends(require_permission("settings", "view")),
    db: AsyncSession = Depends(get_db),
):
    rules = await PolicyRuleService.list_rules(
        db, current_user.tenant_id, rule_type, active_only
    )
    return [_rule_response(r) for r in rules]


@router.get("/{rule_id}", response_model=PolicyRuleResponse)
async def get_policy_rule(
    rule_id: int,
    current_user: User = Depends(require_permission("settings", "view")),
    db: AsyncSession = Depends(get_db),
):
    rule = await PolicyRuleService.get_rule(db, current_user.tenant_id, rule_id)
    if not rule:
        raise HTTPException(404, "Policy rule not found")
    return _rule_response(rule)


@router.post("", response_model=PolicyRuleResponse, status_code=201)
async def create_policy_rule(
    data: PolicyRuleCreate,
    current_user: User = Depends(require_permission("settings", "create")),
    db: AsyncSession = Depends(get_db),
):
    try:
        # conditions (tree) and actions are already plain JSON via model_dump().
        rule_data = data.model_dump()
        rule = await PolicyRuleService.create_rule(
            db, current_user.tenant_id, rule_data, current_user.id
        )
        await db.commit()
        return _rule_response(rule)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.put("/{rule_id}", response_model=PolicyRuleResponse)
async def update_policy_rule(
    rule_id: int,
    data: PolicyRuleUpdate,
    current_user: User = Depends(require_permission("settings", "edit")),
    db: AsyncSession = Depends(get_db),
):
    # conditions (tree) and actions are already plain JSON via model_dump().
    update_data = data.model_dump(exclude_unset=True)
    try:
        rule = await PolicyRuleService.update_rule(db, current_user.tenant_id, rule_id, update_data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not rule:
        raise HTTPException(404, "Policy rule not found")
    await db.commit()
    return _rule_response(rule)


@router.delete("/{rule_id}", status_code=204)
async def delete_policy_rule(
    rule_id: int,
    current_user: User = Depends(require_permission("settings", "delete")),
    db: AsyncSession = Depends(get_db),
):
    deleted = await PolicyRuleService.delete_rule(db, current_user.tenant_id, rule_id)
    if not deleted:
        raise HTTPException(404, "Policy rule not found")
    await db.commit()


def _rule_response(rule) -> dict:
    return {
        "id": rule.id,
        "tenant_id": str(rule.tenant_id),
        "name": rule.name,
        "description": rule.description,
        "rule_type": rule.rule_type,
        "priority": rule.priority,
        "is_active": rule.is_active,
        "conditions": rule.conditions or [],
        "actions": rule.actions or [],
        "employment_types": rule.employment_types,
        "scope_org_node_ids": rule.scope_org_node_ids,
        "effective_from": rule.effective_from,
        "effective_until": rule.effective_until,
        "created_by": rule.created_by,
        "created_at": rule.created_at,
        "updated_at": rule.updated_at,
    }
