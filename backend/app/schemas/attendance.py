from datetime import date, datetime, time
from typing import List, Optional

from pydantic import BaseModel, Field


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
