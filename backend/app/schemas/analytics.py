from typing import Dict, List, Optional

from pydantic import BaseModel


# ── Shared ────────────────────────────────────────────────────────

MONTH_LABELS = [
    "", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]


class CategoryInfo(BaseModel):
    code: str
    name: str
    compensation_type: Optional[str] = None


class LeaveTypeInfo(BaseModel):
    code: str
    name: str


# ── Overtime Trends ──────────────────────────────────────────────

class OvertimeMonthBreakdown(BaseModel):
    month: int
    month_label: str
    total_minutes: float = 0
    total_hours: float = 0
    by_category: Dict[str, float] = {}
    log_count: int = 0
    # Overtime pay is a salary figure: None unless the caller is a salary viewer.
    total_pay: Optional[float] = 0
    total_credits: float = 0


class OvertimeTrendsResponse(BaseModel):
    year: int
    categories: List[CategoryInfo]
    months: List[OvertimeMonthBreakdown]
    pay_hidden: bool = False


# ── Overtime Paid vs Unpaid ──────────────────────────────────────

class PaidUnpaidMonth(BaseModel):
    month: int
    month_label: str
    paid_minutes: float = 0
    paid_hours: float = 0
    unpaid_minutes: float = 0
    unpaid_hours: float = 0
    total_minutes: float = 0
    total_hours: float = 0


class OvertimePaidUnpaidResponse(BaseModel):
    year: int
    months: List[PaidUnpaidMonth]


# ── Leave Trends ─────────────────────────────────────────────────

class LeaveMonthBreakdown(BaseModel):
    month: int
    month_label: str
    total_days: float = 0
    application_count: int = 0
    by_type: Dict[str, float] = {}


class LeaveTrendsResponse(BaseModel):
    year: int
    leave_types: List[LeaveTypeInfo]
    months: List[LeaveMonthBreakdown]


# ── Attendance Summary ───────────────────────────────────────────

class AttendanceMonthSummary(BaseModel):
    month: int
    month_label: str
    total_records: int = 0
    present_count: int = 0
    late_count: int = 0
    absent_count: int = 0
    avg_hours_worked: float = 0
    total_tardiness_minutes: int = 0
    total_undertime_minutes: int = 0
    total_overtime_minutes: int = 0


class AttendanceSummaryResponse(BaseModel):
    year: int
    months: List[AttendanceMonthSummary]


# ── Overview ─────────────────────────────────────────────────────

class AnalyticsOverviewResponse(BaseModel):
    total: int
    active: int
    inactive: int


# ── Dashboard ──────────────────────────────────────────────────
#
# The dashboard is everyone's home screen, so it always answers. Holders of
# reports:view get the metrics block (company-wide for full-scope roles, their
# own teams otherwise); everyone gets the personal block. It used to be three
# role codes or nothing, so an employee's dashboard 403'd on load and again on
# every 60-second refresh, and rendered as a page of dashes.

class DashboardMetrics(BaseModel):
    total_employees: int
    active_employees: int
    departments: int
    pending_leaves: int
    pending_overtime: int
    today_present: int
    today_late: int
    today_absent: int
    month_attendance_rate: float
    month_late_count: int
    month_ot_hours: float
    month_leave_days: float
    recent_leave_applications: List["DashboardLeaveItem"]
    recent_overtime_logs: List["DashboardOvertimeItem"]


class DashboardLeaveItem(BaseModel):
    id: int
    employee_name: str
    leave_type: str
    start_date: str
    end_date: str
    days: float
    status: str


class DashboardOvertimeItem(BaseModel):
    id: int
    employee_name: str
    category: str
    date: str
    hours: float
    status: str


class PersonalShift(BaseModel):
    date: str
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    status: str
    status_label: str
    category: Optional[str] = None


class PersonalLeaveBalance(BaseModel):
    leave_type: str
    name: str
    available_days: float
    total_days: float


class PersonalLeaveRequest(BaseModel):
    id: int
    leave_type: str
    start_date: str
    end_date: str
    days: float


class PersonalClockStatus(BaseModel):
    enabled: bool
    clocked_in: bool
    since: Optional[str] = None


class PersonalDashboard(BaseModel):
    today: str
    next_shifts: List[PersonalShift]
    # None when the balance could not be computed, so the screen can say so
    # instead of showing "0 days left".
    leave_balances: Optional[List[PersonalLeaveBalance]] = None
    pending_leave_requests: List[PersonalLeaveRequest]
    pending_schedule_requests: int
    clock: PersonalClockStatus


class DashboardResponse(BaseModel):
    # "company": metrics cover everyone; "team": only the employees the caller
    # manages; "personal": no reports:view, metrics is None.
    view: str
    metrics: Optional[DashboardMetrics] = None
    personal: PersonalDashboard
