"""Leave: configuration, requests, the approval flow and balances.

Access follows the permission contract (permission_service): approving a step
is governed by the approver chain; the matrix governs reading other people's
leave (leave:view), filing for someone else (leave:create), configuration and
stepping in on a stuck approval (leave:edit) and deleting configuration
(leave:delete). Scope (access_scope) limits a non-full-scope role to the
employees in the units they head or deputise. Self-service (your own requests,
balance and approval chain) is never gated.
"""

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.middleware.auth import get_current_user, require_leave_config
from app.models.leave import (
    LeaveApplication,
    LeaveApprovalEvent,
    LeaveApproverAssignment,
    LeaveApproverRuleStep,
    LeavePolicy,
    LeavePolicyEntitlement,
    LeaveType,
    OvertimeCategory,
)
from app.models.org_hierarchy import OrgNode
from app.models.role import LeaveApprovalStep
from app.models.settings import AppSettings, ShiftStatusType
from app.models.user import User
from app.schemas.leave import (
    ApprovalChainPreviewItem,
    ApprovalChainPreviewResponse,
    ApproverCheckResponse,
    ApproverRuleStepOut,
    BulkEntitlementsRequest,
    LeaveActions,
    LeaveApplicationCreate,
    LeaveApplicationListResponse,
    LeaveApplicationResponse,
    LeaveApplicationUpdate,
    LeaveApprovalEventResponse,
    LeaveApprovalStepResponse,
    LeaveApproverAssignmentCreate,
    LeaveApproverAssignmentResponse,
    LeaveApproverAssignmentUpdate,
    LeaveBalanceItem,
    LeaveBalanceResponse,
    LeaveOverrideRequest,
    LeavePolicyCreate,
    LeavePolicyEntitlementCreate,
    LeavePolicyEntitlementResponse,
    LeavePolicyEntitlementUpdate,
    LeavePolicyResponse,
    LeavePolicyUpdate,
    LeavePrecheckRequest,
    LeavePrecheckResponse,
    LeaveReassignRequest,
    LeaveReviewRequest,
    LeaveRevokeRequest,
    LeaveSelfApproveRequest,
    LeaveTypeCreate,
    LeaveTypeResponse,
    LeaveTypeUpdate,
    OvertimeCategoryCreate,
    OvertimeCategoryResponse,
    OvertimeCategoryUpdate,
    PolicyCompleteness,
    TeamStatsResponse,
)
from app.services.access_scope import assert_manages, assert_operational_session
from app.services.permission_service import ADMIN_ROLE, PermissionService
from app.services.leave_access import (
    LeaveViewer,
    approver_check,
    assert_can_be_approver,
    ensure_reviewer_role,
    full_name,
    has_permission,
    leave_editors,
)
from app.services.leave_approval_service import (
    SOURCE_SELF,
    STEP_APPROVED,
    STEP_PENDING,
    STEP_REJECTED,
    LeaveApprovalService,
    record_event,
    set_status,
)
from app.services.leave_days_service import count_leave_days, days_by_year
from app.services.leave_notify_service import (
    NOBODY_CAN_APPROVE_EMPLOYEE,
    TO_APPROVER,
    TO_EMPLOYEE,
    LeaveNotifier,
)
from app.services.leave_rule_service import LeaveRuleService, violations_message
from app.services.leave_service import LeaveService
from app.services.schedule_service import ScheduleService
from app.services.settings_service import SettingsService
from app.services.user_service import UserService
from app.utils.timeutil import utcnow

router = APIRouter(prefix="/leave", tags=["Leave"])


# ── Helpers ─────────────────────────────────────────────────────────


def _step_to_response(step: LeaveApprovalStep, employee_id: Optional[int] = None) -> LeaveApprovalStepResponse:
    return LeaveApprovalStepResponse(
        id=step.id,
        step_order=step.step_order,
        approver_id=step.approver_id,
        approver_name=full_name(step.approver),
        status=step.status,
        decided_at=step.decided_at,
        notes=step.notes,
        is_self=step.approver_id is not None and step.approver_id == employee_id,
    )


def _event_to_response(ev: LeaveApprovalEvent) -> LeaveApprovalEventResponse:
    return LeaveApprovalEventResponse(
        id=ev.id,
        action=ev.action,
        actor_id=ev.actor_id,
        actor_name=full_name(ev.actor) or None,
        from_approver_id=ev.from_approver_id,
        from_approver_name=full_name(ev.from_approver) or None,
        to_approver_id=ev.to_approver_id,
        to_approver_name=full_name(ev.to_approver) or None,
        reason=ev.reason,
        created_at=ev.created_at,
    )


class _Ctx:
    """Per-request facts needed to work out each request's action flags."""

    def __init__(self, viewer: LeaveViewer, type_names: dict, lone: Optional[bool] = None):
        self.viewer = viewer
        self.type_names = type_names
        # True when nobody but the caller holds leave:edit, i.e. the caller's
        # own request can only be self-approved. Computed on first need.
        self.lone = lone


async def _ctx(db: AsyncSession, user: User) -> _Ctx:
    viewer = await LeaveViewer.build(db, user)
    names = {
        r[0]: r[1]
        for r in (
            await db.execute(
                select(LeaveType.code, LeaveType.name).where(LeaveType.tenant_id == user.tenant_id)
            )
        ).all()
    }
    return _Ctx(viewer, names)


async def _no_other_approver(db: AsyncSession, user: User) -> bool:
    return not await leave_editors(db, user.tenant_id, exclude={user.id})


async def _actions(db: AsyncSession, app: LeaveApplication, ctx: _Ctx) -> LeaveActions:
    v = ctx.viewer
    me = v.user.id
    own = app.employee_id == me
    step = LeaveApprovalService.current_step(app) if app.status == "pending" else None
    self_step = LeaveApprovalService.is_self_step(app, step)
    can_self = False
    if own and self_step:
        if ctx.lone is None:
            ctx.lone = await _no_other_approver(db, v.user)
        can_self = ctx.lone
    decided_by_me = any(
        s.approver_id == me and s.status == STEP_APPROVED for s in app.approval_steps or []
    )
    return LeaveActions(
        can_edit=own and app.status == "pending",
        can_cancel=own and app.status == "pending",
        can_review=bool(step and step.approver_id == me and not own),
        can_self_approve=can_self,
        can_override=app.status == "pending" and v.can_override(app),
        can_reassign=app.status == "pending" and step is not None and v.can_override(app),
        can_revoke=app.status == "approved" and (decided_by_me or v.can_override(app)),
    )


async def _to_response(
    db: AsyncSession, app: LeaveApplication, ctx: Optional[_Ctx] = None
) -> LeaveApplicationResponse:
    """Convert a LeaveApplication ORM model to response schema."""
    steps = [_step_to_response(s, app.employee_id) for s in (app.approval_steps or [])]
    current = LeaveApprovalService.current_step(app) if app.status == "pending" else None
    return LeaveApplicationResponse(
        id=app.id,
        employee_id=app.employee_id,
        employee_name=full_name(app.employee),
        leave_type=app.leave_type,
        leave_type_name=(ctx.type_names.get(app.leave_type) if ctx else None),
        start_date=app.start_date,
        end_date=app.end_date,
        days_requested=app.days_requested,
        half_day=app.half_day,
        day_breakdown=app.day_breakdown or None,
        reason=app.reason,
        supporting_documents=app.supporting_documents,
        status=app.status,
        reviewed_by=app.reviewed_by,
        reviewer_name=full_name(app.reviewer) or None,
        reviewed_at=app.reviewed_at,
        reviewer_notes=app.reviewer_notes,
        rule_warnings=app.rule_warnings or None,
        approval_steps=steps,
        current_step=current.step_order if current else None,
        events=[_event_to_response(e) for e in (app.events or [])],
        actions=await _actions(db, app, ctx) if ctx else LeaveActions(),
        created_at=app.created_at,
        updated_at=app.updated_at,
    )


def _load_options():
    return [
        selectinload(LeaveApplication.employee),
        selectinload(LeaveApplication.reviewer),
        selectinload(LeaveApplication.approval_steps).selectinload(LeaveApprovalStep.approver),
        selectinload(LeaveApplication.events).selectinload(LeaveApprovalEvent.actor),
        selectinload(LeaveApplication.events).selectinload(LeaveApprovalEvent.from_approver),
        selectinload(LeaveApplication.events).selectinload(LeaveApprovalEvent.to_approver),
    ]


