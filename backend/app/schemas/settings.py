from datetime import time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ── App Settings ─────────────────────────────────────────────────────

class AppSettingsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    timezone: str
    currency_code: str = "PHP"
    date_format: str
    time_format: str
    week_starts_on: str
    default_leave_days: int
    allow_negative_leave: bool
    require_leave_approval: bool
    max_consecutive_leave_days: int
    default_shift_duration_hours: int
    allow_overtime: bool
    max_overtime_hours_per_week: int
    notify_on_leave_request: bool
    notify_on_leave_approval: bool
    notify_on_schedule_change: bool
    schedule_employee_visibility: str = "own_node"
    # ── Payroll computation. Defaults are Philippine statutory rates; every
    # install is expected to set these to its own jurisdiction / agreement.
    working_days_per_month: int = 22
    night_diff_multiplier: float = 1.10
    night_shift_start: Optional[time] = None
    night_shift_end: Optional[time] = None
    holiday_worked_multiplier: float = 2.0
    special_holiday_worked_multiplier: float = 1.3
    # ── Schedule enforcement. 0 = rule disabled.
    max_consecutive_work_days: int = 0
    min_rest_days_per_week: int = 0
    # Generate 'holiday_off' shifts for otherwise-empty calendars on a holiday.
    auto_create_holiday_off: bool = False
    # Separated-employee data lifecycle. null = retain indefinitely.
    data_retention_days: Optional[int] = None
    analytics_exclusion_days: int = 0
    timeclock_enabled: bool = False
    timeclock_require_location: bool = True
    timeclock_location_grace_minutes: int = 60
    timeclock_default_radius_m: int = 200
    custom_settings: Optional[Dict] = None
    # ── Area E (employees): company wording for Personnel #; null = default.
    employee_number_label: Optional[str] = None

    # ── Area L: leave day counting and approval reminders
    work_week_days: List[int] = [0, 1, 2, 3, 4]
    leave_reminder_after_days: int = 2
    leave_escalate_after_days: int = 5

    # ── Area S: working-hour rules. 0 / false = off.
    max_work_hours_per_day: float = 0
    max_work_hours_per_week: float = 0
    min_rest_hours_between_shifts: float = 0
    check_overlapping_shifts: bool = False

    # ── Area F: attendance automation
    auto_clockout_after_hours: float = 4
    auto_clockout_unscheduled_hours: float = 16
    auto_mark_absent: bool = True
    auto_absent_after_minutes: int = 120


