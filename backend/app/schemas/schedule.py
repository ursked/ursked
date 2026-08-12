from __future__ import annotations

import datetime as _dt
from datetime import date, datetime, time
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# ── Request Schemas ──────────────────────────────────────────────────

class ShiftCreate(BaseModel):
    employee_id: int
    date: date
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    status: str = "scheduled"
    work_arrangement: Optional[str] = None
    role_name: Optional[str] = None
    color: Optional[str] = None
    notes: Optional[str] = None
    remarks: Optional[str] = None
    # Override forceable guardrail conflicts (consecutive-days / rest-days).
    # Approved-leave overlaps can never be forced.
    force: bool = False


class ShiftUpdate(BaseModel):
    employee_id: Optional[int] = None
    date: Optional[_dt.date] = None
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    status: Optional[str] = None
    work_arrangement: Optional[str] = None
    role_name: Optional[str] = None
    color: Optional[str] = None
    notes: Optional[str] = None
    remarks: Optional[str] = None


class ShiftCopyRequest(BaseModel):
    source_employee_id: int
    source_start_date: date
    source_end_date: date
    target_employee_ids: List[int]
    target_start_date: date


class DateRemarkCreate(BaseModel):
    date: date
    title: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None
    is_holiday: bool = False
    is_special: bool = False
    is_recurring: bool = False


class DateRemarkUpdate(BaseModel):
    date: Optional[date] = None
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = None
    is_holiday: Optional[bool] = None
    is_special: Optional[bool] = None
    is_recurring: Optional[bool] = None


class TemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None
    # A list of per-day entries (index 0 = day 0), each a dict of shift fields
    # (status/start_time/end_time/…). apply_template iterates this list, so it
    # MUST be a list — a bare dict previously type-checked but silently created
    # zero shifts on apply.
    template_data: List[Dict[str, Any]]


class TemplateApply(BaseModel):
    start_date: date
    employee_ids: List[int]


class ShiftBulkCreate(BaseModel):
    employee_ids: List[int]
    start_date: date
    end_date: date
    status: str = "scheduled"
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    work_arrangement: Optional[str] = None
    role_name: Optional[str] = None
    color: Optional[str] = None
    notes: Optional[str] = None
    remarks: Optional[str] = None
    skip_weekends: bool = False
    skip_holidays: bool = False
    skip_days: List[str] = []
    # Override forceable guardrail conflicts. Approved-leave dates are always
    # skipped and reported regardless of this flag.
    force: bool = False


# ── Response Schemas ─────────────────────────────────────────────────

class ShiftResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    employee_id: int
    employee_name: Optional[str] = None
    date: date
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    sequence_number: int = 1
    status: str
    work_arrangement: Optional[str] = None
    role_id: Optional[int] = None
    role_name: Optional[str] = None
    color: Optional[str] = None
    notes: Optional[str] = None
    remarks: Optional[str] = None
    is_published: bool = True


class DateRemarkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    date: date
    title: str
    description: Optional[str] = None
    is_holiday: bool
    is_special: bool
    is_recurring: bool


class TemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: Optional[str] = None
    template_data: List[Dict[str, Any]]
    is_active: bool


class ScheduleConflict(BaseModel):
    employee_id: int
    date: str
    type: str
    forceable: bool
    message: str


class ShiftBulkCreateResponse(BaseModel):
    created: List[ShiftResponse] = []
    skipped_conflicts: List[ScheduleConflict] = []


class ScheduleStatsResponse(BaseModel):
    total_shifts: int = 0
    total_employees: int = 0
    scheduled_count: int = 0
    leave_count: int = 0
    rest_day_count: int = 0


class ScheduleEmployeeResponse(BaseModel):
    employee_id: int
    employee_name: str
    section_name: Optional[str] = None
    unit_name: Optional[str] = None
    shifts: List[ShiftResponse] = []


class ScheduleGridResponse(BaseModel):
    employees: List[ScheduleEmployeeResponse] = []
    dates: List[str] = []
    date_remarks: List[DateRemarkResponse] = []
    stats: ScheduleStatsResponse = ScheduleStatsResponse()


# ── Schedule Change Request Schemas ──────────────────────────────────

class ScheduleChangeRequestCreate(BaseModel):
    request_type: Literal["swap", "change"]
    date: date
    end_date: Optional[date] = None
    target_employee_id: Optional[int] = None
    requested_start_time: Optional[time] = None
    requested_end_time: Optional[time] = None
    requested_status: Optional[str] = None
    requested_work_arrangement: Optional[str] = None
    reason: Optional[str] = None


class ScheduleChangeApprovalStepResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    step_order: int
    step_type: str
    approver_id: Optional[int] = None
    approver_name: str = ""
    status: str
    decided_at: Optional[datetime] = None
    notes: Optional[str] = None


class ScheduleChangeRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    request_type: str
    requester_id: int
    requester_name: str = ""
    date: date
    end_date: Optional[date] = None
    target_employee_id: Optional[int] = None
    target_employee_name: Optional[str] = None
    original_start_time: Optional[time] = None
    original_end_time: Optional[time] = None
    original_status: Optional[str] = None
    target_original_start_time: Optional[time] = None
    target_original_end_time: Optional[time] = None
    target_original_status: Optional[str] = None
    requested_start_time: Optional[time] = None
    requested_end_time: Optional[time] = None
    requested_status: Optional[str] = None
    requested_work_arrangement: Optional[str] = None
    reason: Optional[str] = None
    status: str
    reviewed_by: Optional[int] = None
    reviewer_name: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    reviewer_notes: Optional[str] = None
    approval_steps: List[ScheduleChangeApprovalStepResponse] = []
    current_step: Optional[int] = None
    created_at: Optional[datetime] = None


class ScheduleChangeReviewRequest(BaseModel):
    action: Literal["approve", "reject"]
    notes: Optional[str] = None


# ── Bulk Delete Schemas ──────────────────────────────────────────────

class ShiftBulkDelete(BaseModel):
    start_date: date
    end_date: date
    employee_ids: Optional[List[int]] = None  # None = all employees


# ── Schedule Snapshot Schemas ────────────────────────────────────────

class SnapshotCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None
    start_date: date
    end_date: date
    range_type: str = "week"


class SnapshotApply(BaseModel):
    target_start_date: date
    employee_ids: Optional[List[int]] = None  # None = apply to same employees
    # Repeat the snapshot forward, contiguously (stride = snapshot span), until
    # this date. None = single apply (back-compat).
    repeat_until: Optional[date] = None
    # How to handle a date that already has a shift or breaks a guardrail.
    # Approved-leave dates are ALWAYS skipped regardless.
    on_conflict: str = Field("skip", pattern=r"^(skip|overwrite)$")


class SnapshotPreviewRequest(BaseModel):
    target_start_date: date
    repeat_until: Optional[date] = None
    employee_ids: Optional[List[int]] = None


class SnapshotOccurrence(BaseModel):
    index: int
    start_date: date
    end_date: date


class SnapshotConflict(BaseModel):
    employee_id: int
    employee_name: str
    date: str
    type: str  # approved_leave | existing_shift | max_consecutive_work_days | min_rest_days_per_week
    forceable: bool
    message: str
    has_existing_shift: bool = False


class SnapshotPreviewResponse(BaseModel):
    occurrences: List[SnapshotOccurrence]
    stride_days: int
    total_shifts: int
    create_count: int
    blocking_conflicts: List[SnapshotConflict]      # approved leave — always skipped
    resolvable_conflicts: List[SnapshotConflict]    # user decides skip vs overwrite


class SnapshotSkipped(BaseModel):
    employee_id: int
    date: str
    reason: str
    message: str


class SnapshotApplyResult(BaseModel):
    created: int
    overwritten: int
    skipped: List[SnapshotSkipped]


# ── Copy week ────────────────────────────────────────────────────────
# Reuses SnapshotPreviewResponse / SnapshotApplyResult for the response shapes.

class CopyWeekRequest(BaseModel):
    source_start_date: date
    source_end_date: date
    # Default (None) = the contiguous next window (source_start + span).
    target_start_date: Optional[date] = None
    employee_ids: Optional[List[int]] = None  # None = all visible
    on_conflict: str = Field("skip", pattern=r"^(skip|overwrite)$")


# ── Guardrail lint ───────────────────────────────────────────────────

class ScheduleLintRequest(BaseModel):
    start_date: date
    end_date: date
    employee_ids: Optional[List[int]] = None


class ScheduleLintViolation(BaseModel):
    employee_id: int
    date: str
    type: str  # max_consecutive_work_days | min_rest_days_per_week | approved_leave
    message: str


class ScheduleLintResponse(BaseModel):
    violations: List[ScheduleLintViolation]


# ── Draft / publish ──────────────────────────────────────────────────

class PublishRangeRequest(BaseModel):
    start_date: date
    end_date: date
    employee_ids: Optional[List[int]] = None


class PublishRangeResponse(BaseModel):
    published_count: int
    notified: int


class UnpublishRangeResponse(BaseModel):
    unpublished_count: int


class SnapshotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: Optional[str] = None
    source_start_date: date
    source_end_date: date
    range_type: str
    employee_count: int = 0
    shift_count: int = 0
    is_active: bool = True
    created_by: Optional[int] = None
    created_at: Optional[datetime] = None
