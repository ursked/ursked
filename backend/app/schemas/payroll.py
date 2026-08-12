from datetime import date, datetime
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
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    description: Optional[str] = None
    monthly_rate: float
    daily_rate: Optional[float] = None
    hourly_rate: Optional[float] = None
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
    total_gross: Optional[float] = None
    total_net: Optional[float] = None
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
    breakdown: Dict[str, Any] = {}
