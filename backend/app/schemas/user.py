import re
from datetime import date, datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.schemas.role import UserRoleResponse


def validate_password_strength(v: str) -> str:
    """The one password rule. Admin-set, imported, activated and self-chosen
    passwords all go through it; before 2026-09 an admin could set a
    one-word 8-letter password that a user could not have chosen themselves."""
    if len(v) < 8:
        raise ValueError("Password must be at least 8 characters long")
    if not re.search(r"[A-Z]", v):
        raise ValueError("Password must contain at least one uppercase letter")
    if not re.search(r"[a-z]", v):
        raise ValueError("Password must contain at least one lowercase letter")
    if not re.search(r"\d", v):
        raise ValueError("Password must contain at least one digit")
    return v


def _required_text(v: Optional[str], label: str) -> str:
    if v is None or not str(v).strip():
        raise ValueError(f"{label} cannot be empty")
    return str(v).strip()


def _optional_text(v: Optional[str]) -> Optional[str]:
    """Blank strings are stored as NULL, so 'clear the field' and 'never set'
    look the same to every reader (exports, uniqueness, search)."""
    if v is None:
        return None
    v = str(v).strip()
    return v or None


# Every write schema forbids unknown keys. The employee form used to send
# typecode, id_number, rank and div_department; the schema did not declare
# them, pydantic dropped them, and the UI said "saved". With extra="forbid" a
# field the backend does not understand is a 422 the developer sees at once,
# not data the user silently loses.
class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _EmployeeFields(_Strict):
    middle_name: Optional[str] = Field(default=None, max_length=100)
    contact_number: Optional[str] = Field(default=None, max_length=50)
    personnel_number: Optional[str] = Field(default=None, max_length=50)
    typecode: Optional[str] = Field(default=None, max_length=50)
    id_number: Optional[str] = Field(default=None, max_length=100)
    rank: Optional[str] = Field(default=None, max_length=100)
    employee_type: Optional[str] = Field(default=None, max_length=50)
    schedule_format: Optional[str] = Field(default=None, max_length=50)
    org_node_id: Optional[int] = None
    job_title: Optional[str] = Field(default=None, max_length=200)
    hiring_date: Optional[date] = None
    reports_to_id: Optional[int] = None
    # {field_key: value}; validated against the tenant's definitions.
    custom_fields: Optional[Dict[str, Any]] = None

    @field_validator(
        "middle_name", "contact_number", "personnel_number", "typecode", "id_number",
        "rank", "employee_type", "schedule_format", "job_title",
    )
    @classmethod
    def _blank_is_null(cls, v):
        return _optional_text(v)


class UserCreate(_EmployeeFields):
    username: Optional[str] = Field(default=None, max_length=80)
    email: EmailStr
    password: Optional[str] = None
    send_invite: bool = True
    first_name: str = Field(max_length=100)
    last_name: str = Field(max_length=100)
    role_codes: List[str] = Field(default_factory=lambda: ["employee"])

    @field_validator("first_name")
    @classmethod
    def _first(cls, v):
        return _required_text(v, "First name")

    @field_validator("last_name")
    @classmethod
    def _last(cls, v):
        return _required_text(v, "Last name")

    @field_validator("email")
    @classmethod
    def _email(cls, v):
        return str(v).strip().lower()

    @field_validator("username")
    @classmethod
    def _username(cls, v):
        return _optional_text(v)

    @field_validator("password")
    @classmethod
    def _password(cls, v):
        if v is None or v == "":
            return None
        return validate_password_strength(v)


class UserUpdate(_EmployeeFields):
    """Edit another employee. Only the keys the client sends are applied
    (exclude_unset), and an explicit null clears an optional field.

    `is_active` is deliberately absent: separate and reinstate are the only
    ways to change it, because they carry the safeguards (not yourself, not
    the last administrator) and the clean-up.
    """

    username: Optional[str] = Field(default=None, max_length=80)
    email: Optional[EmailStr] = None
    first_name: Optional[str] = Field(default=None, max_length=100)
    last_name: Optional[str] = Field(default=None, max_length=100)
    role_codes: Optional[List[str]] = None

    @field_validator("first_name")
    @classmethod
    def _first(cls, v):
        return _required_text(v, "First name")

    @field_validator("last_name")
    @classmethod
    def _last(cls, v):
        return _required_text(v, "Last name")

    @field_validator("username")
    @classmethod
    def _username(cls, v):
        return _required_text(v, "Username")

    @field_validator("email")
    @classmethod
    def _email(cls, v):
        if v is None:
            raise ValueError("Email cannot be empty")
        return str(v).strip().lower()


