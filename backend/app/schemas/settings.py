from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


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
    # Separated-employee data lifecycle. null = retain indefinitely.
    data_retention_days: Optional[int] = None
    analytics_exclusion_days: int = 0
    custom_settings: Optional[Dict] = None


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
    # null clears the retention policy (retain indefinitely); 1..3650 sets a window.
    data_retention_days: Optional[int] = Field(None, ge=1, le=3650)
    analytics_exclusion_days: Optional[int] = Field(None, ge=0, le=365)
    custom_settings: Optional[Dict] = None


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
