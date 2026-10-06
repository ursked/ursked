from datetime import date, datetime, time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ── Salary Grades ─────────────────────────────────────────────────

class SalaryGradeCreate(BaseModel):
    code: str = Field(..., max_length=50)
    name: str = Field(..., max_length=100)
    description: Optional[str] = None
    monthly_rate: float
    daily_rate: Optional[float] = None
    hourly_rate: Optional[float] = None
    is_active: bool = True
    sort_order: int = 0


class SalaryGradeUpdate(BaseModel):
    code: Optional[str] = Field(None, max_length=50)
    name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None
    monthly_rate: Optional[float] = None
    daily_rate: Optional[float] = None
    hourly_rate: Optional[float] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None


class SalaryGradeResponse(BaseModel):
    """A grade's code, name and status are structure (finances:view); its rates
    are figures, None with rates_hidden=True for anyone who is not a salary
    viewer."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    description: Optional[str] = None
    monthly_rate: Optional[float] = None
    daily_rate: Optional[float] = None
    hourly_rate: Optional[float] = None
    rates_hidden: bool = False
    is_active: bool
    sort_order: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ── Employee Salary ───────────────────────────────────────────────

class EmployeeSalaryCreate(BaseModel):
    employee_id: int
    salary_grade_id: int
    effective_date: date
    monthly_rate_override: Optional[float] = None
    notes: Optional[str] = None


class EmployeeSalaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    employee_id: int
    salary_grade_id: int
    effective_date: date
    monthly_rate_override: Optional[float] = None
    notes: Optional[str] = None
    grade_code: Optional[str] = None
    grade_name: Optional[str] = None
    grade_monthly_rate: Optional[float] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ── Deduction Types ───────────────────────────────────────────────

class DeductionTypeCreate(BaseModel):
    code: str = Field(..., max_length=50)
    name: str = Field(..., max_length=100)
    description: Optional[str] = None
    calculation_type: str = Field("fixed", pattern="^(fixed|percentage|tiered)$")
    calculation_basis: str = Field("gross", pattern="^(gross|base)$")
    default_amount: Optional[float] = None
    default_rate: Optional[float] = None
    is_mandatory: bool = False
    is_employer_contribution: bool = False
    is_active: bool = True
    sort_order: int = 0


class DeductionTypeUpdate(BaseModel):
    code: Optional[str] = Field(None, max_length=50)
    name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None
    calculation_type: Optional[str] = Field(None, pattern="^(fixed|percentage|tiered)$")
    calculation_basis: Optional[str] = Field(None, pattern="^(gross|base)$")
    default_amount: Optional[float] = None
    default_rate: Optional[float] = None
    is_mandatory: Optional[bool] = None
    is_employer_contribution: Optional[bool] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None


class DeductionTypeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    description: Optional[str] = None
    calculation_type: str
    calculation_basis: str = "gross"
    default_amount: Optional[float] = None
    default_rate: Optional[float] = None
    is_mandatory: bool
    is_employer_contribution: bool
    is_system: bool
    is_active: bool
    sort_order: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ── Deduction Brackets (tiered tables) ────────────────────────────

class DeductionBracketItem(BaseModel):
    over_amount: float = 0
    up_to_amount: Optional[float] = None
    base_amount: float = 0
    rate: float = 0
    rate_basis: str = Field("excess", pattern="^(excess|full)$")


class DeductionBracketResponse(DeductionBracketItem):
    model_config = ConfigDict(from_attributes=True)
    id: int


class DeductionBracketsReplace(BaseModel):
    brackets: List[DeductionBracketItem]


# ── Payroll Periods ───────────────────────────────────────────────

class PayrollPeriodCreate(BaseModel):
    name: str = Field(..., max_length=100)
    period_type: str = Field("monthly", pattern="^(monthly|semi_monthly|biweekly|weekly)$")
    start_date: date
    end_date: date
    # When set, the run also pays every scheduled CompensationItem whose
    # payout_date == this date (bonuses/incentives/allowances/leave-cash).
    payout_date: Optional[date] = None
    schedule_id: Optional[int] = None
    notes: Optional[str] = None


class PayrollPeriodResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    period_type: str
    start_date: date
    end_date: date
    payout_date: Optional[date] = None
    schedule_id: Optional[int] = None
    status: str
    compute_progress: Optional[Dict[str, Any]] = None
    computed_at: Optional[datetime] = None
    computed_by: Optional[int] = None
    approved_at: Optional[datetime] = None
    approved_by: Optional[int] = None
    finalized_at: Optional[datetime] = None
    finalized_by: Optional[int] = None
    notes: Optional[str] = None
    item_count: Optional[int] = None
    # Figures: None with figures_hidden=True unless the caller is a salary
    # viewer. The rest of the period is the payroll calendar (structure).
    total_gross: Optional[float] = None
    total_net: Optional[float] = None
    figures_hidden: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ── Payroll Items ─────────────────────────────────────────────────

class PayrollItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    payroll_period_id: int
    employee_id: int
    employee_name: Optional[str] = None
    salary_grade_id: Optional[int] = None
    grade_name: Optional[str] = None
    base_pay: float
    overtime_pay: float
    gross_pay: float
    total_deductions: float
    total_contributions: float
    net_pay: float
    breakdown: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ── Payroll Summary ───────────────────────────────────────────────

class PayrollSummary(BaseModel):
    period: PayrollPeriodResponse
    total_employees: int
    total_base_pay: float
    total_overtime_pay: float
    total_gross_pay: float
    total_deductions: float
    total_contributions: float
    total_net_pay: float
    items: List[PayrollItemResponse]


# ── Employee self-service payslips ────────────────────────────────

class MyPayslipSummary(BaseModel):
    """One row in the employee's payslip list (released runs only)."""
    period_id: int
    period_name: str
    start_date: date
    end_date: date
    payout_date: Optional[date] = None
    status: str
    gross_pay: float
    total_deductions: float
    net_pay: float


