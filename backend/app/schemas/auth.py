import re
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from app.schemas.user import UserResponse


class LoginRequest(BaseModel):
    username: str
    password: str
    remember_device: bool = False
    device_token: Optional[str] = None


class MeResponse(UserResponse):
    """The signed-in user as this session sees them (admin mode).

    `roles` lists the roles IN FORCE for this session, so a client deciding
    what to show from it cannot offer admin screens in an employee session.
    `admin_eligible` says whether the account holds tenant_admin at all (the
    administrator sign-in link is offered on that); `finance_eligible` the same
    for the finance role and the finance sign-in. `portal` is "employee",
    "admin" or "finance". For an admin or finance session, `expires_at` is when
    it ends if nothing else happens (the idle limit or the absolute cap,
    whichever is sooner) and `admin_expires_at` the cap itself (the name
    predates the finance door; it is the cap of either).
    """

    portal: str = "employee"
    admin_eligible: bool = False
    finance_eligible: bool = False
    has_employee_workspace: bool = True
    expires_at: Optional[datetime] = None
    admin_expires_at: Optional[datetime] = None
    idle_timeout_seconds: Optional[int] = None


class LoginResponse(BaseModel):
    """Tokens are delivered as httpOnly cookies, never in the body.

    `csrf_token` is the value the client must echo back in the X-CSRF-Token
    header on state-changing requests. It is not a credential by itself.
    """

    expires_in: int
    user: Optional[MeResponse] = None
    requires_2fa: bool = False
    csrf_token: Optional[str] = None


class TokenRefreshResponse(BaseModel):
    expires_in: int
    csrf_token: str


class TwoFactorSetupResponse(BaseModel):
    secret: str
    qr_code_uri: str
    qr_code_base64: str
    backup_codes: List[str]


class TwoFactorVerifyRequest(BaseModel):
    code: str
    remember_device: bool = False


class TwoFactorConfirmRequest(BaseModel):
    code: str = Field(min_length=6, max_length=12)


class TwoFactorDisableRequest(BaseModel):
    password: str = Field(min_length=1, max_length=200)


class ActivateAccountRequest(BaseModel):
    token: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_activate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one digit")
        return v


class ValidateTokenResponse(BaseModel):
    valid: bool
    email: Optional[str] = None
    first_name: Optional[str] = None
    tenant_name: Optional[str] = None


def _validate_strong_password(v: str) -> str:
    if len(v) < 8:
        raise ValueError("Password must be at least 8 characters long")
    if not re.search(r"[A-Z]", v):
        raise ValueError("Password must contain at least one uppercase letter")
    if not re.search(r"[a-z]", v):
        raise ValueError("Password must contain at least one lowercase letter")
    if not re.search(r"\d", v):
        raise ValueError("Password must contain at least one digit")
    return v


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        return _validate_strong_password(v)


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        return _validate_strong_password(v)


class SessionResponse(BaseModel):
    """Active-session summary for the "Sessions" profile card."""
    id: int
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    login_at: Optional[str] = None
    last_activity_at: Optional[str] = None
    is_current: bool = False
    # "employee" or "admin" (admin mode): which sign-in page opened it.
    portal: str = "employee"

    model_config = {"from_attributes": True}
