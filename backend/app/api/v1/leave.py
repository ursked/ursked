from datetime import datetime, date, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.middleware.auth import get_current_user, require_role
from app.models.leave import (
    LeaveApplication,
    LeaveApproverAssignment,
    LeavePolicy,
    LeavePolicyEntitlement,
    LeaveType,
    OvertimeCategory,
)
from app.models.org_hierarchy import OrgNode
from app.models.role import LeaveApprovalStep, Role, UserRole
from app.models.settings import AppSettings
from app.models.user import User
from app.schemas.leave import (
    ApprovalChainPreviewItem,
    ApprovalChainPreviewResponse,
    BulkEntitlementsRequest,
    LeaveApplicationCreate,
    LeaveApplicationListResponse,
    LeaveApplicationResponse,
    LeaveApplicationUpdate,
    LeaveApprovalStepResponse,
    LeaveApproverAssignmentCreate,
    LeaveApproverAssignmentResponse,
    LeaveApproverAssignmentUpdate,
    LeaveBalanceItem,
    LeaveBalanceResponse,
    LeavePolicyCreate,
    LeavePolicyEntitlementCreate,
    LeavePolicyEntitlementResponse,
    LeavePolicyEntitlementUpdate,
    LeavePolicyResponse,
    LeavePolicyUpdate,
    LeavePrecheckRequest,
    LeavePrecheckResponse,
    PolicyCompleteness,
    LeaveReviewRequest,
    LeaveRevokeRequest,
    LeaveTypeCreate,
    LeaveTypeResponse,
    LeaveTypeUpdate,
    OvertimeCategoryCreate,
    OvertimeCategoryResponse,
    OvertimeCategoryUpdate,
    TeamStatsResponse,
)
from app.services.email_service import EmailService
from app.services.leave_approval_service import LeaveApprovalService
from app.services.leave_rule_service import LeaveRuleService
from app.services.leave_service import LeaveService
from app.services.schedule_service import ScheduleService
from app.services.settings_service import SettingsService
from app.services.user_service import UserService

router = APIRouter(prefix="/leave", tags=["Leave"])

REVIEWER_ROLES = ["tenant_admin", "hr", "manager", "leave_approver"]
CONFIG_ROLES = ["tenant_admin", "hr"]


# ── Helpers ─────────────────────────────────────────────────────────


def _business_days(start: date, end: date) -> float:
    """Count business days (Mon-Fri) between two dates, inclusive."""
    if start > end:
        return 0.0
    count = 0
    current = start
    while current <= end:
        if current.weekday() < 5:
            count += 1
        current += timedelta(days=1)
    return float(count)


def _step_to_response(step: LeaveApprovalStep) -> LeaveApprovalStepResponse:
    approver_name = ""
    if step.approver:
        approver_name = f"{step.approver.first_name} {step.approver.last_name}"
    return LeaveApprovalStepResponse(
        id=step.id,
        step_order=step.step_order,
        approver_id=step.approver_id,
        approver_name=approver_name,
        status=step.status,
        decided_at=step.decided_at,
        notes=step.notes,
    )


def _to_response(app: LeaveApplication) -> LeaveApplicationResponse:
    """Convert a LeaveApplication ORM model to response schema."""
    employee_name = ""
    if app.employee:
        employee_name = f"{app.employee.first_name} {app.employee.last_name}"
    reviewer_name = None
    if app.reviewer:
        reviewer_name = f"{app.reviewer.first_name} {app.reviewer.last_name}"

    steps = []
    current_step = None
    if app.approval_steps:
        steps = [_step_to_response(s) for s in app.approval_steps]
        for s in app.approval_steps:
            if s.status == "pending":
                current_step = s.step_order
                break

    return LeaveApplicationResponse(
        id=app.id,
        employee_id=app.employee_id,
        employee_name=employee_name,
        leave_type=app.leave_type,
        start_date=app.start_date,
        end_date=app.end_date,
        days_requested=app.days_requested,
        reason=app.reason,
        supporting_documents=app.supporting_documents,
        status=app.status,
        reviewed_by=app.reviewed_by,
        reviewer_name=reviewer_name,
        reviewed_at=app.reviewed_at,
        reviewer_notes=app.reviewer_notes,
        rule_warnings=app.rule_warnings or None,
        approval_steps=steps,
        current_step=current_step,
        created_at=app.created_at,
        updated_at=app.updated_at,
    )


def _load_options():
    return [
        selectinload(LeaveApplication.employee),
        selectinload(LeaveApplication.reviewer),
        selectinload(LeaveApplication.approval_steps).selectinload(
            LeaveApprovalStep.approver
        ),
    ]


async def _has_reviewer_role(user: User) -> bool:
    user_role_codes = set(user.role_codes)
    return bool(user_role_codes & set(REVIEWER_ROLES))


async def _has_config_role(user: User) -> bool:
    user_role_codes = set(user.role_codes)
    return bool(user_role_codes & set(CONFIG_ROLES))


async def _get_app_settings(db: AsyncSession, tenant_id) -> Optional[AppSettings]:
    result = await db.execute(
        select(AppSettings).where(AppSettings.tenant_id == tenant_id)
    )
    return result.scalar_one_or_none()


async def _get_approver_emails(db: AsyncSession, tenant_id) -> list[dict]:
    """Get emails and names of users with reviewer roles for the tenant."""
    stmt = (
        select(User.email, User.first_name, User.last_name)
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .where(
            Role.tenant_id == tenant_id,
            Role.code.in_(REVIEWER_ROLES),
            User.is_active == True,
        )
        .distinct()
    )
    result = await db.execute(stmt)
    return [
        {"email": row.email, "name": f"{row.first_name} {row.last_name}"}
        for row in result.all()
    ]


def _entitlement_to_response(e: LeavePolicyEntitlement) -> LeavePolicyEntitlementResponse:
    return LeavePolicyEntitlementResponse(
        id=e.id,
        leave_type_id=e.leave_type_id,
        leave_type_code=e.leave_type.code if e.leave_type else "",
        leave_type_name=e.leave_type.name if e.leave_type else "",
        annual_credits=e.annual_credits,
        carry_over_enabled=e.carry_over_enabled,
        max_carry_over_days=e.max_carry_over_days,
        carry_over_expiry_months=e.carry_over_expiry_months,
        cash_convertible=e.cash_convertible,
        cash_conversion_rate=e.cash_conversion_rate,
        requires_documentation=e.requires_documentation,
        min_notice_days=e.min_notice_days,
    )


def _policy_completeness(p: LeavePolicy) -> PolicyCompleteness:
    """Server-computed completeness signals, reused by the policy cards and the
    Stage 3 setup checklist."""
    ents = p.entitlements or []
    if p.pool_type == "shared":
        has_entitlements = bool(p.shared_annual_credits and p.shared_annual_credits > 0)
        uncovered: list[str] = []
    else:
        has_entitlements = any((e.annual_credits or 0) > 0 for e in ents)
        uncovered = [
            e.leave_type.code
            for e in ents
            if e.leave_type and (e.annual_credits or 0) <= 0
        ]
    return PolicyCompleteness(
        has_employment_types=bool(p.employment_types),
        has_entitlements=has_entitlements,
        uncovered_leave_types=uncovered,
        has_approval_path=True,  # auto/hybrid always resolve; manual is validated elsewhere
        enforcement_configured=bool(p.enforcement),
    )


