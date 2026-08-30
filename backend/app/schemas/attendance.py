from datetime import date, datetime, time
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# ── Attendance Records ─────────────────────────────────────────────

class AttendanceRecordCreate(BaseModel):
    employee_id: int
    date: date
    actual_start_time: Optional[time] = None
    actual_end_time: Optional[time] = None
    notes: Optional[str] = None


class SelfTimeEntry(BaseModel):
    """Employee self-service time entry (CE subset). No employee_id — forced
    to the authenticated user. NOT a clock-in/kiosk; the employee fills in
    their own hours after the fact."""
    date: date
    actual_start_time: Optional[time] = None
    actual_end_time: Optional[time] = None
    notes: Optional[str] = None

class AttendanceRecordUpdate(BaseModel):
    actual_start_time: Optional[time] = None
    actual_end_time: Optional[time] = None
    status: Optional[str] = None
    notes: Optional[str] = None

class AttendanceRecordResponse(BaseModel):
    id: int
    tenant_id: str
    employee_id: int
    shift_id: Optional[int] = None
    date: date
    actual_start_time: Optional[time] = None
    actual_end_time: Optional[time] = None
    scheduled_start_time: Optional[time] = None
    scheduled_end_time: Optional[time] = None
    hours_worked: Optional[float] = None
    tardiness_minutes: int = 0
    overtime_minutes: int = 0
    undertime_minutes: int = 0
    status: str
    notes: Optional[str] = None
    recorded_by: Optional[int] = None
    self_reported: bool = False
    employee_name: Optional[str] = None
    recorder_name: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ── Overtime Logs ──────────────────────────────────────────────────

class OvertimeLogResponse(BaseModel):
    id: int
    tenant_id: str
    employee_id: int
    attendance_record_id: int
    date: date
    overtime_minutes: int
    overtime_category_id: Optional[int] = None
    overtime_category_name: Optional[str] = None
    pay_multiplier: Optional[float] = None
    pay_amount: Optional[float] = None
    leave_credits_earned: Optional[float] = None
    status: str
    approved_by: Optional[int] = None
    approved_at: Optional[datetime] = None
    notes: Optional[str] = None
    employee_name: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class OvertimeApproveRequest(BaseModel):
    notes: Optional[str] = None

class OvertimeConvertRequest(BaseModel):
    leave_type: Optional[str] = None
    notes: Optional[str] = None


# ── Tardiness Records ─────────────────────────────────────────────

class TardinessRecordResponse(BaseModel):
    id: int
    tenant_id: str
    employee_id: int
    attendance_record_id: int
    date: date
    tardiness_minutes: int
    resolution_type: Optional[str] = None
    deduction_amount: Optional[float] = None
    leave_credits_deducted: Optional[float] = None
    policy_rule_id: Optional[int] = None
    recorded_by: Optional[int] = None
    notes: Optional[str] = None
    employee_name: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class TardinessResolveRequest(BaseModel):
    resolution_type: str = Field(..., pattern="^(salary_deduction|leave_deduction|excused|warning)$")
    deduction_amount: Optional[float] = None
    leave_type: Optional[str] = None
    notes: Optional[str] = None


# ── Leave Credit Adjustments ──────────────────────────────────────

class LeaveCreditAdjustmentResponse(BaseModel):
    id: int
    tenant_id: str
    employee_id: int
    adjustment_type: str
    leave_type: Optional[str] = None
    credits: float
    source_id: Optional[int] = None
    source_type: Optional[str] = None
    notes: Optional[str] = None
    created_by: Optional[int] = None
    employee_name: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class LeaveCreditAdjustmentCreate(BaseModel):
    employee_id: int
    adjustment_type: str = Field(..., pattern="^(ot_conversion|tardiness_deduction|manual|carry_over)$")
    leave_type: Optional[str] = None
    credits: float
    notes: Optional[str] = None


# ── Time clock ───────────────────────────────────────────────────────────────

class PunchRequest(BaseModel):
    """A clock-in or clock-out.

    `punch_type` is explicit rather than inferred from server state: the intent is
    auditable, and a stale browser tab that disagrees gets a 409 telling it the
    real state instead of silently doing the opposite of what the user pressed.
    """
    punch_type: Literal["in", "out"]
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    accuracy_m: Optional[float] = Field(default=None, ge=0)
    # Why no coordinates came with the punch. Recorded so an operator can tell
    # "the browser refused" from "the site is not on HTTPS so it never asked".
    location_error: Optional[
        Literal["denied", "unavailable", "timeout", "insecure_context"]
    ] = None
    client_time: Optional[datetime] = None
    notes: Optional[str] = None


class PunchLocationRequest(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy_m: Optional[float] = Field(default=None, ge=0)


class TimePunchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    employee_id: int
    business_date: date
    punch_type: str
    shift_id: Optional[int] = None
    work_arrangement: Optional[str] = None
    punched_at: datetime
    local_time: time
    clock_skew_seconds: Optional[int] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    accuracy_m: Optional[float] = None
    location_status: str
    recapture_deadline: Optional[datetime] = None
    geofence_status: str
    work_site_id: Optional[int] = None
    distance_m: Optional[float] = None
    notes: Optional[str] = None


class TimeclockShiftInfo(BaseModel):
    shift_id: int
    sequence_number: int
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    status: str
    work_arrangement: Optional[str] = None
    geofence_mode: str
    work_site_id: Optional[int] = None


class TimeclockTodayResponse(BaseModel):
    timeclock_enabled: bool
    require_location: bool
    grace_minutes: int
    business_date: date
    server_time: datetime
    # 'clock_in' or 'clock_out' — what the button should offer right now.
    next_action: str
    open_punch: Optional[TimePunchResponse] = None
    punches: List[TimePunchResponse] = []
    shifts: List[TimeclockShiftInfo] = []
    hours_today: Optional[float] = None


class WorkSiteCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    code: Optional[str] = Field(default=None, max_length=50)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    radius_m: int = Field(default=200, ge=10, le=100_000)
    address: Optional[str] = None
    org_node_id: Optional[int] = None


class WorkSiteUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    code: Optional[str] = Field(default=None, max_length=50)
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    radius_m: Optional[int] = Field(default=None, ge=10, le=100_000)
    address: Optional[str] = None
    org_node_id: Optional[int] = None
    is_active: Optional[bool] = None


class WorkSiteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    code: Optional[str] = None
    latitude: float
    longitude: float
    radius_m: int
    address: Optional[str] = None
    org_node_id: Optional[int] = None
    is_active: bool


class ArrangementRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    label: str
    geofence_mode: str
    is_active: bool
    sort_order: int


class ArrangementRuleUpdate(BaseModel):
    label: Optional[str] = Field(default=None, max_length=100)
    geofence_mode: Optional[Literal["require_site", "any_location", "record_only"]] = None
    is_active: Optional[bool] = None