class MyPayslipDetail(BaseModel):
    period_id: int
    period_name: str
    start_date: date
    end_date: date
    payout_date: Optional[date] = None
    status: str
    employee_name: str
    grade_name: Optional[str] = None
    base_pay: float
    overtime_pay: float
    gross_pay: float
    total_deductions: float
    total_contributions: float
    net_pay: float
    # What was taken from the employee's pay (adds up to total_deductions)
    # and, separately, what the employer paid on top. [{name, amount, ...}]
    employee_deductions: List[Dict[str, Any]] = []
    employer_contributions: List[Dict[str, Any]] = []
    breakdown: Dict[str, Any] = {}


# ── Pay rules ─────────────────────────────────────────────────────
# Company-wide rules payroll applies to everyone: how a monthly rate becomes a
# daily one, and the night and holiday premiums. They are STRUCTURE, not
# anyone's pay, so finances:view reads them without salary access. They are
# stored on app_settings, but only this endpoint changes them: they used to sit
# in General settings, where anyone who could edit settings could change what
# everyone is paid without holding any finance permission.

class PayRulesResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    working_days_per_month: int = 22
    night_diff_multiplier: float = 1.0
    night_shift_start: Optional[time] = None
    night_shift_end: Optional[time] = None
    holiday_worked_multiplier: float = 1.0
    special_holiday_worked_multiplier: float = 1.0


class PayRulesUpdate(BaseModel):
    """The whole set, saved together. The night window has no default: it must
    be sent, and null means no window (so no night differential). A client that
    leaves it out gets an error instead of silently clearing it."""

    working_days_per_month: int = Field(..., ge=1, le=31)
    # Premiums are paid as hours x rate x (multiplier - 1), so anything below
    # 1.0 would subtract pay. Floor at 1.0 (= no premium) rather than allow that.
    night_diff_multiplier: float = Field(..., ge=1.0, le=10.0)
    night_shift_start: Optional[time]
    night_shift_end: Optional[time]
    holiday_worked_multiplier: float = Field(..., ge=1.0, le=10.0)
    special_holiday_worked_multiplier: float = Field(..., ge=1.0, le=10.0)


# The app_settings columns the pay rules are made of. PATCH /settings/app
# refuses to change these; they are changed here, under finances:edit.
PAY_RULE_FIELDS = tuple(PayRulesUpdate.model_fields)
