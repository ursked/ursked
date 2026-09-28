from datetime import date, datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# "expired": still pending when its last day passed (see leave_reminder_service).
LeaveStatus = Literal["pending", "approved", "rejected", "cancelled", "expired"]
HalfDay = Literal["am", "pm"]

# ── Type aliases for policy configuration ───────────────────────────

AccrualMethod = Literal["monthly", "annual"]
PoolType = Literal["per_type", "shared"]
CompensationType = Literal["paid", "leave_credit", "both", "none"]
ApprovalMode = Literal["auto", "manual", "hybrid"]
# Employment types are tenant-configurable (see configurable_types); keep this
# an open string rather than a fixed enum so custom/generic types validate.
EmploymentType = str


# ── Leave Approval Step Schemas ───────────────────────────────────

class LeaveApprovalStepResponse(BaseModel):
    id: int
    step_order: int
    approver_id: Optional[int] = None
    approver_name: str = ""
    status: str  # pending | approved | rejected | skipped
    decided_at: Optional[datetime] = None
    notes: Optional[str] = None
    # The requester's own step: only created when nobody else in the company
    # can approve leave, and only completed through the self-approve action.
    is_self: bool = False

    model_config = ConfigDict(from_attributes=True)


class LeaveApprovalEventResponse(BaseModel):
    """An override, reassignment, reminder etc., shown on the request."""
    id: int
    action: str
    actor_id: Optional[int] = None
    actor_name: Optional[str] = None
    from_approver_id: Optional[int] = None
    from_approver_name: Optional[str] = None
    to_approver_id: Optional[int] = None
    to_approver_name: Optional[str] = None
    reason: Optional[str] = None
    created_at: Optional[datetime] = None


class LeaveActions(BaseModel):
    """What the CALLER may do with this request, as the API will judge it.

    The UI shows a button only when its flag is true, so it never offers an
    action the server would refuse (reviewers used to see Cancel on other
    people's requests and get a 403).
    """
    can_edit: bool = False
    can_cancel: bool = False
    can_review: bool = False
    can_self_approve: bool = False
    can_override: bool = False
    can_reassign: bool = False
    can_revoke: bool = False


class DayBreakdownItem(BaseModel):
    date: date
    days: float
    reason: str
    label: str = ""


# ── Leave Application Schemas (existing, updated) ──────────────────


class LeaveApplicationCreate(BaseModel):
    # Someone with leave:create may file on behalf of an employee they manage —
    # sick leave phoned in on the day is the common case. Omit it, or set it to
    # your own id, to file for yourself. Anyone else supplying someone else's id
    # is refused rather than silently redirected to their own record.
    employee_id: Optional[int] = None
    leave_type: str = Field(..., min_length=1, max_length=50)
    start_date: date
    end_date: date
    # Morning or afternoon off; only for a single-day request. Counts 0.5.
    half_day: Optional[HalfDay] = None
    reason: str = Field(..., min_length=1, max_length=2000)
    supporting_documents: Optional[List[str]] = None


class RuleViolation(BaseModel):
    rule: str
    mode: Literal["block", "warn"]
    message: str
    details: Dict = {}


class LeavePrecheckResponse(BaseModel):
    """Dry-run of filing: what the request would cost and what it breaks,
    shown in the form before the employee submits."""
    allowed: bool  # False when any block-mode rule fails
    days_requested: float
    violations: List[RuleViolation] = []  # failing block-mode rules
    warnings: List[RuleViolation] = []  # failing warn-mode rules
    day_breakdown: List[DayBreakdownItem] = []
    days_by_year: Dict[int, float] = {}
    # Readable reason the request cannot be filed at all (e.g. no working day
    # in the range), or None.
    problem: Optional[str] = None


class LeaveApplicationUpdate(BaseModel):
    leave_type: Optional[str] = Field(None, min_length=1, max_length=50)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    half_day: Optional[HalfDay] = None
    reason: Optional[str] = Field(None, min_length=1, max_length=2000)
    supporting_documents: Optional[List[str]] = None


class LeaveOverrideRequest(BaseModel):
    """Approve or reject a request without waiting for its approver.

    For people with leave:edit over the employee, when an approver is absent or
    stuck. The reason is required and is shown on the request and in the
    audit log: an override is a decision made on someone else's behalf.
    """
    action: Literal["approve", "reject"]
    reason: str = Field(min_length=1, max_length=2000)


