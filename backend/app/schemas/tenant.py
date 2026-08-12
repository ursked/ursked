from datetime import datetime
from typing import Dict, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas.user import UserResponse


class TenantCreate(BaseModel):
    organization_name: str = Field(min_length=2, max_length=200)
    slug: str = Field(min_length=2, max_length=100, pattern=r"^[a-z0-9-]+$")
    admin_email: EmailStr
    admin_password: str = Field(min_length=8)
    admin_first_name: str = Field(min_length=1, max_length=100)
    admin_last_name: str = Field(min_length=1, max_length=100)
    industry: Optional[str] = None
    company_size: Optional[str] = None
    country: Optional[str] = None
    timezone: Optional[str] = None


class TenantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    domain: Optional[str] = None
    email: str
    phone: Optional[str] = None
    industry: Optional[str] = None
    company_size: Optional[str] = None
    country: Optional[str] = None
    timezone: Optional[str] = None
    plan: str
    subscription_status: str
    subscription_ends_at: Optional[datetime] = None
    max_users: int
    max_storage_gb: int
    settings: Optional[Dict] = None
    branding: Optional[Dict] = None
    is_active: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class TenantUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    industry: Optional[str] = None
    company_size: Optional[str] = None
    country: Optional[str] = None
    timezone: Optional[str] = None


class TenantBrandingUpdate(BaseModel):
    logo_url: Optional[str] = None
    primary_color: Optional[str] = None
    secondary_color: Optional[str] = None
    accent_color: Optional[str] = None
    company_name: Optional[str] = None
    support_email: Optional[str] = None


class TenantStatsResponse(BaseModel):
    total_users: int
    active_users: int
    total_departments: int
    total_shifts_this_month: int
    total_leave_pending: int
    storage_used_gb: float


class TenantRegistrationResponse(BaseModel):
    tenant: TenantResponse
    admin_user: UserResponse
    trial_ends_at: datetime


class SlugCheckResponse(BaseModel):
    slug: str
    available: bool