def _policy_to_response(p: LeavePolicy) -> LeavePolicyResponse:
    return LeavePolicyResponse(
        id=p.id,
        name=p.name,
        description=p.description,
        accrual_method=p.accrual_method,
        pool_type=p.pool_type,
        employment_types=p.employment_types or [],
        is_default=p.is_default,
        is_active=p.is_active,
        approval_mode=p.approval_mode or "auto",
        required_approval_levels=p.required_approval_levels or 1,
        enforcement=p.enforcement or {},
        shared_annual_credits=p.shared_annual_credits,
        shared_carry_over_enabled=p.shared_carry_over_enabled,
        shared_max_carry_over_days=p.shared_max_carry_over_days,
        shared_carry_over_expiry_months=p.shared_carry_over_expiry_months,
        shared_cash_convertible=p.shared_cash_convertible,
        shared_cash_conversion_rate=p.shared_cash_conversion_rate,
        shared_max_consecutive_days=p.shared_max_consecutive_days,
        entitlements=[_entitlement_to_response(e) for e in (p.entitlements or [])],
        completeness=_policy_completeness(p),
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


def _policy_load_options():
    return [
        selectinload(LeavePolicy.entitlements).selectinload(LeavePolicyEntitlement.leave_type),
    ]


async def _validate_leave_type(db: AsyncSession, tenant_id, leave_type_code: str):
    """Validate that a leave type code exists for this tenant."""
    result = await db.execute(
        select(LeaveType.id).where(
            LeaveType.tenant_id == tenant_id,
            LeaveType.code == leave_type_code,
            LeaveType.is_active == True,
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"Invalid leave type: {leave_type_code}")


# ══════════════════════════════════════════════════════════════════════
# LEAVE TYPE CONFIGURATION
# ══════════════════════════════════════════════════════════════════════


@router.get("/types", response_model=List[LeaveTypeResponse])
async def list_leave_types(
    include_inactive: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(LeaveType)
        .where(LeaveType.tenant_id == current_user.tenant_id)
        .order_by(LeaveType.sort_order, LeaveType.id)
    )
    if not include_inactive:
        stmt = stmt.where(LeaveType.is_active == True)
    result = await db.execute(stmt)
    return [LeaveTypeResponse.model_validate(lt) for lt in result.scalars().all()]


@router.post("/types", response_model=LeaveTypeResponse, status_code=201)
async def create_leave_type(
    data: LeaveTypeCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(CONFIG_ROLES)),
):
    existing = await db.execute(
        select(LeaveType).where(
            LeaveType.tenant_id == current_user.tenant_id,
            LeaveType.code == data.code,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Leave type code already exists")

    leave_type = LeaveType(
        tenant_id=current_user.tenant_id,
        code=data.code,
        name=data.name,
        description=data.description,
        is_system=False,
        sort_order=data.sort_order,
    )
    db.add(leave_type)
    await db.flush()

    # Approving leave writes this code into Shift.status, and the schedule grid
    # resolves presentation from shift_status_types. Provision the matching row
    # now so a custom leave type is renderable the first time it is approved,
    # rather than showing as an unrecognised grey cell.
    await SettingsService.ensure_status_type_for_leave_type(
        db,
        current_user.tenant_id,
        code=leave_type.code,
        label=leave_type.name,
        export_code=leave_type.export_code,
    )
    return LeaveTypeResponse.model_validate(leave_type)


@router.patch("/types/{type_id}", response_model=LeaveTypeResponse)
async def update_leave_type(
    type_id: int,
    data: LeaveTypeUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(CONFIG_ROLES)),
):
    result = await db.execute(
        select(LeaveType).where(
            LeaveType.id == type_id,
            LeaveType.tenant_id == current_user.tenant_id,
        )
    )
    leave_type = result.scalar_one_or_none()
    if not leave_type:
        raise HTTPException(status_code=404, detail="Leave type not found")

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(leave_type, key, value)

    await db.flush()
    return LeaveTypeResponse.model_validate(leave_type)


@router.delete("/types/{type_id}", status_code=204)
async def delete_leave_type(
    type_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(["tenant_admin"])),
):
    result = await db.execute(
        select(LeaveType).where(
            LeaveType.id == type_id,
            LeaveType.tenant_id == current_user.tenant_id,
        )
    )
    leave_type = result.scalar_one_or_none()
    if not leave_type:
        raise HTTPException(status_code=404, detail="Leave type not found")

    leave_type.is_active = False
    await db.flush()


# ══════════════════════════════════════════════════════════════════════
# LEAVE POLICY CONFIGURATION
# ══════════════════════════════════════════════════════════════════════


@router.get("/policies", response_model=List[LeavePolicyResponse])
async def list_leave_policies(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(LeavePolicy)
        .options(*_policy_load_options())
        .where(LeavePolicy.tenant_id == current_user.tenant_id)
        .order_by(LeavePolicy.is_default.desc(), LeavePolicy.id)
    )
    result = await db.execute(stmt)
    return [_policy_to_response(p) for p in result.scalars().all()]


@router.get("/policies/{policy_id}", response_model=LeavePolicyResponse)
async def get_leave_policy(
    policy_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(LeavePolicy)
        .options(*_policy_load_options())
        .where(
            LeavePolicy.id == policy_id,
            LeavePolicy.tenant_id == current_user.tenant_id,
        )
    )
    result = await db.execute(stmt)
    policy = result.scalar_one_or_none()
    if not policy:
        raise HTTPException(status_code=404, detail="Leave policy not found")
    return _policy_to_response(policy)


@router.post("/policies", response_model=LeavePolicyResponse, status_code=201)
async def create_leave_policy(
    data: LeavePolicyCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(CONFIG_ROLES)),
):
    tenant_id = current_user.tenant_id

    existing = await db.execute(
        select(LeavePolicy).where(
            LeavePolicy.tenant_id == tenant_id,
            LeavePolicy.name == data.name,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Policy name already exists")

    if data.is_default:
        from sqlalchemy import update
        await db.execute(
            update(LeavePolicy)
            .where(LeavePolicy.tenant_id == tenant_id, LeavePolicy.is_default == True)
            .values(is_default=False)
        )

    policy = LeavePolicy(
        tenant_id=tenant_id,
        name=data.name,
        description=data.description,
        accrual_method=data.accrual_method,
        pool_type=data.pool_type,
        employment_types=data.employment_types,
        is_default=data.is_default,
        approval_mode=data.approval_mode,
        required_approval_levels=data.required_approval_levels,
        enforcement=data.enforcement or {},
        shared_annual_credits=data.shared_annual_credits,
        shared_carry_over_enabled=data.shared_carry_over_enabled,
        shared_max_carry_over_days=data.shared_max_carry_over_days,
        shared_carry_over_expiry_months=data.shared_carry_over_expiry_months,
        shared_cash_convertible=data.shared_cash_convertible,
        shared_cash_conversion_rate=data.shared_cash_conversion_rate,
        shared_max_consecutive_days=data.shared_max_consecutive_days,
    )
    db.add(policy)
    await db.flush()

    if data.entitlements and data.pool_type == "per_type":
        for ent_data in data.entitlements:
            lt_result = await db.execute(
                select(LeaveType.id).where(
                    LeaveType.id == ent_data.leave_type_id,
                    LeaveType.tenant_id == tenant_id,
                )
            )
            if not lt_result.scalar_one_or_none():
                raise HTTPException(status_code=400, detail=f"Leave type {ent_data.leave_type_id} not found")

            entitlement = LeavePolicyEntitlement(
                policy_id=policy.id,
                leave_type_id=ent_data.leave_type_id,
                annual_credits=ent_data.annual_credits,
                carry_over_enabled=ent_data.carry_over_enabled,
                max_carry_over_days=ent_data.max_carry_over_days,
                carry_over_expiry_months=ent_data.carry_over_expiry_months,
                cash_convertible=ent_data.cash_convertible,
                cash_conversion_rate=ent_data.cash_conversion_rate,
                requires_documentation=ent_data.requires_documentation,
                min_notice_days=ent_data.min_notice_days,
                max_consecutive_days=ent_data.max_consecutive_days,
            )
            db.add(entitlement)
        await db.flush()

    stmt = (
        select(LeavePolicy)
        .options(*_policy_load_options())
        .where(LeavePolicy.id == policy.id)
    )
    result = await db.execute(stmt)
    policy = result.scalar_one()
    return _policy_to_response(policy)


@router.patch("/policies/{policy_id}", response_model=LeavePolicyResponse)
async def update_leave_policy(
    policy_id: int,
    data: LeavePolicyUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(CONFIG_ROLES)),
):
    tenant_id = current_user.tenant_id
    result = await db.execute(
        select(LeavePolicy)
        .options(*_policy_load_options())
        .where(
            LeavePolicy.id == policy_id,
            LeavePolicy.tenant_id == tenant_id,
        )
    )
    policy = result.scalar_one_or_none()
    if not policy:
        raise HTTPException(status_code=404, detail="Leave policy not found")

    update_data = data.model_dump(exclude_unset=True)

    if update_data.get("is_default") is True:
        from sqlalchemy import update
        await db.execute(
            update(LeavePolicy)
            .where(
                LeavePolicy.tenant_id == tenant_id,
                LeavePolicy.is_default == True,
                LeavePolicy.id != policy_id,
            )
            .values(is_default=False)
        )

    if "name" in update_data and update_data["name"] != policy.name:
        existing = await db.execute(
            select(LeavePolicy).where(
                LeavePolicy.tenant_id == tenant_id,
                LeavePolicy.name == update_data["name"],
                LeavePolicy.id != policy_id,
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Policy name already exists")

    for key, value in update_data.items():
        setattr(policy, key, value)

    await db.flush()

    stmt = (
        select(LeavePolicy)
        .options(*_policy_load_options())
        .where(LeavePolicy.id == policy.id)
    )
    result = await db.execute(stmt)
    policy = result.scalar_one()
    return _policy_to_response(policy)


@router.delete("/policies/{policy_id}", status_code=204)
async def delete_leave_policy(
    policy_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(["tenant_admin"])),
):
    result = await db.execute(
        select(LeavePolicy).where(
            LeavePolicy.id == policy_id,
            LeavePolicy.tenant_id == current_user.tenant_id,
        )
    )
    policy = result.scalar_one_or_none()
    if not policy:
        raise HTTPException(status_code=404, detail="Leave policy not found")

    policy.is_active = False
    await db.flush()


@router.post("/policies/{policy_id}/clone", response_model=LeavePolicyResponse, status_code=201)
async def clone_leave_policy(
    policy_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(CONFIG_ROLES)),
):
    """Duplicate a policy (with its entitlements and enforcement) as an
    inactive, non-default '(copy)'. Lets admins start from an existing policy
    instead of re-entering everything."""
    tenant_id = current_user.tenant_id
    src = (await db.execute(
        select(LeavePolicy)
        .options(*_policy_load_options())
        .where(LeavePolicy.id == policy_id, LeavePolicy.tenant_id == tenant_id)
    )).scalar_one_or_none()
    if not src:
        raise HTTPException(status_code=404, detail="Leave policy not found")

    # Unique name: "<name> (copy)", "<name> (copy 2)", ...
    base = f"{src.name} (copy)"
    name = base
    n = 2
    while True:
        clash = (await db.execute(
            select(LeavePolicy.id).where(
                LeavePolicy.tenant_id == tenant_id, LeavePolicy.name == name
            )
        )).scalar_one_or_none()
        if not clash:
            break
        name = f"{base} {n}"
        n += 1

    clone = LeavePolicy(
        tenant_id=tenant_id,
        name=name,
        description=src.description,
        accrual_method=src.accrual_method,
        pool_type=src.pool_type,
        employment_types=list(src.employment_types or []),
        is_default=False,
        is_active=False,
        approval_mode=src.approval_mode,
        required_approval_levels=src.required_approval_levels,
        enforcement=dict(src.enforcement or {}),
        shared_annual_credits=src.shared_annual_credits,
        shared_carry_over_enabled=src.shared_carry_over_enabled,
        shared_max_carry_over_days=src.shared_max_carry_over_days,
        shared_carry_over_expiry_months=src.shared_carry_over_expiry_months,
        shared_cash_convertible=src.shared_cash_convertible,
        shared_cash_conversion_rate=src.shared_cash_conversion_rate,
        shared_max_consecutive_days=src.shared_max_consecutive_days,
    )
    db.add(clone)
    await db.flush()

    for e in (src.entitlements or []):
        db.add(LeavePolicyEntitlement(
            policy_id=clone.id,
            leave_type_id=e.leave_type_id,
            annual_credits=e.annual_credits,
            carry_over_enabled=e.carry_over_enabled,
            max_carry_over_days=e.max_carry_over_days,
            carry_over_expiry_months=e.carry_over_expiry_months,
            cash_convertible=e.cash_convertible,
            cash_conversion_rate=e.cash_conversion_rate,
            requires_documentation=e.requires_documentation,
            min_notice_days=e.min_notice_days,
            max_consecutive_days=e.max_consecutive_days,
        ))
    await db.flush()

    clone = (await db.execute(
        select(LeavePolicy).options(*_policy_load_options()).where(LeavePolicy.id == clone.id)
    )).scalar_one()
    return _policy_to_response(clone)


# ══════════════════════════════════════════════════════════════════════
# POLICY ENTITLEMENTS
# ══════════════════════════════════════════════════════════════════════


@router.post("/policies/{policy_id}/entitlements", response_model=LeavePolicyEntitlementResponse, status_code=201)
async def add_policy_entitlement(
    policy_id: int,
    data: LeavePolicyEntitlementCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(CONFIG_ROLES)),
):
    tenant_id = current_user.tenant_id

    policy_result = await db.execute(
        select(LeavePolicy).where(
            LeavePolicy.id == policy_id,
            LeavePolicy.tenant_id == tenant_id,
        )
    )
    if not policy_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Leave policy not found")

    lt_result = await db.execute(
        select(LeaveType).where(
            LeaveType.id == data.leave_type_id,
            LeaveType.tenant_id == tenant_id,
        )
    )
    leave_type = lt_result.scalar_one_or_none()
    if not leave_type:
        raise HTTPException(status_code=400, detail="Leave type not found")

    dup = await db.execute(
        select(LeavePolicyEntitlement).where(
            LeavePolicyEntitlement.policy_id == policy_id,
            LeavePolicyEntitlement.leave_type_id == data.leave_type_id,
        )
    )
    if dup.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Entitlement for this leave type already exists in this policy")

    entitlement = LeavePolicyEntitlement(
        policy_id=policy_id,
        leave_type_id=data.leave_type_id,
        annual_credits=data.annual_credits,
        carry_over_enabled=data.carry_over_enabled,
        max_carry_over_days=data.max_carry_over_days,
        carry_over_expiry_months=data.carry_over_expiry_months,
        cash_convertible=data.cash_convertible,
        cash_conversion_rate=data.cash_conversion_rate,
        requires_documentation=data.requires_documentation,
        min_notice_days=data.min_notice_days,
    )
    db.add(entitlement)
    await db.flush()

    stmt = (
        select(LeavePolicyEntitlement)
        .options(selectinload(LeavePolicyEntitlement.leave_type))
        .where(LeavePolicyEntitlement.id == entitlement.id)
    )
    result = await db.execute(stmt)
    entitlement = result.scalar_one()
    return _entitlement_to_response(entitlement)