class LeaveReassignRequest(BaseModel):
    """Move a pending step to a different approver."""
    approver_id: int
    reason: str = Field(min_length=1, max_length=2000)
    # Defaults to the step currently waiting for a decision.
    step_id: Optional[int] = None


class LeaveSelfApproveRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


class LeaveReviewRequest(BaseModel):
    action: Literal["approve", "reject"]
    notes: Optional[str] = None


class LeaveRevokeRequest(BaseModel):
    """Undo a decision on an already-approved application.

    "unapprove" returns it to the approval queue (status -> pending) — the right
    action when the approval itself was the mistake. "reject" refuses it outright
    (status -> rejected) — the right action when the leave should not stand.

    Either way the schedule overlay is reverted, so the employee goes back on the
    roster. A reason is required: this reverses a decision the employee was
    already notified about.
    """
    action: Literal["unapprove", "reject"]
    notes: str = Field(min_length=1)


class LeaveApplicationResponse(BaseModel):
    id: int
    employee_id: int
    employee_name: str
    leave_type: str
    start_date: date
    end_date: date
    days_requested: float
    reason: str
    supporting_documents: Optional[list] = None
    status: str
    reviewed_by: Optional[int] = None
    reviewer_name: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    reviewer_notes: Optional[str] = None
    rule_warnings: Optional[List[RuleViolation]] = None
    approval_steps: List[LeaveApprovalStepResponse] = []
    current_step: Optional[int] = None
    leave_type_name: Optional[str] = None
    half_day: Optional[str] = None
    day_breakdown: Optional[List[DayBreakdownItem]] = None
    events: List[LeaveApprovalEventResponse] = []
    actions: LeaveActions = LeaveActions()
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class LeavePrecheckRequest(BaseModel):
    # Filing on someone's behalf previews THEIR roster and balance.
    employee_id: Optional[int] = None
    leave_type: str = Field(..., min_length=1, max_length=50)
    start_date: date
    end_date: date
    half_day: Optional[HalfDay] = None
    supporting_documents: Optional[List[str]] = None
    # When editing an existing request, exclude it from overlap and balance.
    application_id: Optional[int] = None


class LeaveApplicationListResponse(BaseModel):
    items: List[LeaveApplicationResponse]
    total: int
    page: int
    per_page: int
    total_pages: int


class LeaveBalanceItem(BaseModel):
    leave_type: str
    leave_type_name: str = ""
    total_days: float
    used_days: float
    pending_days: float
    available_days: float


class LeaveBalanceResponse(BaseModel):
    employee_id: int
    policy_name: Optional[str] = None
    accrual_method: Optional[str] = None
    pool_type: Optional[str] = None
    balances: List[LeaveBalanceItem]


# ── Leave Type Configuration Schemas ────────────────────────────────


class LeaveTypeCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=50, pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    export_code: Optional[str] = Field(None, max_length=20)
    sort_order: int = 0


class LeaveTypeUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    export_code: Optional[str] = Field(None, max_length=20)
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None


class LeaveTypeResponse(BaseModel):
    id: int
    code: str
    name: str
    description: Optional[str] = None
    export_code: Optional[str] = None
    is_system: bool
    is_active: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ── Leave Policy Entitlement Schemas ────────────────────────────────


class LeavePolicyEntitlementCreate(BaseModel):
    leave_type_id: int
    annual_credits: float = Field(..., ge=0)
    carry_over_enabled: bool = False
    max_carry_over_days: float = Field(0, ge=0)
    carry_over_expiry_months: int = Field(0, ge=0)
    cash_convertible: bool = False
    cash_conversion_rate: float = Field(1.0, ge=0)
    requires_documentation: bool = False
    min_notice_days: int = Field(0, ge=0)
    max_consecutive_days: Optional[float] = Field(None, ge=0)


