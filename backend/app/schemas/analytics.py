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
    total_pay: float = 0
    total_credits: float = 0


class OvertimeTrendsResponse(BaseModel):
    year: int
    categories: List[CategoryInfo]
    months: List[OvertimeMonthBreakdown]


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

class DashboardResponse(BaseModel):
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