@router.patch("/policies/{policy_id}/entitlements/{entitlement_id}", response_model=LeavePolicyEntitlementResponse)
async def update_policy_entitlement(
    policy_id: int,
    entitlement_id: int,
    data: LeavePolicyEntitlementUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(CONFIG_ROLES)),
):
    stmt = (
        select(LeavePolicyEntitlement)
        .options(selectinload(LeavePolicyEntitlement.leave_type))
        .join(LeavePolicy)
        .where(
            LeavePolicyEntitlement.id == entitlement_id,
            LeavePolicyEntitlement.policy_id == policy_id,
            LeavePolicy.tenant_id == current_user.tenant_id,
        )
    )
    result = await db.execute(stmt)
    entitlement = result.scalar_one_or_none()
    if not entitlement:
        raise HTTPException(status_code=404, detail="Entitlement not found")

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(entitlement, key, value)

    await db.flush()
    return _entitlement_to_response(entitlement)


@router.delete("/policies/{policy_id}/entitlements/{entitlement_id}", status_code=204)
async def delete_policy_entitlement(
    policy_id: int,
    entitlement_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(CONFIG_ROLES)),
):
    stmt = (
        select(LeavePolicyEntitlement)
        .join(LeavePolicy)
        .where(
            LeavePolicyEntitlement.id == entitlement_id,
            LeavePolicyEntitlement.policy_id == policy_id,
            LeavePolicy.tenant_id == current_user.tenant_id,
        )
    )
    result = await db.execute(stmt)
    entitlement = result.scalar_one_or_none()
    if not entitlement:
        raise HTTPException(status_code=404, detail="Entitlement not found")

    await db.delete(entitlement)
    await db.flush()