class LeavePolicyEntitlementUpdate(BaseModel):
    annual_credits: Optional[float] = Field(None, ge=0)
    carry_over_enabled: Optional[bool] = None
    max_carry_over_days: Optional[float] = Field(None, ge=0)
    carry_over_expiry_months: Optional[int] = Field(None, ge=0)
    cash_convertible: Optional[bool] = None
    cash_conversion_rate: Optional[float] = Field(None, ge=0)
    requires_documentation: Optional[bool] = None
    min_notice_days: Optional[int] = Field(None, ge=0)
    max_consecutive_days: Optional[float] = Field(None, ge=0)


class LeavePolicyEntitlementResponse(BaseModel):
    id: int
    leave_type_id: int
    leave_type_code: str = ""
    leave_type_name: str = ""
    annual_credits: float
    carry_over_enabled: bool
    max_carry_over_days: float
    carry_over_expiry_months: int
    cash_convertible: bool
    cash_conversion_rate: float
    requires_documentation: bool
    min_notice_days: int
    max_consecutive_days: Optional[float] = None

    model_config = ConfigDict(from_attributes=True)


class BulkEntitlementsRequest(BaseModel):
    entitlements: List[LeavePolicyEntitlementCreate]


# ── Leave Policy Schemas ────────────────────────────────────────────


# Per-rule enforcement mode map (block | warn | off per rule).
EnforcementMode = Literal["block", "warn", "off"]


class LeavePolicyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    accrual_method: AccrualMethod = "annual"
    pool_type: PoolType = "per_type"
    employment_types: List[str] = []
    is_default: bool = False
    approval_mode: ApprovalMode = "auto"
    required_approval_levels: int = Field(1, ge=1)
    enforcement: Dict[str, EnforcementMode] = {}
    # Shared pool fields
    shared_annual_credits: Optional[float] = Field(None, ge=0)
    shared_carry_over_enabled: bool = False
    shared_max_carry_over_days: float = Field(0, ge=0)
    shared_carry_over_expiry_months: int = Field(0, ge=0)
    shared_cash_convertible: bool = False
    shared_cash_conversion_rate: float = Field(1.0, ge=0)
    shared_max_consecutive_days: Optional[float] = Field(None, ge=0)
    # Optional inline entitlements for per_type policies
    entitlements: Optional[List[LeavePolicyEntitlementCreate]] = None


class LeavePolicyUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    accrual_method: Optional[AccrualMethod] = None
    pool_type: Optional[PoolType] = None
    employment_types: Optional[List[str]] = None
    is_default: Optional[bool] = None
    is_active: Optional[bool] = None
    approval_mode: Optional[ApprovalMode] = None
    required_approval_levels: Optional[int] = Field(None, ge=1)
    enforcement: Optional[Dict[str, EnforcementMode]] = None
    shared_annual_credits: Optional[float] = Field(None, ge=0)
    shared_carry_over_enabled: Optional[bool] = None
    shared_max_carry_over_days: Optional[float] = Field(None, ge=0)
    shared_carry_over_expiry_months: Optional[int] = Field(None, ge=0)
    shared_cash_convertible: Optional[bool] = None
    shared_cash_conversion_rate: Optional[float] = Field(None, ge=0)
    shared_max_consecutive_days: Optional[float] = Field(None, ge=0)


class PolicyCompleteness(BaseModel):
    has_employment_types: bool
    has_entitlements: bool
    uncovered_leave_types: List[str] = []
    has_approval_path: bool
    enforcement_configured: bool


class LeavePolicyResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    accrual_method: str
    pool_type: str
    employment_types: List[str]
    is_default: bool
    is_active: bool
    approval_mode: str
    required_approval_levels: int
    enforcement: Dict[str, str] = {}
    shared_annual_credits: Optional[float] = None
    shared_carry_over_enabled: bool
    shared_max_carry_over_days: float
    shared_carry_over_expiry_months: int
    shared_cash_convertible: bool
    shared_cash_conversion_rate: float
    shared_max_consecutive_days: Optional[float] = None
    entitlements: List[LeavePolicyEntitlementResponse] = []
    completeness: Optional[PolicyCompleteness] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ── Overtime Category Schemas ───────────────────────────────────────


class OvertimeCategoryCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=50, pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    multiplier_rate: float = Field(..., gt=0)
    compensation_type: CompensationType = "paid"
    leave_credit_rate: Optional[float] = Field(None, gt=0)
    leave_credit_type_id: Optional[int] = None
    sort_order: int = 0


class OvertimeCategoryUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    multiplier_rate: Optional[float] = Field(None, gt=0)
    compensation_type: Optional[CompensationType] = None
    leave_credit_rate: Optional[float] = Field(None, gt=0)
    leave_credit_type_id: Optional[int] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None


class OvertimeCategoryResponse(BaseModel):
    id: int
    code: str
    name: str
    description: Optional[str] = None
    multiplier_rate: float
    compensation_type: str
    leave_credit_rate: Optional[float] = None
    leave_credit_type_id: Optional[int] = None
    leave_credit_type_name: Optional[str] = None
    is_active: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ── Approval Chain Preview Schemas ────────────────────────────────


class ApprovalChainPreviewItem(BaseModel):
    approver_id: int
    approver_name: str
    step_order: int
    # auto | hybrid_org_chart | manual_* | fallback_* | self_approval
    source: str
    # True when a unit's deputy stands in for its head.
    is_deputy: bool = False
    node_name: Optional[str] = None


class ApprovalChainPreviewResponse(BaseModel):
    chain: List[ApprovalChainPreviewItem]


# ── Approver Assignment Schemas ───────────────────────────────────


ApproverRole = Literal["node_head", "node_deputy", "parent_head", "parent_deputy"]
RuleScope = Literal["default", "employee", "org_node"]


class ApproverRuleStepIn(BaseModel):
    """One approver in a rule's chain: a named person or a position."""
    approver_id: Optional[int] = None
    approver_role: Optional[ApproverRole] = None


class ApproverRuleStepOut(BaseModel):
    step_order: int
    approver_id: Optional[int] = None
    approver_name: Optional[str] = None
    approver_role: Optional[str] = None
    approver_active: bool = True


class LeaveApproverAssignmentCreate(BaseModel):
    employee_id: Optional[int] = None
    org_node_id: Optional[int] = None
    # Ordered approvers: step 1, step 2, ... The single approver_id /
    # approver_role pair is still accepted and means a one-step rule.
    steps: Optional[List[ApproverRuleStepIn]] = None
    approver_id: Optional[int] = None
    approver_role: Optional[ApproverRole] = None
    step_order: int = Field(1, ge=1)
    # Omit to add the rule at the bottom of the list.
    priority: Optional[int] = Field(None, ge=1)
    cascade: bool = False
    exclude: bool = False


class LeaveApproverAssignmentUpdate(BaseModel):
    # Changing who the rule applies to. "default" clears the employee/unit and
    # the exclude/cascade flags that only make sense with them.
    scope: Optional[RuleScope] = None
    employee_id: Optional[int] = None
    org_node_id: Optional[int] = None
    steps: Optional[List[ApproverRuleStepIn]] = None
    approver_id: Optional[int] = None
    approver_role: Optional[ApproverRole] = None
    step_order: Optional[int] = Field(None, ge=1)
    # Only the reorder action should send this; editing a rule keeps its place.
    priority: Optional[int] = Field(None, ge=1)
    is_active: Optional[bool] = None
    cascade: Optional[bool] = None
    exclude: Optional[bool] = None


class LeaveApproverAssignmentResponse(BaseModel):
    id: int
    employee_id: Optional[int] = None
    employee_name: Optional[str] = None
    org_node_id: Optional[int] = None
    org_node_name: Optional[str] = None
    approver_id: Optional[int] = None
    approver_name: Optional[str] = None
    approver_role: Optional[str] = None
    steps: List[ApproverRuleStepOut] = []
    step_order: int
    priority: int = 100
    cascade: bool = False
    exclude: bool = False
    is_active: bool
    deactivated_reason: Optional[str] = None
    # Names of people this save gave the Leave Approver role to.
    granted_role_to: List[str] = []

    model_config = ConfigDict(from_attributes=True)


class ApproverCheckResponse(BaseModel):
    user_id: int
    name: Optional[str] = None
    found: bool
    is_active: bool
    has_reviewer_role: bool
    will_grant_role: bool
    message: str = ""


# ── Team Stats Schemas ────────────────────────────────────────────


class TeamStatsResponse(BaseModel):
    summary: Dict[str, int]
    by_type: List[Dict]
    by_month: List[Dict]
    by_status: Dict[str, int]