class AppSettingsUpdate(BaseModel):
    timezone: Optional[str] = None
    # ISO 4217 uppercase 3-letter code. Curated in the UI with a custom option.
    currency_code: Optional[str] = Field(None, pattern=r"^[A-Z]{3}$")
    date_format: Optional[str] = None
    time_format: Optional[str] = None
    week_starts_on: Optional[str] = Field(None, pattern=r"^(monday|sunday|saturday)$")
    default_leave_days: Optional[int] = None
    allow_negative_leave: Optional[bool] = None
    require_leave_approval: Optional[bool] = None
    max_consecutive_leave_days: Optional[int] = None
    default_shift_duration_hours: Optional[int] = None
    allow_overtime: Optional[bool] = None
    max_overtime_hours_per_week: Optional[int] = None
    notify_on_leave_request: Optional[bool] = None
    notify_on_leave_approval: Optional[bool] = None
    notify_on_schedule_change: Optional[bool] = None
    schedule_employee_visibility: Optional[str] = Field(
        None, pattern=r"^(all|own_node|own_and_children|own_and_parent)$"
    )
    # ── Payroll computation ──
    working_days_per_month: Optional[int] = Field(None, ge=1, le=31)
    # Premiums are applied as hours x rate x (multiplier - 1), so anything below
    # 1.0 would subtract pay. Floor at 1.0 (= no premium) rather than allow that.
    night_diff_multiplier: Optional[float] = Field(None, ge=1.0, le=10.0)
    night_shift_start: Optional[time] = None
    night_shift_end: Optional[time] = None
    holiday_worked_multiplier: Optional[float] = Field(None, ge=1.0, le=10.0)
    special_holiday_worked_multiplier: Optional[float] = Field(None, ge=1.0, le=10.0)
    # ── Schedule enforcement (0 disables the rule) ──
    max_consecutive_work_days: Optional[int] = Field(None, ge=0, le=31)
    min_rest_days_per_week: Optional[int] = Field(None, ge=0, le=7)
    auto_create_holiday_off: Optional[bool] = None
    # null clears the retention policy (retain indefinitely); 1..3650 sets a window.
    data_retention_days: Optional[int] = Field(None, ge=1, le=3650)
    analytics_exclusion_days: Optional[int] = Field(None, ge=0, le=365)
    timeclock_enabled: Optional[bool] = None
    timeclock_require_location: Optional[bool] = None
    # 0 disables recapture. Capped at a day: a grace window longer than a shift
    # would let someone attach a location from an entirely different context.
    timeclock_location_grace_minutes: Optional[int] = Field(None, ge=0, le=1440)
    timeclock_default_radius_m: Optional[int] = Field(None, ge=10, le=100000)
    custom_settings: Optional[Dict] = None
    # ── Area L: leave day counting and approval reminders
    # 0 = Monday ... 6 = Sunday. An empty week would make every unrostered day
    # free, so at least one day is required.
    work_week_days: Optional[List[int]] = Field(None, min_length=1, max_length=7)
    leave_reminder_after_days: Optional[int] = Field(None, ge=1, le=60)
    leave_escalate_after_days: Optional[int] = Field(None, ge=0, le=90)

    @field_validator("work_week_days")
    @classmethod
    def _valid_work_week(cls, v: Optional[List[int]]) -> Optional[List[int]]:
        if v is None:
            return v
        if any(d < 0 or d > 6 for d in v):
            raise ValueError("Working days must be numbers from 0 (Monday) to 6 (Sunday).")
        return sorted(set(v))

    # ── Area S: working-hour rules. 0 turns a limit off.
    max_work_hours_per_day: Optional[float] = Field(None, ge=0, le=24)
    max_work_hours_per_week: Optional[float] = Field(None, ge=0, le=168)
    min_rest_hours_between_shifts: Optional[float] = Field(None, ge=0, le=48)
    check_overlapping_shifts: Optional[bool] = None

    # ── Area F: attendance automation. An open clock-in closes this long after
    # its shift's scheduled end (or after the clock-in, with no shift).
    auto_clockout_after_hours: Optional[float] = Field(None, ge=0.5, le=24)
    auto_clockout_unscheduled_hours: Optional[float] = Field(None, ge=1, le=24)
    auto_mark_absent: Optional[bool] = None
    auto_absent_after_minutes: Optional[int] = Field(None, ge=15, le=1440)


# ── Shift Status Types ───────────────────────────────────────────────

class ShiftStatusTypeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    label: str
    short_label: str
    color: str
    bg_class: str
    category: str
    is_system: bool
    is_active: bool
    sort_order: int


class ShiftStatusTypeCreate(BaseModel):
    code: str = Field(min_length=1, max_length=50, pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(min_length=1, max_length=100)
    short_label: str = Field(min_length=1, max_length=10)
    color: str = Field(min_length=4, max_length=20)
    bg_class: str = Field(min_length=1, max_length=100)
    category: str = Field(pattern=r"^(work|rest|leave)$")
    sort_order: int = 0


class ShiftStatusTypeUpdate(BaseModel):
    label: Optional[str] = Field(None, min_length=1, max_length=100)
    short_label: Optional[str] = Field(None, min_length=1, max_length=10)
    color: Optional[str] = Field(None, min_length=4, max_length=20)
    bg_class: Optional[str] = Field(None, min_length=1, max_length=100)
    category: Optional[str] = Field(None, pattern=r"^(work|rest|leave)$")
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None


# ── User Preferences ────────────────────────────────────────────────

class UserPreferencesResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    preferences: Dict[str, Any]
    # The tenant's timezone (source of truth) — surfaced here so a non-admin can
    # convert schedule times from org tz to their own display tz without needing
    # access to the admin-only app settings.
    org_timezone: Optional[str] = None


class UserPreferencesUpdate(BaseModel):
    """Partial update — merges into existing preferences JSONB."""
    schedule_row_order: Optional[List[int]] = None
    sidebar_collapsed: Optional[bool] = None
    # IANA tz name (e.g. "Asia/Manila") or null/"" = same as organization.
    schedule_timezone: Optional[str] = None