@router.put("/policies/{policy_id}/entitlements", response_model=List[LeavePolicyEntitlementResponse])
async def bulk_replace_entitlements(
    policy_id: int,
    data: BulkEntitlementsRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(CONFIG_ROLES)),
):
    tenant_id = current_user.tenant_id

    policy_result = await db.execute(
        select(LeavePolicy).where(
            LeavePolicy.id == policy_id,
            LeavePolicy.tenant_id == tenant_id,
        )
    )
    if not policy_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Leave policy not found")

    existing = await db.execute(
        select(LeavePolicyEntitlement).where(LeavePolicyEntitlement.policy_id == policy_id)
    )
    for ent in existing.scalars().all():
        await db.delete(ent)
    await db.flush()

    new_entitlements = []
    seen_type_ids = set()
    for ent_data in data.entitlements:
        if ent_data.leave_type_id in seen_type_ids:
            raise HTTPException(status_code=400, detail=f"Duplicate leave type {ent_data.leave_type_id}")
        seen_type_ids.add(ent_data.leave_type_id)

        lt_result = await db.execute(
            select(LeaveType.id).where(
                LeaveType.id == ent_data.leave_type_id,
                LeaveType.tenant_id == tenant_id,
            )
        )
        if not lt_result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail=f"Leave type {ent_data.leave_type_id} not found")

        entitlement = LeavePolicyEntitlement(
            policy_id=policy_id,
            leave_type_id=ent_data.leave_type_id,
            annual_credits=ent_data.annual_credits,
            carry_over_enabled=ent_data.carry_over_enabled,
            max_carry_over_days=ent_data.max_carry_over_days,
            carry_over_expiry_months=ent_data.carry_over_expiry_months,
            cash_convertible=ent_data.cash_convertible,
            cash_conversion_rate=ent_data.cash_conversion_rate,
            requires_documentation=ent_data.requires_documentation,
            min_notice_days=ent_data.min_notice_days,
        )
        db.add(entitlement)
        new_entitlements.append(entitlement)

    await db.flush()

    ids = [e.id for e in new_entitlements]
    if ids:
        stmt = (
            select(LeavePolicyEntitlement)
            .options(selectinload(LeavePolicyEntitlement.leave_type))
            .where(LeavePolicyEntitlement.id.in_(ids))
            .order_by(LeavePolicyEntitlement.id)
        )
        result = await db.execute(stmt)
        return [_entitlement_to_response(e) for e in result.scalars().all()]
    return []


# ══════════════════════════════════════════════════════════════════════
# OVERTIME CATEGORIES
# ══════════════════════════════════════════════════════════════════════


def _ot_response(c: OvertimeCategory) -> OvertimeCategoryResponse:
    """Build response with leave_credit_type_name resolved."""
    resp = OvertimeCategoryResponse.model_validate(c)
    if c.leave_credit_type:
        resp.leave_credit_type_name = c.leave_credit_type.name
    return resp


@router.get("/overtime-categories", response_model=List[OvertimeCategoryResponse])
async def list_overtime_categories(
    include_inactive: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(OvertimeCategory)
        .options(selectinload(OvertimeCategory.leave_credit_type))
        .where(OvertimeCategory.tenant_id == current_user.tenant_id)
        .order_by(OvertimeCategory.sort_order, OvertimeCategory.id)
    )
    if not include_inactive:
        stmt = stmt.where(OvertimeCategory.is_active == True)
    result = await db.execute(stmt)
    return [_ot_response(c) for c in result.scalars().all()]


@router.post("/overtime-categories", response_model=OvertimeCategoryResponse, status_code=201)
async def create_overtime_category(
    data: OvertimeCategoryCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(CONFIG_ROLES)),
):
    existing = await db.execute(
        select(OvertimeCategory).where(
            OvertimeCategory.tenant_id == current_user.tenant_id,
            OvertimeCategory.code == data.code,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Overtime category code already exists")

    category = OvertimeCategory(
        tenant_id=current_user.tenant_id,
        code=data.code,
        name=data.name,
        description=data.description,
        multiplier_rate=data.multiplier_rate,
        compensation_type=data.compensation_type,
        leave_credit_rate=data.leave_credit_rate,
        leave_credit_type_id=data.leave_credit_type_id,
        sort_order=data.sort_order,
    )
    db.add(category)
    await db.flush()
    # Re-fetch with relationship loaded
    result = await db.execute(
        select(OvertimeCategory)
        .options(selectinload(OvertimeCategory.leave_credit_type))
        .where(OvertimeCategory.id == category.id)
    )
    category = result.scalar_one()
    return _ot_response(category)


@router.patch("/overtime-categories/{category_id}", response_model=OvertimeCategoryResponse)
async def update_overtime_category(
    category_id: int,
    data: OvertimeCategoryUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(CONFIG_ROLES)),
):
    result = await db.execute(
        select(OvertimeCategory).where(
            OvertimeCategory.id == category_id,
            OvertimeCategory.tenant_id == current_user.tenant_id,
        )
    )
    category = result.scalar_one_or_none()
    if not category:
        raise HTTPException(status_code=404, detail="Overtime category not found")

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(category, key, value)

    await db.flush()
    # Re-fetch with relationship loaded
    result = await db.execute(
        select(OvertimeCategory)
        .options(selectinload(OvertimeCategory.leave_credit_type))
        .where(OvertimeCategory.id == category.id)
    )
    category = result.scalar_one()
    return _ot_response(category)


@router.delete("/overtime-categories/{category_id}", status_code=204)
async def delete_overtime_category(
    category_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(["tenant_admin"])),
):
    result = await db.execute(
        select(OvertimeCategory).where(
            OvertimeCategory.id == category_id,
            OvertimeCategory.tenant_id == current_user.tenant_id,
        )
    )
    category = result.scalar_one_or_none()
    if not category:
        raise HTTPException(status_code=404, detail="Overtime category not found")

    category.is_active = False
    await db.flush()


# ══════════════════════════════════════════════════════════════════════
# LEAVE APPLICATIONS
# ══════════════════════════════════════════════════════════════════════