class UserUpdateProfile(_Strict):
    """What an employee may change about themselves.

    Job title, employee number and the rest are HR data; avatar is not here
    because there is no upload flow, and a free-text avatar let anyone point
    their picture at an arbitrary URL that every colleague's browser fetched.
    """

    first_name: Optional[str] = Field(default=None, max_length=100)
    last_name: Optional[str] = Field(default=None, max_length=100)
    contact_number: Optional[str] = Field(default=None, max_length=50)
    custom_fields: Optional[Dict[str, Any]] = None

    @field_validator("first_name")
    @classmethod
    def _first(cls, v):
        return _required_text(v, "First name")

    @field_validator("last_name")
    @classmethod
    def _last(cls, v):
        return _required_text(v, "Last name")

    @field_validator("contact_number")
    @classmethod
    def _contact(cls, v):
        return _optional_text(v)


class UserSeparateRequest(_Strict):
    separation_type: Literal["resigned", "terminated"]
    separation_date: date
    separation_reason: Optional[str] = Field(default=None, max_length=2000)
    # Shifts dated after the separation date are work nobody will turn up for.
    # The dialog ticks this by default; API callers opt in explicitly.
    delete_future_shifts: bool = False


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: UUID
    username: str
    email: str
    first_name: str
    middle_name: Optional[str] = None
    last_name: str
    avatar: Optional[str] = None
    contact_number: Optional[str] = None
    personnel_number: Optional[str] = None
    typecode: Optional[str] = None
    id_number: Optional[str] = None
    hiring_date: Optional[date] = None
    job_title: Optional[str] = None
    rank: Optional[str] = None
    div_department: Optional[str] = None
    employee_type: Optional[str] = None
    schedule_format: Optional[str] = None
    section_id: Optional[int] = None
    unit_id: Optional[int] = None
    department_id: Optional[int] = None
    division_id: Optional[int] = None
    org_node_id: Optional[int] = None
    reports_to_id: Optional[int] = None
    roles: List[UserRoleResponse] = Field(default_factory=list, validation_alias="user_roles")
    primary_role: str = "employee"
    is_superadmin: bool = False
    is_active: bool = True
    separation_type: Optional[str] = None
    separation_date: Optional[date] = None
    separation_reason: Optional[str] = None
    separated_by: Optional[int] = None
    must_change_password: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # Filled in by the users router (see users._serialize); plain model
    # validation of a User row leaves the defaults.
    org_node_name: Optional[str] = None
    reports_to_name: Optional[str] = None
    invite_pending: bool = False
    invite_expired: bool = False
    custom_fields: Dict[str, Any] = Field(default_factory=dict)

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"


class UserListResponse(BaseModel):
    items: List[UserResponse]
    total: int
    page: int
    per_page: int
    total_pages: int


# ── Bulk edit ────────────────────────────────────────────────────────

class UserBulkFilter(_Strict):
    """'All employees matching the current filter', resolved on the server so
    a selection across pages does not have to ship every id."""

    search: Optional[str] = Field(default=None, max_length=100)
    role: Optional[str] = None
    is_active: Optional[bool] = None
    separation_type: Optional[str] = None
    org_node_id: Optional[int] = None
    custom: Optional[Dict[str, str]] = None


class UserBulkSeparation(_Strict):
    separation_type: Literal["resigned", "terminated"]
    separation_date: date
    separation_reason: Optional[str] = Field(default=None, max_length=2000)
    delete_future_shifts: bool = True


class UserBulkRequest(_Strict):
    action: Literal[
        "set_employee_type",
        "set_schedule_format",
        "set_org_unit",
        "set_reports_to",
        "send_invite",
        "separate",
    ]
    user_ids: Optional[List[int]] = Field(default=None, max_length=5000)
    filter: Optional[UserBulkFilter] = None
    # The new value for set_* actions; null clears (org unit, line manager).
    value: Optional[Any] = None
    separation: Optional[UserBulkSeparation] = None


class UserBulkResult(BaseModel):
    user_id: int
    name: str
    status: Literal["updated", "skipped", "error"]
    message: Optional[str] = None


class UserBulkResponse(BaseModel):
    action: str
    total: int
    updated: int
    skipped: int
    failed: int
    results: List[UserBulkResult]