def _expire_cached(db: AsyncSession, cls, pk: int, attrs: list) -> None:
    """Make the next query reload `attrs` of an object this session already
    holds. A handler that added steps or ledger rows must see them in the
    response. (populate_existing would do it too, but it also resets the
    unloaded relationships of every User it touches, including the caller's
    roles, which then cannot be lazy-loaded in async code.)"""
    for obj in list(db.identity_map.values()):
        if isinstance(obj, cls) and obj.id == pk:
            db.expire(obj, attrs)


async def _load_app(db: AsyncSession, tenant_id, application_id: int) -> LeaveApplication:
    await db.flush()
    _expire_cached(db, LeaveApplication, application_id, ["approval_steps", "events"])
    app = (
        await db.execute(
            select(LeaveApplication)
            .options(*_load_options())
            .where(
                LeaveApplication.id == application_id,
                LeaveApplication.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Leave application not found")
    if await LeaveApprovalService.ensure_steps(db, app):
        return await _load_app(db, tenant_id, application_id)
    return app


async def _get_app_settings(db: AsyncSession, tenant_id) -> Optional[AppSettings]:
    result = await db.execute(
        select(AppSettings).where(AppSettings.tenant_id == tenant_id)
    )
    return result.scalar_one_or_none()


async def _default_days(db: AsyncSession, tenant_id) -> float:
    s = await _get_app_settings(db, tenant_id)
    return float(s.default_leave_days) if s and s.default_leave_days is not None else 15.0


def _rules_error(blocking) -> HTTPException:
    """422 whose detail carries a sentence for people and the list for the form.

    It used to be {"code", "violations"} alone, and the client printed the
    object as JSON to the employee."""
    return HTTPException(
        status_code=422,
        detail={
            "code": "leave_rules_violated",
            "message": violations_message(blocking),
            "violations": [v.to_dict() for v in blocking],
        },
    )


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
        # Was missing, so every policy edit read back "no limit" and saved it.
        max_consecutive_days=e.max_consecutive_days,
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
        has_approval_path=True,  # every request now resolves at least one step
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


def _new_entitlement(policy_id: int, d: LeavePolicyEntitlementCreate) -> LeavePolicyEntitlement:
    return LeavePolicyEntitlement(
        policy_id=policy_id,
        leave_type_id=d.leave_type_id,
        annual_credits=d.annual_credits,
        carry_over_enabled=d.carry_over_enabled,
        max_carry_over_days=d.max_carry_over_days,
        carry_over_expiry_months=d.carry_over_expiry_months,
        cash_convertible=d.cash_convertible,
        cash_conversion_rate=d.cash_conversion_rate,
        requires_documentation=d.requires_documentation,
        min_notice_days=d.min_notice_days,
        max_consecutive_days=d.max_consecutive_days,
    )


async def _validate_leave_type(db: AsyncSession, tenant_id, leave_type_code: str):
    """Validate that a leave type code exists for this tenant."""
    result = await db.execute(
        select(LeaveType.id).where(
            LeaveType.tenant_id == tenant_id,
            LeaveType.code == leave_type_code,
            LeaveType.is_active == True,  # noqa: E712
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"Invalid leave type: {leave_type_code}")


async def _half_day_status(db: AsyncSession, tenant_id, leave_type: str) -> Optional[str]:
    """A shift status for half-day leave, if the tenant has one.

    Half-day leave is shown on the grid with its own status when the tenant has
    defined one ("<type>_half_day", "half_day_leave" or "half_day"); otherwise
    the day carries the leave type and the request records the half day."""
    for code in (f"{leave_type}_half_day", "half_day_leave", "half_day"):
        hit = (
            await db.execute(
                select(ShiftStatusType.code).where(
                    ShiftStatusType.tenant_id == tenant_id,
                    ShiftStatusType.code == code,
                    ShiftStatusType.is_active == True,  # noqa: E712
                )
            )
        ).scalar_one_or_none()
        if hit:
            return hit
    return None


def _counted_ranges(app: LeaveApplication) -> list[tuple[date, date]]:
    """The contiguous date ranges of a request that actually consume leave.

    Rest days, days off and holidays inside a leave are left alone on the
    roster: they were never going to be worked and they cost no credit."""
    if not app.day_breakdown:
        return [(app.start_date, app.end_date)]
    ranges: list[list[date]] = []
    prev: Optional[date] = None
    for d in app.day_breakdown:
        if not d.get("days"):
            prev = None
            continue
        day = date.fromisoformat(str(d["date"]))
        if prev is not None and (day - prev).days == 1:
            ranges[-1][1] = day
        else:
            ranges.append([day, day])
        prev = day
    return [(a, b) for a, b in ranges]


async def _apply_overlay(db: AsyncSession, app: LeaveApplication) -> None:
    status_code = app.leave_type
    if app.half_day:
        status_code = await _half_day_status(db, app.tenant_id, app.leave_type) or app.leave_type
    conflicts: list[date] = []
    for a, b in _counted_ranges(app):
        conflicts += await ScheduleService.overlay_leave_on_shifts(
            db,
            tenant_id=app.tenant_id,
            employee_id=app.employee_id,
            leave_application_id=app.id,
            leave_type=status_code,
            start_date=a,
            end_date=b,
        )
    # Record dates that were already claimed by a different approved leave
    # so reviewers can see the overlap instead of it being silently lost.
    if conflicts:
        existing = list(app.rule_warnings or [])
        existing.append({
            "rule": "schedule_overlay_conflict",
            "mode": "warn",
            "message": (
                "Some dates already carried a different approved leave and "
                "were left unchanged."
            ),
            "details": {"dates": [d.isoformat() for d in conflicts]},
        })
        app.rule_warnings = existing
        await db.flush()


async def _refresh_balance_warning(db: AsyncSession, app: LeaveApplication, tenant_id) -> None:
    """Re-check the balance at approval time (it may have changed since
    filing) and refresh the warning shown to approvers. Never blocks."""
    if not app.employee:
        return
    fresh = await LeaveRuleService.evaluate(
        db,
        tenant_id,
        app.employee,
        leave_type=app.leave_type,
        start_date=app.start_date,
        end_date=app.end_date,
        days_requested=app.days_requested,
        supporting_documents=app.supporting_documents,
        exclude_application_id=app.id,
        rules={"insufficient_balance"},
        day_breakdown=app.day_breakdown,
        advisory=True,
        default_days=await _default_days(db, tenant_id),
    )
    existing = [w for w in (app.rule_warnings or []) if w.get("rule") != "insufficient_balance"]
    merged = existing + [{**v.to_dict(), "mode": "warn"} for v in fresh]
    app.rule_warnings = merged or None


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
        stmt = stmt.where(LeaveType.is_active == True)  # noqa: E712
    result = await db.execute(stmt)
    return [LeaveTypeResponse.model_validate(lt) for lt in result.scalars().all()]


@router.post("/types", response_model=LeaveTypeResponse, status_code=201)
async def create_leave_type(
    data: LeaveTypeCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_leave_config("edit")),
):
    existing = await db.execute(
        select(LeaveType).where(
            LeaveType.tenant_id == current_user.tenant_id,
            LeaveType.code == data.code,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="A leave type with this code already exists.")

    leave_type = LeaveType(
        tenant_id=current_user.tenant_id,
        code=data.code,
        name=data.name,
        description=data.description,
        export_code=data.export_code,
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
    _=Depends(require_leave_config("edit")),
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
    _=Depends(require_leave_config("delete")),
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
    _=Depends(require_leave_config("edit")),
):
    tenant_id = current_user.tenant_id

    existing = await db.execute(
        select(LeavePolicy).where(
            LeavePolicy.tenant_id == tenant_id,
            LeavePolicy.name == data.name,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="A policy with this name already exists.")

    if data.is_default:
        from sqlalchemy import update
        await db.execute(
            update(LeavePolicy)
            .where(LeavePolicy.tenant_id == tenant_id, LeavePolicy.is_default == True)  # noqa: E712
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
            db.add(_new_entitlement(policy.id, ent_data))
        await db.flush()

    policy = (
        await db.execute(
            select(LeavePolicy).options(*_policy_load_options()).where(LeavePolicy.id == policy.id)
        )
    ).scalar_one()
    return _policy_to_response(policy)


@router.patch("/policies/{policy_id}", response_model=LeavePolicyResponse)
async def update_leave_policy(
    policy_id: int,
    data: LeavePolicyUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_leave_config("edit")),
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
                LeavePolicy.is_default == True,  # noqa: E712
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
            raise HTTPException(status_code=400, detail="A policy with this name already exists.")

    for key, value in update_data.items():
        setattr(policy, key, value)

    await db.flush()

    policy = (
        await db.execute(
            select(LeavePolicy)
            .options(*_policy_load_options())
            .where(LeavePolicy.id == policy.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    return _policy_to_response(policy)


@router.delete("/policies/{policy_id}", status_code=204)
async def delete_leave_policy(
    policy_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_leave_config("delete")),
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
    _=Depends(require_leave_config("edit")),
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
    _=Depends(require_leave_config("edit")),
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
    if not lt_result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Leave type not found")

    dup = await db.execute(
        select(LeavePolicyEntitlement).where(
            LeavePolicyEntitlement.policy_id == policy_id,
            LeavePolicyEntitlement.leave_type_id == data.leave_type_id,
        )
    )
    if dup.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="This policy already covers that leave type.")

    entitlement = _new_entitlement(policy_id, data)
    db.add(entitlement)
    await db.flush()

    entitlement = (
        await db.execute(
            select(LeavePolicyEntitlement)
            .options(selectinload(LeavePolicyEntitlement.leave_type))
            .where(LeavePolicyEntitlement.id == entitlement.id)
        )
    ).scalar_one()
    return _entitlement_to_response(entitlement)


@router.patch("/policies/{policy_id}/entitlements/{entitlement_id}", response_model=LeavePolicyEntitlementResponse)
async def update_policy_entitlement(
    policy_id: int,
    entitlement_id: int,
    data: LeavePolicyEntitlementUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_leave_config("edit")),
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
    entitlement = (await db.execute(stmt)).scalar_one_or_none()
    if not entitlement:
        raise HTTPException(status_code=404, detail="Entitlement not found")

    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(entitlement, key, value)

    await db.flush()
    return _entitlement_to_response(entitlement)


@router.delete("/policies/{policy_id}/entitlements/{entitlement_id}", status_code=204)
async def delete_policy_entitlement(
    policy_id: int,
    entitlement_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_leave_config("edit")),
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
    entitlement = (await db.execute(stmt)).scalar_one_or_none()
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
    _=Depends(require_leave_config("edit")),
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

        # max_consecutive_days used to be dropped here, so saving a policy
        # silently removed every per-type limit.
        entitlement = _new_entitlement(policy_id, ent_data)
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
        return [_entitlement_to_response(e) for e in (await db.execute(stmt)).scalars().all()]
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
        stmt = stmt.where(OvertimeCategory.is_active == True)  # noqa: E712
    result = await db.execute(stmt)
    return [_ot_response(c) for c in result.scalars().all()]


@router.post("/overtime-categories", response_model=OvertimeCategoryResponse, status_code=201)
async def create_overtime_category(
    data: OvertimeCategoryCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_leave_config("edit")),
):
    existing = await db.execute(
        select(OvertimeCategory).where(
            OvertimeCategory.tenant_id == current_user.tenant_id,
            OvertimeCategory.code == data.code,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="An overtime category with this code already exists.")

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
    category = (
        await db.execute(
            select(OvertimeCategory)
            .options(selectinload(OvertimeCategory.leave_credit_type))
            .where(OvertimeCategory.id == category.id)
        )
    ).scalar_one()
    return _ot_response(category)


@router.patch("/overtime-categories/{category_id}", response_model=OvertimeCategoryResponse)
async def update_overtime_category(
    category_id: int,
    data: OvertimeCategoryUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_leave_config("edit")),
):
    category = (
        await db.execute(
            select(OvertimeCategory).where(
                OvertimeCategory.id == category_id,
                OvertimeCategory.tenant_id == current_user.tenant_id,
            )
        )
    ).scalar_one_or_none()
    if not category:
        raise HTTPException(status_code=404, detail="Overtime category not found")

    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(category, key, value)

    await db.flush()
    category = (
        await db.execute(
            select(OvertimeCategory)
            .options(selectinload(OvertimeCategory.leave_credit_type))
            .where(OvertimeCategory.id == category.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    return _ot_response(category)


@router.delete("/overtime-categories/{category_id}", status_code=204)
async def delete_overtime_category(
    category_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_leave_config("delete")),
):
    category = (
        await db.execute(
            select(OvertimeCategory).where(
                OvertimeCategory.id == category_id,
                OvertimeCategory.tenant_id == current_user.tenant_id,
            )
        )
    ).scalar_one_or_none()
    if not category:
        raise HTTPException(status_code=404, detail="Overtime category not found")

    category.is_active = False
    await db.flush()


# ══════════════════════════════════════════════════════════════════════
# LEAVE APPLICATIONS
# ══════════════════════════════════════════════════════════════════════


def _scope_filter(viewer: LeaveViewer, scope: str):
    """Which requests a list shows.

    mine    the caller's own requests only, whatever roles they hold. A
            reviewer's "My Leave" used to list the whole company.
    team    other people's requests the caller may see: those where they are
            on the approval chain, plus (with leave:view) everyone in their
            scope.
    review  requests the caller can act on after approval: where they are on
            the chain, plus (with leave:edit) everyone in their scope.
    all     mine + team.
    """
    me = viewer.user.id
    mine = LeaveApplication.employee_id == me
    if scope == "mine":
        return mine
    chain = LeaveApplication.id.in_(
        select(LeaveApprovalStep.leave_application_id).where(LeaveApprovalStep.approver_id == me)
    )
    parts = [chain]
    allowed = viewer.can_edit if scope == "review" else viewer.can_view
    if allowed:
        parts.append(
            true() if viewer.managed is None else LeaveApplication.employee_id.in_(viewer.managed)
        )
    others = and_(LeaveApplication.employee_id != me, or_(*parts))
    if scope == "all":
        return or_(mine, others)
    return others


@router.get("/applications", response_model=LeaveApplicationListResponse)
async def list_leave_applications(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    leave_type: Optional[str] = None,
    employee_id: Optional[int] = None,
    scope: str = Query("all", pattern="^(mine|team|review|all)$"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = current_user.tenant_id
    if scope != "mine":
        # Other people's leave is review, done from the regular dashboard.
        assert_operational_session(current_user)
    ctx = await _ctx(db, current_user)

    cond = and_(LeaveApplication.tenant_id == tenant_id, _scope_filter(ctx.viewer, scope))
    if employee_id:
        cond = and_(cond, LeaveApplication.employee_id == employee_id)
    if status:
        cond = and_(cond, LeaveApplication.status == status)
    if leave_type:
        cond = and_(cond, LeaveApplication.leave_type == leave_type)

    total = (await db.execute(select(func.count(LeaveApplication.id)).where(cond))).scalar() or 0
    items = list(
        (
            await db.execute(
                select(LeaveApplication)
                .options(*_load_options())
                .where(cond)
                .order_by(LeaveApplication.created_at.desc(), LeaveApplication.id.desc())
                .offset((page - 1) * per_page)
                .limit(per_page)
            )
        ).scalars().all()
    )
    total_pages = (total + per_page - 1) // per_page if total > 0 else 1

    return LeaveApplicationListResponse(
        items=[await _to_response(db, a, ctx) for a in items],
        total=total,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
    )


async def _subject_for(db: AsyncSession, current_user: User, employee_id: Optional[int]) -> User:
    """Whose leave this is. Filing for someone else needs leave:create and the
    employee must be inside the caller's scope."""
    if employee_id is None or employee_id == current_user.id:
        return current_user
    assert_operational_session(current_user)
    if not await has_permission(db, current_user, "leave", "create"):
        raise HTTPException(status_code=403, detail="You can only file leave for yourself.")
    await assert_manages(db, current_user, [employee_id], "leave")
    subject = (
        await db.execute(
            select(User).where(User.id == employee_id, User.tenant_id == current_user.tenant_id)
        )
    ).scalar_one_or_none()
    if not subject:
        raise HTTPException(status_code=404, detail="Employee not found")
    if not subject.is_active:
        raise HTTPException(status_code=400, detail=f"{full_name(subject)} is no longer active.")
    return subject


def _check_dates(start: date, end: date, half_day: Optional[str]) -> None:
    if end < start:
        raise HTTPException(status_code=400, detail="End date must be on or after start date")
    if half_day and start != end:
        raise HTTPException(
            status_code=400,
            detail="A half day can only be requested for a single day. Set the same start and end date.",
        )


def _nothing_to_take(breakdown: list, whose: str) -> str:
    reasons = sorted({d["label"] for d in breakdown})[:3]
    return (
        f"None of these days is a working day for {whose}, so there is no leave to take. "
        + ("Those days are: " + "; ".join(reasons) + "." if reasons else "")
    ).strip()


@router.post("/applications", response_model=LeaveApplicationResponse, status_code=201)
async def create_leave_application(
    data: LeaveApplicationCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = current_user.tenant_id
    await _validate_leave_type(db, tenant_id, data.leave_type)

    # Whose leave this is. Everything downstream — the roster the days are
    # counted from, balance rules, the policy that applies, the approval chain
    # and the notifications — is a property of the employee taking the leave,
    # not of whoever typed it in.
    subject = await _subject_for(db, current_user, data.employee_id)
    _check_dates(data.start_date, data.end_date, data.half_day)

    count = await count_leave_days(
        db, tenant_id, subject.id, data.start_date, data.end_date, half_day=data.half_day
    )
    if count.days <= 0:
        whose = "you" if subject.id == current_user.id else full_name(subject)
        raise HTTPException(status_code=400, detail=_nothing_to_take(count.breakdown, whose))

    # Policy-driven enforcement. Block-mode failures reject the request;
    # warn-mode failures (and the advisory overlap/balance checks) are stored
    # on the application for approvers to see.
    violations = await LeaveRuleService.evaluate(
        db,
        tenant_id,
        subject,
        leave_type=data.leave_type,
        start_date=data.start_date,
        end_date=data.end_date,
        days_requested=count.days,
        supporting_documents=data.supporting_documents,
        day_breakdown=count.breakdown,
        advisory=True,
        default_days=await _default_days(db, tenant_id),
    )
    blocking, warnings = LeaveRuleService.split(violations)
    if blocking:
        raise _rules_error(blocking)

    app = LeaveApplication(
        tenant_id=tenant_id,
        employee_id=subject.id,
        leave_type=data.leave_type,
        start_date=data.start_date,
        end_date=data.end_date,
        days_requested=count.days,
        half_day=data.half_day,
        day_breakdown=count.breakdown,
        reason=data.reason,
        supporting_documents=data.supporting_documents,
        rule_warnings=[w.to_dict() for w in warnings] if warnings else None,
        status="pending",
    )
    db.add(app)
    await db.flush()

    chain = await LeaveApprovalService.resolve_chain_for_employee(db, tenant_id, subject)
    await LeaveApprovalService.create_approval_steps(
        db, app.id, chain, tenant_id=tenant_id, employee_id=subject.id, granted_by=current_user.id,
    )

    app = await _load_app(db, tenant_id, app.id)
    notifier = LeaveNotifier(db, tenant_id)
    first = chain[0] if chain else None
    if first is None:
        # Nobody can approve leave in this company: the request waits, the
        # employee is told why, and the administrators what to do about it.
        await notifier.send(
            [subject.id], audience=TO_EMPLOYEE, kind="leave_no_approver",
            title="Nobody can approve your leave yet",
            body=NOBODY_CAN_APPROVE_EMPLOYEE,
            app=app,
        )
        await notifier.nobody_can_approve(app)
    elif first["source"] == SOURCE_SELF:
        await notifier.send(
            [subject.id], audience=TO_EMPLOYEE, kind="leave_self_approval",
            title="Nobody else can approve your leave",
            body=(
                "There is no other active person who can approve leave in your company, "
                "so this request is waiting for you to self-approve it. The self-approval "
                "is recorded with your reason."
            ),
            app=app,
        )
    else:
        await notifier.request_waiting(app, first["approver_id"])
    if subject.id != current_user.id:
        await notifier.send(
            [subject.id], audience=TO_EMPLOYEE, kind="leave_filed_for_you",
            title="Leave was filed for you",
            body=f"{full_name(current_user)} filed {await notifier.describe(app)} on your behalf.",
            app=app,
        )

    return await _to_response(db, app, await _ctx(db, current_user))


@router.post("/applications/precheck", response_model=LeavePrecheckResponse)
async def precheck_leave_application(
    data: LeavePrecheckRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Preview a request without creating it: the days it would consume, day by
    day, and the rules it would break, so the form can show both before the
    employee submits."""
    tenant_id = current_user.tenant_id
    subject = await _subject_for(db, current_user, data.employee_id)
    _check_dates(data.start_date, data.end_date, data.half_day)
    exclude_id = None
    if data.application_id is not None:
        own = await db.get(LeaveApplication, data.application_id)
        if own is not None and own.tenant_id == tenant_id and own.employee_id == subject.id:
            exclude_id = own.id

    count = await count_leave_days(
        db, tenant_id, subject.id, data.start_date, data.end_date,
        half_day=data.half_day, application_id=exclude_id,
    )
    problem = None
    violations = []
    if count.days <= 0:
        whose = "you" if subject.id == current_user.id else full_name(subject)
        problem = _nothing_to_take(count.breakdown, whose)
    else:
        violations = await LeaveRuleService.evaluate(
            db,
            tenant_id,
            subject,
            leave_type=data.leave_type,
            start_date=data.start_date,
            end_date=data.end_date,
            days_requested=count.days,
            supporting_documents=data.supporting_documents,
            exclude_application_id=exclude_id,
            day_breakdown=count.breakdown,
            advisory=True,
            default_days=await _default_days(db, tenant_id),
        )
    blocking, warnings = LeaveRuleService.split(violations)
    return LeavePrecheckResponse(
        allowed=not blocking and problem is None,
        days_requested=count.days,
        violations=[v.to_dict() for v in blocking],
        warnings=[w.to_dict() for w in warnings],
        day_breakdown=count.breakdown,
        days_by_year=count.by_year,
        problem=problem,
    )


@router.get("/applications/{application_id}", response_model=LeaveApplicationResponse)
async def get_leave_application(
    application_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    app = await _load_app(db, current_user.tenant_id, application_id)
    ctx = await _ctx(db, current_user)
    if not ctx.viewer.can_read(app):
        raise HTTPException(status_code=403, detail="You do not have access to this leave request.")
    return await _to_response(db, app, ctx)


@router.patch("/applications/{application_id}", response_model=LeaveApplicationResponse)
async def update_leave_application(
    application_id: int,
    data: LeaveApplicationUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Change your own pending request.

    Any change re-runs every leave rule against the new dates and type. If an
    approver had already approved a step, those approvals were given for a
    different request: every step goes back to pending and the first approver
    is told. An approved request cannot be edited at all — it is already on the
    roster and in the balance; cancel it via the approver (unapprove) instead.
    """
    tenant_id = current_user.tenant_id
    app = await _load_app(db, tenant_id, application_id)

    if app.employee_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only edit your own leave requests.")
    if app.status == "approved":
        raise HTTPException(
            status_code=400,
            detail=(
                "This leave is already approved, so it cannot be changed. Ask your approver "
                "to withdraw the approval, or file a new request for the new dates."
            ),
        )
    if app.status != "pending":
        raise HTTPException(status_code=400, detail=f"This request is {app.status} and can no longer be changed.")

    update_data = data.model_dump(exclude_unset=True)
    leave_type = update_data.get("leave_type", app.leave_type)
    start = update_data.get("start_date", app.start_date)
    end = update_data.get("end_date", app.end_date)
    half_day = update_data["half_day"] if "half_day" in update_data else app.half_day
    docs = update_data.get("supporting_documents", app.supporting_documents)
    if "leave_type" in update_data:
        await _validate_leave_type(db, tenant_id, leave_type)
    _check_dates(start, end, half_day)

    count = await count_leave_days(db, tenant_id, app.employee_id, start, end, half_day=half_day, application_id=app.id)
    if count.days <= 0:
        raise HTTPException(status_code=400, detail=_nothing_to_take(count.breakdown, "you"))

    violations = await LeaveRuleService.evaluate(
        db, tenant_id, app.employee,
        leave_type=leave_type, start_date=start, end_date=end,
        days_requested=count.days, supporting_documents=docs,
        exclude_application_id=app.id, day_breakdown=count.breakdown,
        advisory=True, default_days=await _default_days(db, tenant_id),
    )
    blocking, warnings = LeaveRuleService.split(violations)
    if blocking:
        raise _rules_error(blocking)

    app.leave_type = leave_type
    app.start_date = start
    app.end_date = end
    app.half_day = half_day
    app.supporting_documents = docs
    if "reason" in update_data:
        app.reason = update_data["reason"]
    app.days_requested = count.days
    app.day_breakdown = count.breakdown
    # Warnings are re-derived from scratch; keep only the history entries the
    # rule engine does not produce (e.g. a previous revert of the roster).
    kept = [
        w for w in (app.rule_warnings or [])
        if w.get("rule") in ("leave_overlay_reverted",)
    ]
    app.rule_warnings = (kept + [w.to_dict() for w in warnings]) or None

    had_approvals = any(s.status == STEP_APPROVED for s in app.approval_steps or [])
    for s in app.approval_steps or []:
        s.status = STEP_PENDING
        s.decided_at = None
        s.notes = None
    if had_approvals:
        await record_event(
            db, app, "steps_reset", actor_id=current_user.id,
            reason="The employee changed the request after it had been approved at an earlier step.",
        )
    await db.flush()

    app = await _load_app(db, tenant_id, app.id)
    step = LeaveApprovalService.current_step(app)
    if step is not None and not LeaveApprovalService.is_self_step(app, step):
        lead = (
            "They changed it after it had been approved at an earlier step, so it needs approving again."
            if had_approvals
            else "They changed the request."
        )
        await LeaveNotifier(db, tenant_id).request_waiting(app, step.approver_id, kind="leave_updated", lead=lead)
    return await _to_response(db, app, await _ctx(db, current_user))


@router.post("/applications/{application_id}/review", response_model=LeaveApplicationResponse)
async def review_leave_application(
    application_id: int,
    data: LeaveReviewRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Approve or reject the step waiting for you.

    Governed by the approver chain, not by a role: whoever the current step
    names may act on it, and nobody else may (an admin who needs to step in
    uses override, which asks for a reason). Nobody approves their own leave.
    Decided from the regular dashboard, never an admin session.
    """
    assert_operational_session(current_user)
    tenant_id = current_user.tenant_id
    app = await _load_app(db, tenant_id, application_id)
    if app.status != "pending":
        raise HTTPException(status_code=400, detail=f"This request is already {app.status}.")

    step = LeaveApprovalService.current_step(app)
    if app.employee_id == current_user.id:
        raise HTTPException(
            status_code=403,
            detail=(
                "You cannot approve your own leave."
                + (" Nobody else can approve leave in your company, so use Self-approve on your request."
                   if LeaveApprovalService.is_self_step(app, step) else "")
            ),
        )
    if step is None or step.approver_id != current_user.id:
        later = any(
            s.approver_id == current_user.id and s.status == STEP_PENDING
            for s in app.approval_steps or []
        )
        if later:
            raise HTTPException(
                status_code=400,
                detail="An earlier approver has not decided yet. You will be notified when it is your turn.",
            )
        raise HTTPException(
            status_code=403,
            detail="You are not the approver for the step this request is waiting on.",
        )

    if data.action == "approve":
        await _refresh_balance_warning(db, app, tenant_id)

    new_status = await LeaveApprovalService.process_step_decision(
        db, app, step, data.action, data.notes, current_user.id, actor=current_user
    )

    notifier = LeaveNotifier(db, tenant_id)
    me = full_name(current_user)
    if new_status == "approved":
        await _apply_overlay(db, app)
        await notifier.mark_resolved(app)
        await notifier.decided(app, approved=True, by=me, notes=data.notes)
    elif new_status == "rejected":
        await notifier.mark_resolved(app)
        await notifier.decided(app, approved=False, by=me, notes=data.notes)
    else:
        app = await _load_app(db, tenant_id, app.id)
        nxt = LeaveApprovalService.current_step(app)
        if nxt is not None:
            await notifier.request_waiting(
                app, nxt.approver_id, kind="leave_request",
                lead=f"Step {step.step_order} was approved by {me}.",
            )

    app = await _load_app(db, tenant_id, app.id)
    return await _to_response(db, app, await _ctx(db, current_user))


@router.post("/applications/{application_id}/self-approve", response_model=LeaveApplicationResponse)
async def self_approve_leave_application(
    application_id: int,
    data: LeaveSelfApproveRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Approve your own request when nobody else can.

    Only possible when the request's step is the requester's own (the chain
    found nobody else) and, checked again now, there is still no other active
    person with leave:edit. The reason is recorded on the request and in the
    audit log. This replaces the old silent path where a sole admin could
    approve their own leave through the API with no trace.
    """
    tenant_id = current_user.tenant_id
    app = await _load_app(db, tenant_id, application_id)
    if app.employee_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only self-approve your own request.")
    if current_user.in_admin_portal:
        # Admin mode (session_portal): the admin portal is for acting on other
        # people. Self-approval stays the employee's own recorded escape hatch.
        raise HTTPException(
            status_code=403,
            detail=(
                "Someone else has to approve your own leave. If nobody else can, "
                "self-approve it from your employee dashboard."
            ),
        )
    if app.status != "pending":
        raise HTTPException(status_code=400, detail=f"This request is already {app.status}.")
    step = LeaveApprovalService.current_step(app)
    if not LeaveApprovalService.is_self_step(app, step):
        raise HTTPException(
            status_code=400,
            detail="This request has an approver. It will be decided by them.",
        )
    others = await leave_editors(db, tenant_id, exclude={current_user.id})
    if others:
        _uid, first, last, _code = others[0]
        raise HTTPException(
            status_code=409,
            detail=(
                f"{first} {last} can now approve leave, so this request cannot be self-approved. "
                "Ask them to approve it; an administrator can reassign it to them."
            ),
        )

    step.status = STEP_APPROVED
    step.decided_at = utcnow()
    step.notes = f"Self-approved (no other approver exists): {data.reason}"
    app.reviewed_by = current_user.id
    app.reviewed_at = utcnow()
    app.reviewer_notes = step.notes
    await record_event(db, app, "self_approve", actor_id=current_user.id, step=step, reason=data.reason)
    await set_status(db, app, "approved", actor=current_user)
    await _apply_overlay(db, app)

    app = await _load_app(db, tenant_id, app.id)
    return await _to_response(db, app, await _ctx(db, current_user))


@router.post("/applications/{application_id}/override", response_model=LeaveApplicationResponse)
async def override_leave_application(
    application_id: int,
    data: LeaveOverrideRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Approve or reject a pending request without waiting for its approver.

    For leave:edit holders over the employee (HR by default; not
    administrators, who configure leave but do not review it) when an approver
    is away, has left, or is simply stuck. The remaining steps are closed, the
    reason is shown on the request and audit-logged, and both the employee and
    the bypassed approver are told.
    """
    assert_operational_session(current_user)
    tenant_id = current_user.tenant_id
    app = await _load_app(db, tenant_id, application_id)
    ctx = await _ctx(db, current_user)
    if app.employee_id == current_user.id:
        raise HTTPException(status_code=403, detail="You cannot override a decision on your own leave.")
    if not ctx.viewer.can_edit:
        raise HTTPException(
            status_code=403,
            detail="Only HR, or someone with leave edit rights over this employee, can override an approval.",
        )
    await assert_manages(db, current_user, [app.employee_id], "leave")
    if app.status != "pending":
        raise HTTPException(
            status_code=400,
            detail=(
                "Only a pending request can be overridden."
                + (" To reverse an approval, use Unapprove or Disapprove." if app.status == "approved" else "")
            ),
        )

    step = LeaveApprovalService.current_step(app)
    bypassed = step.approver_id if step is not None else None
    me = full_name(current_user)
    note = f"{'Approved' if data.action == 'approve' else 'Rejected'} by {me} (override): {data.reason}"
    if step is not None:
        step.status = STEP_APPROVED if data.action == "approve" else STEP_REJECTED
        step.decided_at = utcnow()
        step.notes = note
    LeaveApprovalService.skip_open_steps(app, note=f"Not needed: {note}")
    app.reviewed_by = current_user.id
    app.reviewed_at = utcnow()
    app.reviewer_notes = note
    await record_event(
        db, app, f"override_{data.action}", actor_id=current_user.id, step=step,
        from_approver_id=bypassed, reason=data.reason,
    )
    new_status = "approved" if data.action == "approve" else "rejected"
    await set_status(db, app, new_status, actor=current_user)
    if new_status == "approved":
        await _apply_overlay(db, app)

    notifier = LeaveNotifier(db, tenant_id)
    await notifier.mark_resolved(app)
    await notifier.decided(app, approved=new_status == "approved", by=f"{me} (override)", notes=data.reason)
    if bypassed and bypassed != current_user.id:
        employee = full_name(app.employee)
        await notifier.send(
            [bypassed], audience=TO_APPROVER, kind="leave_override",
            title=f"{me} decided a leave request that was waiting for you",
            body=(
                f"{me} {new_status} {employee}'s {await notifier.describe(app)} without waiting "
                f"for your step. Reason: {data.reason}"
            ),
            app=app,
        )

    app = await _load_app(db, tenant_id, app.id)
    return await _to_response(db, app, await _ctx(db, current_user))


@router.post("/applications/{application_id}/reassign", response_model=LeaveApplicationResponse)
async def reassign_leave_approver(
    application_id: int,
    data: LeaveReassignRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Hand a pending step to a different approver.

    The new approver must be active and cannot be the employee. If they have
    no reviewer role they are given Leave Approver, so the request never lands
    with someone who cannot open it.
    """
    assert_operational_session(current_user)
    tenant_id = current_user.tenant_id
    app = await _load_app(db, tenant_id, application_id)
    if app.employee_id == current_user.id:
        raise HTTPException(status_code=403, detail="You cannot reassign the approver of your own leave.")
    if not await has_permission(db, current_user, "leave", "edit"):
        raise HTTPException(
            status_code=403,
            detail="Only HR, or someone with leave edit rights over this employee, can reassign an approver.",
        )
    await assert_manages(db, current_user, [app.employee_id], "leave")
    if app.status != "pending":
        raise HTTPException(status_code=400, detail=f"This request is already {app.status}.")

    if data.step_id is not None:
        step = next((s for s in app.approval_steps or [] if s.id == data.step_id), None)
        if step is None or step.status != STEP_PENDING:
            raise HTTPException(status_code=400, detail="That step is not waiting for a decision.")
    else:
        step = LeaveApprovalService.current_step(app)
        if step is None:
            raise HTTPException(status_code=400, detail="No step of this request is waiting for a decision.")
    if data.approver_id == app.employee_id:
        raise HTTPException(status_code=400, detail="An employee cannot approve their own leave.")
    if data.approver_id == step.approver_id:
        raise HTTPException(status_code=400, detail="That person is already the approver for this step.")
    await assert_can_be_approver(db, tenant_id, data.approver_id)

    old = step.approver_id
    await LeaveApprovalService.reassign_step(
        db, app, step, data.approver_id, actor_id=current_user.id, reason=data.reason,
    )

    app = await _load_app(db, tenant_id, app.id)
    notifier = LeaveNotifier(db, tenant_id)
    me = full_name(current_user)
    new_user = await db.get(User, data.approver_id)
    if LeaveApprovalService.current_step(app) is step:
        await notifier.request_waiting(
            app, data.approver_id, kind="leave_reassigned",
            lead=f"{me} reassigned this request to you. Reason: {data.reason}.",
        )
    await notifier.send(
        [app.employee_id], audience=TO_EMPLOYEE, kind="leave_reassigned",
        title="Your leave request has a new approver",
        body=f"{me} passed your {await notifier.describe(app)} to {full_name(new_user)}. Reason: {data.reason}",
        app=app,
    )
    if old and old != current_user.id:
        await notifier.send(
            [old], audience=TO_APPROVER, kind="leave_reassigned_away",
            title="A leave request was reassigned from you",
            body=(
                f"{me} gave {full_name(app.employee)}'s {await notifier.describe(app)} to "
                f"{full_name(new_user)}. You no longer need to act on it."
            ),
            app=app,
        )
    return await _to_response(db, app, await _ctx(db, current_user))


@router.post("/applications/{application_id}/cancel", response_model=LeaveApplicationResponse)
async def cancel_leave_application(
    application_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cancel your own pending leave request."""
    tenant_id = current_user.tenant_id
    app = await _load_app(db, tenant_id, application_id)

    if app.employee_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only cancel your own leave requests.")
    if app.status != "pending":
        raise HTTPException(
            status_code=400,
            detail=(
                "Only a pending request can be cancelled."
                + (" This one is approved: ask your approver to withdraw the approval." if app.status == "approved" else "")
            ),
        )

    step = LeaveApprovalService.current_step(app)
    LeaveApprovalService.skip_open_steps(app, note="Cancelled by the employee.")
    await set_status(db, app, "cancelled", actor=current_user)

    notifier = LeaveNotifier(db, tenant_id)
    await notifier.mark_resolved(app)
    if step is not None and not LeaveApprovalService.is_self_step(app, step):
        await notifier.send(
            [step.approver_id], audience=TO_APPROVER, kind="leave_cancelled",
            title=f"{full_name(current_user)} cancelled a leave request",
            body=f"{full_name(current_user)} cancelled {await notifier.describe(app)}. You no longer need to act on it.",
            app=app,
        )

    app = await _load_app(db, tenant_id, app.id)
    return await _to_response(db, app, await _ctx(db, current_user))


@router.post("/applications/{application_id}/revoke", response_model=LeaveApplicationResponse)
async def revoke_leave_application(
    application_id: int,
    data: LeaveRevokeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Undo the approval of an already-approved leave application.

    Without this, approval was terminal — `/cancel`, `PATCH` and `/review` all
    guard on `status == "pending"` — so an approval made in error could not be
    withdrawn and an employee returning early could not be put back on the
    roster.

    Who may: an approver on this request's chain, or someone with leave:edit
    over the employee (recorded as an override). It used to be any reviewer in
    the company.

    Both actions revert the schedule overlay. They differ in where the
    application lands: "unapprove" returns it to `pending` so the approval chain
    can run again, "reject" refuses it outright.

    Leave balances are derived from application status by `LeaveService`, so the
    days are released by the status change itself — there is no credit ledger to
    adjust and therefore no double-refund to guard against.
    """
    assert_operational_session(current_user)
    tenant_id = current_user.tenant_id
    app = await _load_app(db, tenant_id, application_id)
    if app.status != "approved":
        raise HTTPException(
            status_code=400,
            detail=f"Only an approved request can be revoked (this one is {app.status}).",
        )

    ctx = await _ctx(db, current_user)
    my_step = next(
        (s for s in app.approval_steps or [] if s.approver_id == current_user.id and s.status == STEP_APPROVED),
        None,
    )
    as_override = my_step is None
    if as_override:
        if not ctx.viewer.can_override(app):
            raise HTTPException(
                status_code=403,
                detail="Only an approver of this request, or someone who can edit leave settings, can reverse it.",
            )
        await assert_manages(db, current_user, [app.employee_id], "leave")

    # Put the employee back on the roster before changing status, so a failure
    # here does not leave an application that says "pending" while the schedule
    # still shows leave.
    reverted = await ScheduleService.revert_leave_overlay(
        db, tenant_id=tenant_id, leave_application_id=app.id
    )

    me = full_name(current_user)
    app.reviewer_notes = data.notes
    chain_people = [s.approver_id for s in app.approval_steps or [] if s.approver_id]
    if data.action == "unapprove":
        # Back into the queue: clear the decision and reopen every step so the
        # chain can be walked again from the start.
        app.reviewed_by = None
        app.reviewed_at = None
        for step in (app.approval_steps or []):
            step.status = STEP_PENDING
            step.decided_at = None
            step.notes = None
        new_status = "pending"
    else:
        # The step that reverses the decision is marked rejected, so the chain
        # no longer reads "approved" on a request that is not. An override
        # marks the last step, as it stands in for the final say.
        target = my_step or sorted(app.approval_steps or [], key=lambda s: s.step_order)[-1]
        target.status = STEP_REJECTED
        target.decided_at = utcnow()
        target.notes = f"Rejected after approval by {me}: {data.notes}"
        app.reviewed_by = current_user.id
        app.reviewed_at = utcnow()
        new_status = "rejected"

    if as_override:
        await record_event(
            db, app, "override_revoke", actor_id=current_user.id,
            reason=f"{data.action}: {data.notes}",
        )
    await set_status(db, app, new_status, actor=current_user)

    # Record what happened to the schedule so a reviewer can see it rather than
    # having to diff the grid. mode is "warn" because that is the only
    # non-blocking value rule_warnings accepts.
    warnings = list(app.rule_warnings or [])
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

    notifier = LeaveNotifier(db, tenant_id)
    what = await notifier.describe(app)
    if data.action == "unapprove":
        title = "Your approved leave was returned for review"
        body = f"{me} withdrew the approval of your {what}. It is pending review again. Reason: {data.notes}"
    else:
        title = "Your approved leave was rejected"
        body = f"{me} rejected your previously approved {what}. Reason: {data.notes}"
    await notifier.send([app.employee_id], audience=TO_EMPLOYEE, kind="leave_revoked", title=title, body=body, app=app)
    others = [p for p in chain_people if p not in (current_user.id, app.employee_id)]
    if others:
        await notifier.send(
            others, audience=TO_APPROVER, kind="leave_revoked",
            title=f"An approved leave was {'returned for review' if data.action == 'unapprove' else 'rejected'}",
            body=(
                f"{me} {'withdrew the approval of' if data.action == 'unapprove' else 'rejected'} "
                f"{full_name(app.employee)}'s {what}. Reason: {data.notes}"
                + (" It is back in the approval queue." if data.action == "unapprove" else "")
            ),
            app=app,
        )

    app = await _load_app(db, tenant_id, app.id)
    return await _to_response(db, app, await _ctx(db, current_user))


# ══════════════════════════════════════════════════════════════════════
# APPROVAL CHAIN PREVIEW + PENDING APPROVALS
# ══════════════════════════════════════════════════════════════════════


def _chain_response(chain: list) -> ApprovalChainPreviewResponse:
    return ApprovalChainPreviewResponse(
        nobody_can_approve=not chain,
        message=NOBODY_CAN_APPROVE_EMPLOYEE if not chain else None,
        chain=[
            ApprovalChainPreviewItem(
                approver_id=item["approver_id"],
                approver_name=item["approver_name"],
                step_order=item["step_order"],
                source=item["source"],
                is_deputy=bool(item.get("is_deputy")),
                node_name=item.get("node_name"),
            )
            for item in chain
        ]
    )


@router.get("/my-approval-chain", response_model=ApprovalChainPreviewResponse)
async def get_my_approval_chain(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Who will approve my leave: exactly what filing now would produce,
    fallback and self-approval included."""
    chain = await LeaveApprovalService.resolve_chain_for_employee(
        db, current_user.tenant_id, current_user
    )
    return _chain_response(chain)


@router.get("/approval-chain-preview", response_model=ApprovalChainPreviewResponse)
async def preview_approval_chain(
    employee_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_leave_config("view")),
):
    """Admin-facing chain tester: resolve the approval chain for any employee
    in the caller's scope, the same way filing does. Configuration, so an
    administrator tests any employee; anyone else within their leave scope."""
    if not current_user.has_role(ADMIN_ROLE):
        await assert_manages(db, current_user, [employee_id], "leave")
    employee = (await db.execute(
        select(User).where(User.id == employee_id, User.tenant_id == current_user.tenant_id)
    )).scalar_one_or_none()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    chain = await LeaveApprovalService.resolve_chain_for_employee(
        db, current_user.tenant_id, employee
    )
    return _chain_response(chain)


@router.get("/approver-check", response_model=ApproverCheckResponse)
async def check_approver(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """What naming `user_id` as an approver will do, so the screen can say so
    before the admin saves (inactive: refused; no reviewer role: granted)."""
    if not (
        await PermissionService.leave_config_allowed(db, current_user, "edit")
        or await has_permission(db, current_user, "organization", "edit")
    ):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return ApproverCheckResponse(**await approver_check(db, current_user.tenant_id, user_id))


@router.get("/pending-approvals", response_model=LeaveApplicationListResponse)
async def get_pending_approvals(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Requests waiting for the caller's decision. Open to everyone: whoever a
    step names may act on it (it is empty for anyone who approves nothing).
    Not in an admin session: approving is done from the regular dashboard."""
    assert_operational_session(current_user)
    applications, total = await LeaveApprovalService.get_pending_for_approver(
        db, current_user.tenant_id, current_user.id, page, per_page
    )
    ctx = await _ctx(db, current_user)
    total_pages = (total + per_page - 1) // per_page if total > 0 else 1
    return LeaveApplicationListResponse(
        items=[await _to_response(db, a, ctx) for a in applications],
        total=total,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
    )


@router.get("/team-stats", response_model=TeamStatsResponse)
async def get_team_stats(
    year: Optional[int] = Query(None, ge=2000, le=2100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """A year's statistics (default: this year) over exactly the requests Team
    Overview lists."""
    assert_operational_session(current_user)
    viewer = await LeaveViewer.build(db, current_user)
    stats = await LeaveApprovalService.get_team_stats(
        db, current_user.tenant_id, _scope_filter(viewer, "team"), year=year
    )
    return TeamStatsResponse(**stats)


# ══════════════════════════════════════════════════════════════════════
# APPROVER ASSIGNMENTS (approval rules)
# ══════════════════════════════════════════════════════════════════════


def _assignment_options():
    return [
        selectinload(LeaveApproverAssignment.employee),
        selectinload(LeaveApproverAssignment.org_node),
        selectinload(LeaveApproverAssignment.approver),
        selectinload(LeaveApproverAssignment.steps).selectinload(LeaveApproverRuleStep.approver),
    ]


def _assignment_to_response(a: LeaveApproverAssignment, granted: Optional[list] = None) -> LeaveApproverAssignmentResponse:
    steps = [
        ApproverRuleStepOut(
            step_order=s.step_order,
            approver_id=s.approver_id,
            approver_name=full_name(s.approver) or None,
            approver_role=s.approver_role,
            approver_active=bool(s.approver.is_active) if s.approver is not None else True,
        )
        for s in (a.steps or [])
    ]
    if not steps and not a.exclude and (a.approver_id or a.approver_role):
        steps = [ApproverRuleStepOut(
            step_order=1,
            approver_id=a.approver_id,
            approver_name=full_name(a.approver) or None,
            approver_role=a.approver_role,
            approver_active=bool(a.approver.is_active) if a.approver is not None else True,
        )]
    return LeaveApproverAssignmentResponse(
        id=a.id,
        employee_id=a.employee_id,
        employee_name=full_name(a.employee) or None,
        org_node_id=a.org_node_id,
        org_node_name=a.org_node.name if a.org_node else None,
        approver_id=a.approver_id,
        approver_name=full_name(a.approver),
        approver_role=a.approver_role,
        steps=steps,
        step_order=a.step_order,
        priority=a.priority,
        cascade=a.cascade,
        exclude=a.exclude,
        is_active=a.is_active,
        deactivated_reason=a.deactivated_reason,
        granted_role_to=granted or [],
    )


async def _load_assignment(db: AsyncSession, tenant_id, assignment_id: int) -> LeaveApproverAssignment:
    await db.flush()
    _expire_cached(db, LeaveApproverAssignment, assignment_id, ["steps", "employee", "org_node", "approver"])
    a = (
        await db.execute(
            select(LeaveApproverAssignment)
            .options(*_assignment_options())
            .where(
                LeaveApproverAssignment.id == assignment_id,
                LeaveApproverAssignment.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if not a:
        raise HTTPException(status_code=404, detail="Approval rule not found")
    return a


def _steps_from_payload(data) -> Optional[list]:
    """[(approver_id, approver_role)] from `steps` or the single-approver pair."""
    if getattr(data, "steps", None) is not None:
        return [(s.approver_id if not s.approver_role else None, s.approver_role) for s in data.steps]
    if data.approver_id or data.approver_role:
        return [(data.approver_id if not data.approver_role else None, data.approver_role)]
    return None


async def _write_steps(
    db: AsyncSession, current_user: User, a: LeaveApproverAssignment, steps: list
) -> list:
    """Replace a rule's ordered approvers. Returns names given the reviewer role."""
    tenant_id = current_user.tenant_id
    seen = set()
    for approver_id, role in steps:
        if not approver_id and not role:
            raise HTTPException(status_code=400, detail="Each step needs a person or a position.")
        key = approver_id or role
        if key in seen:
            raise HTTPException(status_code=400, detail="The same approver is listed twice in this rule.")
        seen.add(key)
        await assert_can_be_approver(db, tenant_id, approver_id)
        if approver_id and a.employee_id and approver_id == a.employee_id:
            raise HTTPException(status_code=400, detail="An employee cannot approve their own leave.")

    granted: list[str] = []
    for existing in list(a.steps or []):
        await db.delete(existing)
    await db.flush()
    for i, (approver_id, role) in enumerate(steps, start=1):
        db.add(LeaveApproverRuleStep(
            assignment_id=a.id, step_order=i, approver_id=approver_id, approver_role=role,
        ))
        if approver_id and await ensure_reviewer_role(
            db, tenant_id, approver_id, granted_by=current_user.id,
            context="named on a leave approval rule",
        ):
            u = await db.get(User, approver_id)
            granted.append(full_name(u))
    # Step 1 is mirrored onto the rule itself: older code paths and a
    # downgrade read those columns.
    first = steps[0] if steps else (None, None)
    a.approver_id, a.approver_role = first
    a.step_order = 1
    await db.flush()
    return granted


async def _check_scope_targets(db: AsyncSession, tenant_id, employee_id, org_node_id) -> None:
    if employee_id:
        if not (await db.execute(select(User.id).where(User.id == employee_id, User.tenant_id == tenant_id))).scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Employee not found")
    if org_node_id:
        if not (await db.execute(select(OrgNode.id).where(OrgNode.id == org_node_id, OrgNode.tenant_id == tenant_id))).scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Organization unit not found")


@router.get("/approver-assignments", response_model=List[LeaveApproverAssignmentResponse])
async def list_approver_assignments(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_leave_config("view")),
):
    rows = (
        await db.execute(
            select(LeaveApproverAssignment)
            .options(*_assignment_options())
            .where(LeaveApproverAssignment.tenant_id == current_user.tenant_id)
            .order_by(LeaveApproverAssignment.priority, LeaveApproverAssignment.step_order, LeaveApproverAssignment.id)
        )
    ).scalars().all()
    return [_assignment_to_response(a) for a in rows]


@router.post("/approver-assignments", response_model=LeaveApproverAssignmentResponse, status_code=201)
async def create_approver_assignment(
    data: LeaveApproverAssignmentCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_leave_config("edit")),
):
    tenant_id = current_user.tenant_id
    steps = _steps_from_payload(data)
    if not data.exclude and not steps:
        raise HTTPException(status_code=400, detail="Choose at least one approver for this rule.")
    await _check_scope_targets(db, tenant_id, data.employee_id, data.org_node_id)

    priority = data.priority
    if priority is None:
        # New rules go to the bottom of the list.
        top = (
            await db.execute(
                select(func.max(LeaveApproverAssignment.priority)).where(
                    LeaveApproverAssignment.tenant_id == tenant_id
                )
            )
        ).scalar()
        priority = (top or 0) + 10

    a = LeaveApproverAssignment(
        tenant_id=tenant_id,
        employee_id=data.employee_id,
        org_node_id=data.org_node_id if not data.employee_id else None,
        priority=priority,
        step_order=1,
        cascade=bool(data.cascade) if data.org_node_id and not data.employee_id else False,
        exclude=bool(data.exclude) if data.employee_id else False,
    )
    db.add(a)
    await db.flush()
    granted: list = []
    if not a.exclude:
        a = await _load_assignment(db, tenant_id, a.id)
        granted = await _write_steps(db, current_user, a, steps or [])
    a = await _load_assignment(db, tenant_id, a.id)
    return _assignment_to_response(a, granted)


@router.patch("/approver-assignments/{assignment_id}", response_model=LeaveApproverAssignmentResponse)
async def update_approver_assignment(
    assignment_id: int,
    data: LeaveApproverAssignmentUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_leave_config("edit")),
):
    """Edit a rule. Scope changes are applied (they used to be ignored), and
    the rule keeps its place in the list unless `priority` is sent — editing a
    rule used to move it to the bottom."""
    tenant_id = current_user.tenant_id
    a = await _load_assignment(db, tenant_id, assignment_id)
    update = data.model_dump(exclude_unset=True)

    scope = update.get("scope")
    if scope is None and ("employee_id" in update or "org_node_id" in update):
        if update.get("employee_id"):
            scope = "employee"
        elif update.get("org_node_id"):
            scope = "org_node"
    if scope == "default":
        a.employee_id = None
        a.org_node_id = None
        a.cascade = False
        a.exclude = False
    elif scope == "employee":
        emp = update.get("employee_id", a.employee_id)
        if not emp:
            raise HTTPException(status_code=400, detail="Choose the employee this rule applies to.")
        await _check_scope_targets(db, tenant_id, emp, None)
        a.employee_id = emp
        a.org_node_id = None
        a.cascade = False
    elif scope == "org_node":
        node = update.get("org_node_id", a.org_node_id)
        if not node:
            raise HTTPException(status_code=400, detail="Choose the unit this rule applies to.")
        await _check_scope_targets(db, tenant_id, None, node)
        a.org_node_id = node
        a.employee_id = None
        a.exclude = False

    if "cascade" in update and update["cascade"] is not None:
        a.cascade = bool(update["cascade"]) if a.org_node_id else False
    if "exclude" in update and update["exclude"] is not None:
        a.exclude = bool(update["exclude"]) if a.employee_id else False
    if "priority" in update and update["priority"] is not None:
        a.priority = update["priority"]
    if "is_active" in update and update["is_active"] is not None:
        if update["is_active"] and a.deactivated_reason and not (a.employee_id or a.org_node_id) and scope is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"This rule was switched off because: {a.deactivated_reason} "
                    "Choose who it applies to before turning it back on."
                ),
            )
        a.is_active = update["is_active"]
        if a.is_active:
            a.deactivated_reason = None

    granted: list = []
    steps = _steps_from_payload(data) if ("steps" in update or "approver_id" in update or "approver_role" in update) else None
    if a.exclude:
        for existing in list(a.steps or []):
            await db.delete(existing)
        a.approver_id = None
        a.approver_role = None
    elif steps is not None:
        if not steps:
            raise HTTPException(status_code=400, detail="Choose at least one approver for this rule.")
        granted = await _write_steps(db, current_user, a, steps)
    elif not (a.steps or a.approver_id or a.approver_role):
        raise HTTPException(status_code=400, detail="Choose at least one approver for this rule.")
    await db.flush()

    a = await _load_assignment(db, tenant_id, a.id)
    return _assignment_to_response(a, granted)


@router.delete("/approver-assignments/{assignment_id}", status_code=204)
async def delete_approver_assignment(
    assignment_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_leave_config("delete")),
):
    a = (
        await db.execute(
            select(LeaveApproverAssignment).where(
                LeaveApproverAssignment.id == assignment_id,
                LeaveApproverAssignment.tenant_id == current_user.tenant_id,
            )
        )
    ).scalar_one_or_none()
    if not a:
        raise HTTPException(status_code=404, detail="Approval rule not found")
    await db.delete(a)
    await db.flush()


@router.put("/approver-assignments/reorder")
async def reorder_approver_assignments(
    ordered_ids: List[int],
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_leave_config("edit")),
):
    """Reorder approval rules by setting priority based on list position.
    Accepts an ordered list of assignment IDs (top = highest priority)."""
    tenant_id = current_user.tenant_id
    for idx, rule_id in enumerate(ordered_ids):
        assignment = (
            await db.execute(
                select(LeaveApproverAssignment).where(
                    LeaveApproverAssignment.id == rule_id,
                    LeaveApproverAssignment.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if assignment:
            assignment.priority = (idx + 1) * 10  # 10, 20, 30, ...
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
                total_days=round(b.total_days, 2),
                used_days=round(b.used_days, 2),
                pending_days=round(b.pending_days, 2),
                available_days=round(b.available_days, 2),
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
    """Leave balance for the caller, or for `employee_id` when the caller has
    leave:view over that employee."""
    target = current_user
    if employee_id is not None and employee_id != current_user.id:
        if not await has_permission(db, current_user, "leave", "view"):
            raise HTTPException(
                status_code=403,
                detail="Not authorised to view this employee's balance.",
            )
        await assert_manages(db, current_user, [employee_id], "leave")
        target = await UserService.get_user_by_id(db, employee_id, current_user.tenant_id)
        if not target:
            raise HTTPException(status_code=404, detail="Employee not found")

    balance_set = await LeaveService.compute_balances(
        db,
        current_user.tenant_id,
        target,
        year=year,
        default_days=await _default_days(db, current_user.tenant_id),
    )
    return _balance_set_to_response(balance_set)