@router.get("/applications", response_model=LeaveApplicationListResponse)
async def list_leave_applications(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    leave_type: Optional[str] = None,
    employee_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = current_user.tenant_id
    is_reviewer = await _has_reviewer_role(current_user)

    stmt = (
        select(LeaveApplication)
        .options(*_load_options())
        .where(LeaveApplication.tenant_id == tenant_id)
    )
    count_stmt = select(func.count(LeaveApplication.id)).where(
        LeaveApplication.tenant_id == tenant_id
    )

    if not is_reviewer:
        stmt = stmt.where(LeaveApplication.employee_id == current_user.id)
        count_stmt = count_stmt.where(LeaveApplication.employee_id == current_user.id)
    elif employee_id:
        stmt = stmt.where(LeaveApplication.employee_id == employee_id)
        count_stmt = count_stmt.where(LeaveApplication.employee_id == employee_id)

    if status:
        stmt = stmt.where(LeaveApplication.status == status)
        count_stmt = count_stmt.where(LeaveApplication.status == status)

    if leave_type:
        stmt = stmt.where(LeaveApplication.leave_type == leave_type)
        count_stmt = count_stmt.where(LeaveApplication.leave_type == leave_type)

    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    stmt = stmt.order_by(LeaveApplication.created_at.desc())
    stmt = stmt.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(stmt)
    items = list(result.scalars().all())

    total_pages = (total + per_page - 1) // per_page if total > 0 else 1

    return LeaveApplicationListResponse(
        items=[_to_response(a) for a in items],
        total=total,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
    )


@router.post("/applications", response_model=LeaveApplicationResponse, status_code=201)
async def create_leave_application(
    data: LeaveApplicationCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _validate_leave_type(db, current_user.tenant_id, data.leave_type)

    # Whose leave this is. Everything downstream — balance rules, the policy that
    # applies, the approval chain — is a property of the employee taking the
    # leave, not of whoever typed it in, so resolve the subject up front and use
    # it consistently. Previously the body's employee_id was silently dropped
    # and the application was always filed against the caller.
    subject = current_user
    if data.employee_id is not None and data.employee_id != current_user.id:
        if not await _has_reviewer_role(current_user):
            raise HTTPException(
                status_code=403,
                detail="You can only file leave for yourself.",
            )
        result = await db.execute(
            select(User).where(
                User.id == data.employee_id,
                User.tenant_id == current_user.tenant_id,
            )
        )
        subject = result.scalar_one_or_none()
        if not subject:
            raise HTTPException(status_code=404, detail="Employee not found")

    if data.end_date < data.start_date:
        raise HTTPException(status_code=400, detail="End date must be on or after start date")

    days = _business_days(data.start_date, data.end_date)
    if days <= 0:
        raise HTTPException(status_code=400, detail="No business days in the selected range")

    # Policy-driven enforcement. Block-mode failures reject the request;
    # warn-mode failures are stored on the application for approvers to see.
    violations = await LeaveRuleService.evaluate(
        db,
        current_user.tenant_id,
        subject,
        leave_type=data.leave_type,
        start_date=data.start_date,
        end_date=data.end_date,
        days_requested=days,
        supporting_documents=data.supporting_documents,
    )
    blocking, warnings = LeaveRuleService.split(violations)
    if blocking:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "leave_rules_violated",
                "violations": [v.to_dict() for v in blocking],
            },
        )

    app = LeaveApplication(
        tenant_id=current_user.tenant_id,
        employee_id=subject.id,
        leave_type=data.leave_type,
        start_date=data.start_date,
        end_date=data.end_date,
        days_requested=days,
        reason=data.reason,
        supporting_documents=data.supporting_documents,
        rule_warnings=[w.to_dict() for w in warnings] if warnings else None,
        status="pending",
    )
    db.add(app)
    await db.flush()

    # Resolve approval chain and create steps
    policy = await LeaveService.get_policy_for_employee(
        db, current_user.tenant_id, subject.employee_type
    )

    chain = []
    if policy:
        chain = await LeaveApprovalService.resolve_approval_chain(
            db, current_user.tenant_id, subject.id, policy
        )
    else:
        # No policy covers this employee — still resolve a fallback approver
        # (line manager, then admin/HR) so the request isn't left unassigned.
        chain = await LeaveApprovalService._resolve_fallback(
            db, current_user.tenant_id, subject.id
        )

    if chain:
        await LeaveApprovalService.create_approval_steps(db, app.id, chain)
        # Notify first approver only
        first_approver_id = chain[0]["approver_id"]
        first_approver_stmt = select(User).where(User.id == first_approver_id)
        first_approver_result = await db.execute(first_approver_stmt)
        first_approver = first_approver_result.scalar_one_or_none()

        if first_approver:
            employee_name = f"{subject.first_name} {subject.last_name}"
            EmailService.fire_and_forget(
                lambda db, a=first_approver: EmailService.send_leave_request_notification(
                    db,
                    approver_email=a.email,
                    approver_name=f"{a.first_name} {a.last_name}",
                    employee_name=employee_name,
                    leave_type=data.leave_type,
                    start_date=str(data.start_date),
                    end_date=str(data.end_date),
                    days=days,
                    reason=data.reason,
                )
            )
    else:
        # Fallback: broadcast to all reviewers (legacy behavior)
        app_settings = await _get_app_settings(db, current_user.tenant_id)
        if not app_settings or app_settings.notify_on_leave_request:
            approvers = await _get_approver_emails(db, current_user.tenant_id)
            employee_name = f"{current_user.first_name} {current_user.last_name}"
            for approver in approvers:
                if approver["email"] == current_user.email:
                    continue
                EmailService.fire_and_forget(
                    lambda db, a=approver: EmailService.send_leave_request_notification(
                        db,
                        approver_email=a["email"],
                        approver_name=a["name"],
                        employee_name=employee_name,
                        leave_type=data.leave_type,
                        start_date=str(data.start_date),
                        end_date=str(data.end_date),
                        days=days,
                        reason=data.reason,
                    )
                )

    # Reload with relationships
    stmt = (
        select(LeaveApplication)
        .options(*_load_options())
        .where(LeaveApplication.id == app.id)
    )
    result = await db.execute(stmt)
    app = result.scalar_one()

    return _to_response(app)


