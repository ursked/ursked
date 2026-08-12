from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ── Employee Types ──────────────────────────────────────────────────────


class EmployeeTypeCreate(BaseModel):
    code: str = Field(max_length=50)
    name: str = Field(max_length=100)
    description: Optional[str] = None
    sort_order: int = 0


class EmployeeTypeUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=100)
    description: Optional[str] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None


class EmployeeTypeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    description: Optional[str] = None
    is_system: bool
    is_active: bool
    sort_order: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ── Schedule Formats ────────────────────────────────────────────────────


class ScheduleFormatCreate(BaseModel):
    code: str = Field(max_length=50)
    name: str = Field(max_length=100)
    hours_per_day: Optional[float] = None
    hours_per_week: Optional[float] = None
    is_flexible: bool = False
    paid_break_minutes: int = 0
    unpaid_break_minutes: int = 0
    paid_break_after_hours: float = 4.0
    unpaid_break_after_hours: float = 4.0
    description: Optional[str] = None
    sort_order: int = 0


class ScheduleFormatUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=100)
    hours_per_day: Optional[float] = None
    hours_per_week: Optional[float] = None
    is_flexible: Optional[bool] = None
    paid_break_minutes: Optional[int] = None
    unpaid_break_minutes: Optional[int] = None
    paid_break_after_hours: Optional[float] = None
    unpaid_break_after_hours: Optional[float] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None


class ScheduleFormatResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    hours_per_day: Optional[float] = None
    hours_per_week: Optional[float] = None
    is_flexible: bool
    paid_break_minutes: int = 0
    unpaid_break_minutes: int = 0
    paid_break_after_hours: float = 4.0
    unpaid_break_after_hours: float = 4.0
    description: Optional[str] = None
    is_system: bool
    is_active: bool
    sort_order: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ── User Org Node ───────────────────────────────────────────────────────


class UserOrgNodeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    org_node_id: int
    is_primary: bool
    assigned_at: Optional[datetime] = None
