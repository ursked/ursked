from datetime import date, datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


LeaveStatus = Literal["pending", "approved", "rejected", "cancelled"]

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
    status: str
    decided_at: Optional[datetime] = None
    notes: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# ── Leave Application Schemas (existing, updated) ──────────────────


class LeaveApplicationCreate(BaseModel):
    leave_type: str = Field(..., min_length=1, max_length=50)
    start_date: date
    end_date: date
    reason: str = Field(..., min_length=1, max_length=2000)
    supporting_documents: Optional[List[str]] = None


class RuleViolation(BaseModel):
    rule: str
    mode: Literal["block", "warn"]
    message: str
    details: Dict = {}


class LeavePrecheckResponse(BaseModel):
    """Dry-run enforcement result for the filing form."""
    allowed: bool  # False when any block-mode rule fails
    days_requested: float
    violations: List[RuleViolation] = []  # failing block-mode rules
    warnings: List[RuleViolation] = []  # failing warn-mode rules


class LeaveApplicationUpdate(BaseModel):
    leave_type: Optional[str] = Field(None, min_length=1, max_length=50)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    reason: Optional[str] = Field(None, min_length=1, max_length=2000)


class LeaveReviewRequest(BaseModel):
    action: Literal["approve", "reject"]
    notes: Optional[str] = None


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
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class LeavePrecheckRequest(BaseModel):
    leave_type: str = Field(..., min_length=1, max_length=50)
    start_date: date
    end_date: date
    supporting_documents: Optional[List[str]] = None


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
    sort_order: int = 0


class LeaveTypeUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None


class LeaveTypeResponse(BaseModel):
    id: int
    code: str
    name: str
    description: Optional[str] = None
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
    source: str  # "auto", "manual", "hybrid"


class ApprovalChainPreviewResponse(BaseModel):
    chain: List[ApprovalChainPreviewItem]


# ── Approver Assignment Schemas ───────────────────────────────────


ApproverRole = Literal["node_head", "node_deputy", "parent_head", "parent_deputy"]


class LeaveApproverAssignmentCreate(BaseModel):
    employee_id: Optional[int] = None
    org_node_id: Optional[int] = None
    approver_id: Optional[int] = None
    approver_role: Optional[ApproverRole] = None
    step_order: int = Field(1, ge=1)
    priority: int = Field(100, ge=1)
    cascade: bool = False
    exclude: bool = False


class LeaveApproverAssignmentUpdate(BaseModel):
    approver_id: Optional[int] = None
    approver_role: Optional[ApproverRole] = None
    step_order: Optional[int] = Field(None, ge=1)
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
    step_order: int
    priority: int = 100
    cascade: bool = False
    exclude: bool = False
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


# ── Team Stats Schemas ────────────────────────────────────────────


class TeamStatsResponse(BaseModel):
    summary: Dict[str, int]
    by_type: List[Dict]
    by_month: List[Dict]
    by_status: Dict[str, int]