@router.post("/applications/precheck", response_model=LeavePrecheckResponse)
async def precheck_leave_application(
    data: LeavePrecheckRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Dry-run the enforcement rules for the filing form so the UI can show
    warnings/blocks before submit. Does not create anything."""
    if data.end_date < data.start_date:
        raise HTTPException(status_code=400, detail="End date must be on or after start date")
    days = _business_days(data.start_date, data.end_date)

    violations = await LeaveRuleService.evaluate(
        db,
        current_user.tenant_id,
        current_user,
        leave_type=data.leave_type,
        start_date=data.start_date,
        end_date=data.end_date,
        days_requested=days,
        supporting_documents=data.supporting_documents,
    )
    blocking, warnings = LeaveRuleService.split(violations)
    return LeavePrecheckResponse(
        allowed=not blocking,
        days_requested=days,
        violations=[v.to_dict() for v in blocking],
        warnings=[w.to_dict() for w in warnings],
    )


@router.get("/applications/{application_id}", response_model=LeaveApplicationResponse)
async def get_leave_application(
    application_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(LeaveApplication)
        .options(*_load_options())
        .where(
            LeaveApplication.id == application_id,
            LeaveApplication.tenant_id == current_user.tenant_id,
        )
    )
    result = await db.execute(stmt)
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Leave application not found")

    is_reviewer = await _has_reviewer_role(current_user)
    if app.employee_id != current_user.id and not is_reviewer:
        raise HTTPException(status_code=403, detail="Not authorized to view this application")

    return _to_response(app)


@router.patch("/applications/{application_id}", response_model=LeaveApplicationResponse)
async def update_leave_application(
    application_id: int,
    data: LeaveApplicationUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(LeaveApplication)
        .options(*_load_options())
        .where(
            LeaveApplication.id == application_id,
            LeaveApplication.tenant_id == current_user.tenant_id,
        )
    )
    result = await db.execute(stmt)
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Leave application not found")

    if app.employee_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only edit your own applications")

    if app.status != "pending":
        raise HTTPException(status_code=400, detail="Can only edit pending applications")

    update_data = data.model_dump(exclude_unset=True)

    if "leave_type" in update_data:
        await _validate_leave_type(db, current_user.tenant_id, update_data["leave_type"])

    for key, value in update_data.items():
        setattr(app, key, value)

    if "start_date" in update_data or "end_date" in update_data:
        s = update_data.get("start_date", app.start_date)
        e = update_data.get("end_date", app.end_date)
        if e < s:
            raise HTTPException(status_code=400, detail="End date must be on or after start date")
        app.days_requested = _business_days(s, e)

    await db.flush()

    stmt = (
        select(LeaveApplication)
        .options(*_load_options())
        .where(LeaveApplication.id == app.id)
    )
    result = await db.execute(stmt)
    app = result.scalar_one()

    return _to_response(app)


@router.post("/applications/{application_id}/review", response_model=LeaveApplicationResponse)
async def review_leave_application(
    application_id: int,
    data: LeaveReviewRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(REVIEWER_ROLES)),
):
    stmt = (
        select(LeaveApplication)
        .options(*_load_options())
        .where(
            LeaveApplication.id == application_id,
            LeaveApplication.tenant_id == current_user.tenant_id,
        )
    )
    result = await db.execute(stmt)
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Leave application not found")

    if app.status != "pending":
        raise HTTPException(status_code=400, detail="This application has already been reviewed")

    # Re-check balance at approval time (it may have changed since filing) and
    # refresh the warnings snapshot shown to the approver. Never blocks.
    if data.action == "approve" and app.employee:
        fresh = await LeaveRuleService.evaluate(
            db,
            current_user.tenant_id,
            app.employee,
            leave_type=app.leave_type,
            start_date=app.start_date,
            end_date=app.end_date,
            days_requested=app.days_requested,
            supporting_documents=app.supporting_documents,
            exclude_application_id=app.id,
            rules={"insufficient_balance"},
        )
        if fresh:
            existing = [
                w for w in (app.rule_warnings or [])
                if w.get("rule") != "insufficient_balance"
            ]
            # Present balance violations as warnings regardless of policy mode.
            merged = existing + [
                {**v.to_dict(), "mode": "warn"} for v in fresh
            ]
            app.rule_warnings = merged or None

    # Check if there are approval steps (multi-step chain)
    if app.approval_steps:
        my_step = None
        for step in app.approval_steps:
            if step.approver_id == current_user.id and step.status == "pending":
                my_step = step
                break

        if not my_step:
            raise HTTPException(
                status_code=403,
                detail="You are not the current approver for this application"
            )

        for step in app.approval_steps:
            if step.step_order < my_step.step_order and step.status != "approved":
                raise HTTPException(
                    status_code=400,
                    detail="Previous approval steps have not been completed"
                )

        new_status = await LeaveApprovalService.process_step_decision(
            db, app, my_step, data.action, data.notes, current_user.id
        )

        employee = app.employee
        if employee:
            emp_name = f"{employee.first_name} {employee.last_name}"
            rev_name = f"{current_user.first_name} {current_user.last_name}"

            if new_status == "approved":
                EmailService.fire_and_forget(
                    lambda db: EmailService.send_leave_approved_email(
                        db,
                        to_email=employee.email,
                        employee_name=emp_name,
                        leave_type=app.leave_type,
                        start_date=str(app.start_date),
                        end_date=str(app.end_date),
                        reviewer_name=rev_name,
                    )
                )
            elif new_status == "rejected":
                EmailService.fire_and_forget(
                    lambda db: EmailService.send_leave_rejected_email(
                        db,
                        to_email=employee.email,
                        employee_name=emp_name,
                        leave_type=app.leave_type,
                        start_date=str(app.start_date),
                        end_date=str(app.end_date),
                        reviewer_name=rev_name,
                        reviewer_notes=data.notes or "",
                    )
                )
            elif new_status == "pending":
                next_step = await LeaveApprovalService.get_next_pending_step(db, app.id)
                if next_step and next_step.approver:
                    next_approver = next_step.approver
                    EmailService.fire_and_forget(
                        lambda db, a=next_approver: EmailService.send_leave_request_notification(
                            db,
                            approver_email=a.email,
                            approver_name=f"{a.first_name} {a.last_name}",
                            employee_name=emp_name,
                            leave_type=app.leave_type,
                            start_date=str(app.start_date),
                            end_date=str(app.end_date),
                            days=app.days_requested,
                            reason=app.reason,
                        )
                    )
    else:
        # Legacy single-step review
        new_status = "approved" if data.action == "approve" else "rejected"
        app.status = new_status
        app.reviewed_by = current_user.id
        app.reviewed_at = datetime.utcnow()
        app.reviewer_notes = data.notes

        await db.flush()

        app_settings = await _get_app_settings(db, current_user.tenant_id)
        if not app_settings or app_settings.notify_on_leave_approval:
            employee = app.employee
            if employee:
                emp_name = f"{employee.first_name} {employee.last_name}"
                rev_name = f"{current_user.first_name} {current_user.last_name}"
                if new_status == "approved":
                    EmailService.fire_and_forget(
                        lambda db: EmailService.send_leave_approved_email(
                            db,
                            to_email=employee.email,
                            employee_name=emp_name,
                            leave_type=app.leave_type,
                            start_date=str(app.start_date),
                            end_date=str(app.end_date),
                            reviewer_name=rev_name,
                        )
                    )
                else:
                    EmailService.fire_and_forget(
                        lambda db: EmailService.send_leave_rejected_email(
                            db,
                            to_email=employee.email,
                            employee_name=emp_name,
                            leave_type=app.leave_type,
                            start_date=str(app.start_date),
                            end_date=str(app.end_date),
                            reviewer_name=rev_name,
                            reviewer_notes=data.notes or "",
                        )
                    )

    # Overlay leave on schedule when approved
    if new_status == "approved":
        overlay_conflicts = await ScheduleService.overlay_leave_on_shifts(
            db,
            tenant_id=current_user.tenant_id,
            employee_id=app.employee_id,
            leave_application_id=app.id,
            leave_type=app.leave_type,
            start_date=app.start_date,
            end_date=app.end_date,
        )
        # Record dates that were already claimed by a different approved leave
        # so reviewers can see the overlap instead of it being silently lost.
        if overlay_conflicts:
            existing = list(app.rule_warnings or [])
            existing.append({
                "rule": "schedule_overlay_conflict",
                "mode": "warn",
                "message": (
                    "Some dates already carried a different approved leave and "
                    "were left unchanged."
                ),
                "details": {"dates": [d.isoformat() for d in overlay_conflicts]},
            })
            app.rule_warnings = existing
            await db.flush()

    # Reload with relationships
    stmt = (
        select(LeaveApplication)
        .options(*_load_options())
        .where(LeaveApplication.id == app.id)
    )
    result = await db.execute(stmt)
    app = result.scalar_one()

    return _to_response(app)


@router.post("/applications/{application_id}/cancel", response_model=LeaveApplicationResponse)
async def cancel_leave_application(
    application_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cancel own pending leave application."""
    stmt = (
        select(LeaveApplication)
        .options(*_load_options())
        .where(
            LeaveApplication.id == application_id,
            LeaveApplication.tenant_id == current_user.tenant_id,
        )
    )
    result = await db.execute(stmt)
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Leave application not found")

    if app.employee_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only cancel your own applications")

    if app.status != "pending":
        raise HTTPException(status_code=400, detail="Can only cancel pending applications")

    app.status = "cancelled"
    await db.flush()

    stmt = (
        select(LeaveApplication)
        .options(*_load_options())
        .where(LeaveApplication.id == app.id)
    )
    result = await db.execute(stmt)
    app = result.scalar_one()

    return _to_response(app)


@router.post("/applications/{application_id}/revoke", response_model=LeaveApplicationResponse)
async def revoke_leave_application(
    application_id: int,
    data: LeaveRevokeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(REVIEWER_ROLES)),
):
    """Undo the approval of an already-approved leave application.

    Without this, approval was terminal — `/cancel`, `PATCH` and `/review` all
    guard on `status == "pending"` — so an approval made in error could not be
    withdrawn and an employee returning early could not be put back on the
    roster.

    Both actions revert the schedule overlay. They differ in where the
    application lands: "unapprove" returns it to `pending` so the approval chain
    can run again, "reject" refuses it outright.

    Leave balances are derived from application status by `LeaveService`, so the
    days are released by the status change itself — there is no credit ledger to
    adjust and therefore no double-refund to guard against.
    """
    from app.services.notification_service import NotificationService

    stmt = (
        select(LeaveApplication)
        .options(*_load_options())
        .where(
            LeaveApplication.id == application_id,
            LeaveApplication.tenant_id == current_user.tenant_id,
        )
    )
    result = await db.execute(stmt)
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Leave application not found")

    if app.status != "approved":
        raise HTTPException(
            status_code=400,
            detail=f"Only an approved application can be revoked (this one is {app.status})",
        )

    # Put the employee back on the roster before changing status, so a failure
    # here does not leave an application that says "pending" while the schedule
    # still shows leave.
    reverted = await ScheduleService.revert_leave_overlay(
        db, tenant_id=current_user.tenant_id, leave_application_id=app.id
    )

    new_status = "pending" if data.action == "unapprove" else "rejected"
    app.status = new_status
    app.reviewer_notes = data.notes

    if data.action == "unapprove":
        # Back into the queue: clear the decision and reopen every step so the
        # chain can be walked again from the start.
        app.reviewed_by = None
        app.reviewed_at = None
        for step in (app.approval_steps or []):
            step.status = "pending"
            step.decided_at = None
            step.notes = None
    else:
        app.reviewed_by = current_user.id
        app.reviewed_at = datetime.utcnow()

    await db.flush()

    reviewer_name = f"{current_user.first_name} {current_user.last_name}".strip()
    if data.action == "unapprove":
        title = "Your approved leave was returned for review"
        body = (
            f"{reviewer_name} withdrew the approval of your "
            f"{app.leave_type.replace('_', ' ')} leave for {app.start_date} to "
            f"{app.end_date}. It is pending review again. Reason: {data.notes}"
        )
    else:
        title = "Your approved leave was rejected"
        body = (
            f"{reviewer_name} rejected your previously approved "
            f"{app.leave_type.replace('_', ' ')} leave for {app.start_date} to "
            f"{app.end_date}. Reason: {data.notes}"
        )
    await NotificationService.notify(
        db,
        current_user.tenant_id,
        app.employee_id,
        type="leave_revoked",
        title=title,
        body=body,
        action_type="leave_application",
        action_ref_id=app.id,
    )

    # Record what happened to the schedule so a reviewer can see it rather than
    # having to diff the grid.
    warnings = list(app.rule_warnings or [])
    # mode is "warn" because that is the only non-blocking value rule_warnings
    # accepts, and it matches the existing "schedule_overlay_conflict" entry.
    warnings.append({
        "rule": "leave_overlay_reverted",
        "mode": "warn",
        "message": (
            f"Approval revoked; schedule restored: {reverted['restored']} shift(s) "
            f"returned to their previous status, {reverted['deleted']} generated "
            f"shift(s) removed."
        ),
        "details": reverted,
    })
    app.rule_warnings = warnings
    await db.flush()

    stmt = (
        select(LeaveApplication)
        .options(*_load_options())
        .where(LeaveApplication.id == app.id)
    )
    result = await db.execute(stmt)
    app = result.scalar_one()

    return _to_response(app)


