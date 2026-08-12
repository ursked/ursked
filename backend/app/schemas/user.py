from datetime import date, datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas.role import UserRoleResponse


class UserCreate(BaseModel):
    tenant_id: Optional[UUID] = None
    username: Optional[str] = None
    email: EmailStr
    password: Optional[str] = Field(default=None, min_length=8)
    send_invite: bool = True
    first_name: str
    last_name: str
    role_codes: List[str] = Field(default_factory=lambda: ["employee"])
    contact_number: Optional[str] = None
    personnel_number: Optional[str] = None
    employee_type: Optional[str] = None
    schedule_format: Optional[str] = None
    department_id: Optional[int] = None
    division_id: Optional[int] = None
    section_id: Optional[int] = None
    unit_id: Optional[int] = None
    job_title: Optional[str] = None
    hiring_date: Optional[date] = None
    reports_to_id: Optional[int] = None


class UserUpdate(BaseModel):
    username: Optional[str] = None
    email: Optional[EmailStr] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    contact_number: Optional[str] = None
    personnel_number: Optional[str] = None
    employee_type: Optional[str] = None
    schedule_format: Optional[str] = None
    department_id: Optional[int] = None
    division_id: Optional[int] = None
    section_id: Optional[int] = None
    unit_id: Optional[int] = None
    job_title: Optional[str] = None
    hiring_date: Optional[date] = None
    is_active: Optional[bool] = None
    reports_to_id: Optional[int] = None
    role_codes: Optional[List[str]] = None


class UserUpdateProfile(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    contact_number: Optional[str] = None
    avatar: Optional[str] = None


class UserSeparateRequest(BaseModel):
    separation_type: str  # resigned, terminated
    separation_date: date
    separation_reason: Optional[str] = None


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: UUID
    username: str
    email: str
    first_name: str
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

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"


class UserListResponse(BaseModel):
    items: List[UserResponse]
    total: int
    page: int
    per_page: int
    total_pages: int


class UserBulkCreate(BaseModel):
    users: List[UserCreate]


class UserBulkResponse(BaseModel):
    success_count: int
    error_count: int
    errors: List[str]
    created_users: List[UserResponse]
