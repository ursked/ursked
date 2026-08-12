from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ── Payout schedule ──────────────────────────────────────────────────

class CutoffRule(BaseModel):
    cutoff_start_day: int = Field(ge=1, le=31)
    cutoff_end_day: int = Field(ge=1, le=31)
    payout_day: int = Field(ge=1, le=31)
    payout_month_offset: int = Field(default=0, ge=0, le=12)


class PayoutScheduleBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    frequency: str = Field(default="semi_monthly", pattern=r"^(semi_monthly|monthly|weekly|bi_weekly)$")
    cutoffs: List[CutoffRule]
    payout_day_adjust: str = Field(default="none", pattern=r"^(none|prev_business_day|next_business_day)$")
    is_active: bool = True


class PayoutScheduleCreate(PayoutScheduleBase):
    pass


class PayoutScheduleUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    frequency: Optional[str] = Field(None, pattern=r"^(semi_monthly|monthly|weekly|bi_weekly)$")
    cutoffs: Optional[List[CutoffRule]] = None
    payout_day_adjust: Optional[str] = Field(None, pattern=r"^(none|prev_business_day|next_business_day)$")
    is_active: Optional[bool] = None


class PayoutScheduleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    frequency: str
    cutoffs: List[CutoffRule]
    payout_day_adjust: str
    is_active: bool


class PayoutPreviewRequest(BaseModel):
    earned_on: date


class PayoutPreviewResponse(BaseModel):
    earned_on: date
    payout_date: Optional[date]


# ── Compensation items ───────────────────────────────────────────────

KIND_PATTERN = r"^(bonus|incentive|allowance|salary_adjustment|leave_cash|correction)$"


class CompensationItemCreate(BaseModel):
    employee_id: int
    kind: str = Field(pattern=KIND_PATTERN)
    amount: float
    earned_on: date
    recurrence: str = Field(default="once", pattern=r"^(once|monthly|per_cutoff)$")
    reason: str = Field(min_length=1)
    payout_date: Optional[date] = None  # override; else resolved from schedule
    meta: Optional[dict] = None


class CompensationItemVoid(BaseModel):
    reason: str = Field(min_length=1)


class CompensationItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    employee_id: int
    kind: str
    amount: float
    earned_on: date
    payout_date: date
    recurrence: str
    template_id: Optional[int] = None
    status: str
    reason: str
    meta: Optional[dict] = None
    payroll_item_id: Optional[int] = None
    created_at: Optional[datetime] = None


# ── Salary assignment / raise ────────────────────────────────────────

class SalaryAssign(BaseModel):
    employee_id: int
    salary_grade_id: int
    effective_date: date
    monthly_rate_override: Optional[float] = Field(None, ge=0)
    notes: Optional[str] = None


class CurrentSalaryRow(BaseModel):
    employee_id: int
    employee_name: str
    email: Optional[str] = None
    employee_type: Optional[str] = None
    salary_grade_id: Optional[int] = None
    salary_grade_code: Optional[str] = None
    salary_grade_name: Optional[str] = None
    monthly_rate: Optional[float] = None
    effective_date: Optional[date] = None


class RaiseRequest(BaseModel):
    """Apply a salary increase to one or more employees (single = list of one)."""
    employee_ids: List[int] = Field(min_length=1)
    mode: str = Field(pattern=r"^(percent|fixed|grade)$")
    # percent: value is a percentage (e.g. 10 = +10%); fixed: currency amount;
    # grade: value ignored, new_grade_id required.
    value: float = 0
    effective_date: date
    new_grade_id: Optional[int] = None
    reason: Optional[str] = None


class RaiseResultRow(BaseModel):
    employee_id: int
    status: str  # applied | skipped
    from_basic: Optional[float] = None
    to_basic: Optional[float] = None
    delta: Optional[float] = None
    effective_date: Optional[str] = None
    reason: Optional[str] = None


# ── Bulk compensation grant ──────────────────────────────────────────

class BulkCompensationCreate(BaseModel):
    """Grant the same compensation line to many employees at once."""
    employee_ids: List[int] = Field(min_length=1)
    kind: str = Field(pattern=KIND_PATTERN)
    amount: float
    earned_on: date
    recurrence: str = Field(default="once", pattern=r"^(once|monthly|per_cutoff)$")
    reason: str = Field(min_length=1)
    payout_date: Optional[date] = None
    meta: Optional[dict] = None


class ExpandRecurringRequest(BaseModel):
    horizon_start: date
    horizon_end: date