# ══════════════════════════════════════════════════════════════════════
# APPROVAL CHAIN PREVIEW + PENDING APPROVALS
# ══════════════════════════════════════════════════════════════════════


@router.get("/my-approval-chain", response_model=ApprovalChainPreviewResponse)
async def get_my_approval_chain(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Preview who will approve my leave based on current policy."""
    policy = await LeaveService.get_policy_for_employee(
        db, current_user.tenant_id, current_user.employee_type
    )

    if not policy:
        return ApprovalChainPreviewResponse(chain=[])

    chain = await LeaveApprovalService.resolve_approval_chain(
        db, current_user.tenant_id, current_user.id, policy
    )

    return ApprovalChainPreviewResponse(
        chain=[
            ApprovalChainPreviewItem(
                approver_id=item["approver_id"],
                approver_name=item["approver_name"],
                step_order=item["step_order"],
                source=item["source"],
            )
            for item in chain
        ]
    )


@router.get("/approval-chain-preview", response_model=ApprovalChainPreviewResponse)
async def preview_approval_chain(
    employee_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(CONFIG_ROLES)),
):
    """Admin-facing chain tester: resolve the approval chain for any employee so
    configurators can see exactly who would approve a request and why."""
    employee = (await db.execute(
        select(User).where(
            User.id == employee_id, User.tenant_id == current_user.tenant_id
        )
    )).scalar_one_or_none()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    policy = await LeaveService.get_policy_for_employee(
        db, current_user.tenant_id, employee.employee_type
    )
    if not policy:
        return ApprovalChainPreviewResponse(chain=[])

    chain = await LeaveApprovalService.resolve_approval_chain(
        db, current_user.tenant_id, employee.id, policy
    )
    return ApprovalChainPreviewResponse(
        chain=[
            ApprovalChainPreviewItem(
                approver_id=item["approver_id"],
                approver_name=item["approver_name"],
                step_order=item["step_order"],
                source=item["source"],
            )
            for item in chain
        ]
    )


@router.get("/pending-approvals", response_model=LeaveApplicationListResponse)
async def get_pending_approvals(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(REVIEWER_ROLES)),
):
    """Get leave applications where I am the current pending step approver."""
    applications, total = await LeaveApprovalService.get_pending_for_approver(
        db, current_user.tenant_id, current_user.id, page, per_page
    )

    total_pages = (total + per_page - 1) // per_page if total > 0 else 1

    return LeaveApplicationListResponse(
        items=[_to_response(a) for a in applications],
        total=total,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
    )


@router.get("/team-stats", response_model=TeamStatsResponse)
async def get_team_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(REVIEWER_ROLES)),
):
    """Get leave statistics scoped to supervised employees."""
    is_admin = await _has_config_role(current_user)
    stats = await LeaveApprovalService.get_team_stats(
        db, current_user.tenant_id, current_user.id, is_admin
    )
    return TeamStatsResponse(**stats)


# ══════════════════════════════════════════════════════════════════════
# APPROVER ASSIGNMENTS
# ══════════════════════════════════════════════════════════════════════


@router.get("/approver-assignments", response_model=List[LeaveApproverAssignmentResponse])
async def list_approver_assignments(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(CONFIG_ROLES)),
):
    stmt = (
        select(LeaveApproverAssignment)
        .options(
            selectinload(LeaveApproverAssignment.employee),
            selectinload(LeaveApproverAssignment.org_node),
            selectinload(LeaveApproverAssignment.approver),
        )
        .where(LeaveApproverAssignment.tenant_id == current_user.tenant_id)
        .order_by(LeaveApproverAssignment.priority, LeaveApproverAssignment.step_order, LeaveApproverAssignment.id)
    )
    result = await db.execute(stmt)
    assignments = result.scalars().all()

    return [
        LeaveApproverAssignmentResponse(
            id=a.id,
            employee_id=a.employee_id,
            employee_name=(
                f"{a.employee.first_name} {a.employee.last_name}" if a.employee else None
            ),
            org_node_id=a.org_node_id,
            org_node_name=a.org_node.name if a.org_node else None,
            approver_id=a.approver_id,
            approver_name=(
                f"{a.approver.first_name} {a.approver.last_name}" if a.approver else ""
            ),
            approver_role=a.approver_role,
            step_order=a.step_order,
            priority=a.priority,
            cascade=a.cascade,
            exclude=a.exclude,
            is_active=a.is_active,
        )
        for a in assignments
    ]


@router.post("/approver-assignments", response_model=LeaveApproverAssignmentResponse, status_code=201)
async def create_approver_assignment(
    data: LeaveApproverAssignmentCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(CONFIG_ROLES)),
):
    tenant_id = current_user.tenant_id

    if data.approver_id:
        approver_result = await db.execute(
            select(User).where(User.id == data.approver_id, User.tenant_id == tenant_id)
        )
        approver = approver_result.scalar_one_or_none()
        if not approver:
            raise HTTPException(status_code=400, detail="Approver user not found")
    elif not data.exclude and not data.approver_role:
        raise HTTPException(status_code=400, detail="Approver or approver role is required for non-exclude rules")

    if data.employee_id:
        emp_result = await db.execute(
            select(User).where(User.id == data.employee_id, User.tenant_id == tenant_id)
        )
        if not emp_result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Employee not found")

    if data.org_node_id:
        node_result = await db.execute(
            select(OrgNode).where(
                OrgNode.id == data.org_node_id, OrgNode.tenant_id == tenant_id
            )
        )
        if not node_result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Org node not found")

    assignment = LeaveApproverAssignment(
        tenant_id=tenant_id,
        employee_id=data.employee_id,
        org_node_id=data.org_node_id,
        approver_id=data.approver_id if not data.approver_role else None,
        approver_role=data.approver_role,
        step_order=data.step_order,
        priority=data.priority,
        cascade=data.cascade if data.org_node_id else False,
        exclude=data.exclude if data.employee_id else False,
    )
    db.add(assignment)
    await db.flush()

    stmt = (
        select(LeaveApproverAssignment)
        .options(
            selectinload(LeaveApproverAssignment.employee),
            selectinload(LeaveApproverAssignment.org_node),
            selectinload(LeaveApproverAssignment.approver),
        )
        .where(LeaveApproverAssignment.id == assignment.id)
    )
    result = await db.execute(stmt)
    a = result.scalar_one()

    return LeaveApproverAssignmentResponse(
        id=a.id,
        employee_id=a.employee_id,
        employee_name=(
            f"{a.employee.first_name} {a.employee.last_name}" if a.employee else None
        ),
        org_node_id=a.org_node_id,
        org_node_name=a.org_node.name if a.org_node else None,
        approver_id=a.approver_id,
        approver_name=(
            f"{a.approver.first_name} {a.approver.last_name}" if a.approver else ""
        ),
        approver_role=a.approver_role,
        step_order=a.step_order,
        priority=a.priority,
        cascade=a.cascade,
        exclude=a.exclude,
        is_active=a.is_active,
    )


@router.patch("/approver-assignments/{assignment_id}", response_model=LeaveApproverAssignmentResponse)
async def update_approver_assignment(
    assignment_id: int,
    data: LeaveApproverAssignmentUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(CONFIG_ROLES)),
):
    stmt = (
        select(LeaveApproverAssignment)
        .options(
            selectinload(LeaveApproverAssignment.employee),
            selectinload(LeaveApproverAssignment.org_node),
            selectinload(LeaveApproverAssignment.approver),
        )
        .where(
            LeaveApproverAssignment.id == assignment_id,
            LeaveApproverAssignment.tenant_id == current_user.tenant_id,
        )
    )
    result = await db.execute(stmt)
    a = result.scalar_one_or_none()
    if not a:
        raise HTTPException(status_code=404, detail="Assignment not found")

    update_data = data.model_dump(exclude_unset=True)

    if "approver_id" in update_data and update_data["approver_id"]:
        approver_result = await db.execute(
            select(User).where(
                User.id == update_data["approver_id"],
                User.tenant_id == current_user.tenant_id,
            )
        )
        if not approver_result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Approver user not found")

    # If setting approver_role, clear approver_id; if setting approver_id, clear approver_role
    if "approver_role" in update_data and update_data["approver_role"]:
        update_data["approver_id"] = None
    elif "approver_id" in update_data and update_data["approver_id"]:
        update_data["approver_role"] = None

    for key, value in update_data.items():
        setattr(a, key, value)

    await db.flush()

    stmt = (
        select(LeaveApproverAssignment)
        .options(
            selectinload(LeaveApproverAssignment.employee),
            selectinload(LeaveApproverAssignment.org_node),
            selectinload(LeaveApproverAssignment.approver),
        )
        .where(LeaveApproverAssignment.id == a.id)
    )
    result = await db.execute(stmt)
    a = result.scalar_one()

    return LeaveApproverAssignmentResponse(
        id=a.id,
        employee_id=a.employee_id,
        employee_name=(
            f"{a.employee.first_name} {a.employee.last_name}" if a.employee else None
        ),
        org_node_id=a.org_node_id,
        org_node_name=a.org_node.name if a.org_node else None,
        approver_id=a.approver_id,
        approver_name=(
            f"{a.approver.first_name} {a.approver.last_name}" if a.approver else ""
        ),
        approver_role=a.approver_role,
        step_order=a.step_order,
        priority=a.priority,
        cascade=a.cascade,
        exclude=a.exclude,
        is_active=a.is_active,
    )


@router.delete("/approver-assignments/{assignment_id}", status_code=204)
async def delete_approver_assignment(
    assignment_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(CONFIG_ROLES)),
):
    result = await db.execute(
        select(LeaveApproverAssignment).where(
            LeaveApproverAssignment.id == assignment_id,
            LeaveApproverAssignment.tenant_id == current_user.tenant_id,
        )
    )
    a = result.scalar_one_or_none()
    if not a:
        raise HTTPException(status_code=404, detail="Assignment not found")

    await db.delete(a)
    await db.flush()


@router.put("/approver-assignments/reorder")
async def reorder_approver_assignments(
    ordered_ids: List[int],
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(CONFIG_ROLES)),
):
    """Reorder approval rules by setting priority based on list position.
    Accepts an ordered list of assignment IDs (top = highest priority)."""
    tenant_id = current_user.tenant_id

    for idx, rule_id in enumerate(ordered_ids):
        new_priority = (idx + 1) * 10  # 10, 20, 30, ...
        result = await db.execute(
            select(LeaveApproverAssignment).where(
                LeaveApproverAssignment.id == rule_id,
                LeaveApproverAssignment.tenant_id == tenant_id,
            )
        )
        assignment = result.scalar_one_or_none()
        if assignment:
            assignment.priority = new_priority

    await db.flush()
    return {"status": "ok", "count": len(ordered_ids)}


# ══════════════════════════════════════════════════════════════════════
# LEAVE BALANCE (policy-aware)
# ══════════════════════════════════════════════════════════════════════


def _balance_set_to_response(balance_set) -> LeaveBalanceResponse:
    return LeaveBalanceResponse(
        employee_id=balance_set.employee_id,
        policy_name=balance_set.policy_name,
        accrual_method=balance_set.accrual_method,
        pool_type=balance_set.pool_type,
        balances=[
            LeaveBalanceItem(
                leave_type=b.leave_type,
                leave_type_name=b.leave_type_name,
                total_days=b.total_days,
                used_days=b.used_days,
                pending_days=b.pending_days,
                available_days=b.available_days,
            )
            for b in balance_set.balances
        ],
    )


@router.get("/balance", response_model=LeaveBalanceResponse)
async def get_my_leave_balance(
    year: Optional[int] = None,
    employee_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Leave balance for the caller, or for `employee_id` when the caller is
    authorised (admin/HR, or the employee's supervisor)."""
    target = current_user
    if employee_id is not None and employee_id != current_user.id:
        roles = set(current_user.role_codes)
        is_privileged = bool({"tenant_admin", "hr"} & roles)
        if not is_privileged:
            supervised = await LeaveApprovalService.get_supervised_employee_ids(
                db, current_user.tenant_id, current_user.id
            )
            if employee_id not in supervised:
                raise HTTPException(
                    status_code=403,
                    detail="Not authorised to view this employee's balance.",
                )
        target = await UserService.get_user_by_id(
            db, employee_id, current_user.tenant_id
        )
        if not target:
            raise HTTPException(status_code=404, detail="Employee not found")

    app_settings = await _get_app_settings(db, current_user.tenant_id)
    default_days = app_settings.default_leave_days if app_settings else 15

    balance_set = await LeaveService.compute_balances(
        db,
        current_user.tenant_id,
        target,
        year=year,
        default_days=float(default_days),
    )
    return _balance_set_to_response(balance_set)
