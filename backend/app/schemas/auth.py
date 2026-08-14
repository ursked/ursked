import re
from typing import List, Optional

from pydantic import BaseModel, field_validator

from app.schemas.user import UserResponse


class LoginRequest(BaseModel):
    username: str
    password: str
    remember_device: bool = False
    device_token: Optional[str] = None


class LoginResponse(BaseModel):
    """Tokens are delivered as httpOnly cookies, never in the body.

    `csrf_token` is the value the client must echo back in the X-CSRF-Token
    header on state-changing requests. It is not a credential by itself.
    """

    expires_in: int
    user: Optional[UserResponse] = None
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

    model_config = {"from_attributes": True}
