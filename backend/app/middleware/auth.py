import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import bcrypt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_db
from app.models.role import UserRole
from app.models.user import User
from app.services.token_store import TokenDenylist

logger = logging.getLogger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


class TokenType:
    ACCESS = "access"
    REFRESH = "refresh"
    TWO_FACTOR = "2fa_pending"


# Precomputed hash of an unguessable value. Verified against when no user is
# found so that the response time of a bad-username attempt matches that of a
# bad-password attempt, closing the user-enumeration timing oracle.
_DUMMY_PASSWORD_HASH = bcrypt.hashpw(uuid.uuid4().hex.encode("utf-8"), bcrypt.gensalt()).decode(
    "utf-8"
)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"), hashed_password.encode("utf-8")
        )
    except (ValueError, TypeError):
        return False


def dummy_verify_password(plain_password: str) -> None:
    """Burn the same CPU as a real bcrypt check. Used on the user-not-found path."""
    bcrypt.checkpw(plain_password.encode("utf-8"), _DUMMY_PASSWORD_HASH.encode("utf-8"))


def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(
        password.encode("utf-8"), bcrypt.gensalt()
    ).decode("utf-8")


def _create_token(data: dict, token_type: str, expires_delta: timedelta) -> str:
    """Build a signed JWT.

    `type` and `jti` are applied last and are not overridable by `data`, so a
    caller cannot accidentally (or maliciously) mint a token of the wrong type.
    """
    now = datetime.now(timezone.utc)
    to_encode = {k: v for k, v in data.items() if k not in {"type", "jti", "iat", "exp"}}
    to_encode.update(
        {
            "exp": now + expires_delta,
            "iat": int(now.timestamp()),
            "jti": uuid.uuid4().hex,
            "type": token_type,
        }
    )
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    return _create_token(
        data,
        TokenType.ACCESS,
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )


def create_refresh_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    return _create_token(
        data,
        TokenType.REFRESH,
        expires_delta or timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )


def create_two_factor_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Short-lived token that proves password authentication only.

    It is NOT an access token: `get_current_user` rejects it, so possession of
    it grants no API access until a valid TOTP code is exchanged for real
    credentials at /auth/2fa/verify.
    """
    return _create_token(
        data,
        TokenType.TWO_FACTOR,
        expires_delta or timedelta(minutes=settings.TWO_FACTOR_TOKEN_EXPIRE_MINUTES),
    )


def decode_token(token: str, expected_type: Optional[str] = None) -> dict:
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if expected_type is not None and payload.get("type") != expected_type:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return payload


def extract_token(request: Request, header_token: Optional[str] = None) -> Optional[str]:
    """Prefer the httpOnly cookie; fall back to a bearer header for API clients."""
    cookie_token = request.cookies.get(settings.ACCESS_COOKIE_NAME)
    if cookie_token:
        return cookie_token
    return header_token


def _tokens_invalidated(user: User, payload: dict) -> bool:
    """True if the user's sessions were globally revoked after this token was issued.

    Resolution is one second, because `iat` is second-granular per RFC 7519.
    A token minted in the same second as the revocation therefore survives.
    That window is deliberate: tightening it would also invalidate the
    replacement session issued during a password change.
    """
    valid_from = getattr(user, "tokens_valid_from", None)
    if not valid_from:
        return False

    issued_at = payload.get("iat")
    if issued_at is None:
        # Legacy token minted before `iat` was added; treat as revoked.
        return True

    if valid_from.tzinfo is None:
        valid_from = valid_from.replace(tzinfo=timezone.utc)

    return issued_at < int(valid_from.timestamp())


async def get_current_user(
    request: Request,
    header_token: Optional[str] = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    token = extract_token(request, header_token)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Enforcing the type here is what stops a refresh token or a 2FA challenge
    # token from being replayed as an access token.
    payload = decode_token(token, expected_type=TokenType.ACCESS)

    jti = payload.get("jti")
    if jti and await TokenDenylist.is_revoked(jti):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked",
        )

    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )

    try:
        user_id = int(user_id)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )

    stmt = (
        select(User)
        .options(
            selectinload(User.two_factor),
            selectinload(User.user_roles).selectinload(UserRole.role),
        )
        .where(User.id == user_id)
    )
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    if _tokens_invalidated(user, payload):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired, please sign in again",
        )

    request.state.token_payload = payload
    return user


def require_role(roles: List[str]):
    """Check if current user has ANY of the specified roles."""
    async def role_checker(current_user: User = Depends(get_current_user)):
        user_codes = set(current_user.role_codes)
        required = set(roles)
        if not user_codes & required:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return current_user

    return role_checker


def require_permission(module: str, action: str):
    """Check if current user has a specific module+action permission via role_permissions table.
    tenant_admin always bypasses.
    action: 'view', 'create', 'edit', 'delete'
    """
    async def permission_checker(
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ):
        # tenant_admin bypasses all permission checks
        if current_user.has_role("tenant_admin"):
            return current_user

        from app.services.permission_service import PermissionService

        role_ids = [ur.role_id for ur in current_user.user_roles]
        allowed = await PermissionService.check_permission(
            db, current_user.tenant_id, role_ids, module, action
        )
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"No {action} permission on {module}",
            )
        return current_user

    return permission_checker


def require_salary_access():
    """Gate cross-employee salary/compensation visibility behind an active 'viewer'
    enrollment. Unlike require_permission, this does NOT bypass tenant_admin — the
    admin must be an enrolled viewer too. (Own-payslip endpoints are intentionally
    left ungated elsewhere.)"""
    async def checker(
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ):
        from app.services.salary_enrollment_service import SalaryEnrollmentService

        if not await SalaryEnrollmentService.is_viewer(
            db, current_user.tenant_id, current_user.id
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Salary access requires enrollment approval.",
            )
        return current_user

    return checker


def require_salary_approver():
    """Gate salary-enrollment management (approve/decline/revoke/list) behind an
    active 'approver' enrollment. Also does NOT bypass tenant_admin."""
    async def checker(
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ):
        from app.services.salary_enrollment_service import SalaryEnrollmentService

        if not await SalaryEnrollmentService.is_approver(
            db, current_user.tenant_id, current_user.id
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only a salary enrollment approver can do this.",
            )
        return current_user

    return checker


def require_extra_permission(permission_key: str):
    """Check if current user has a specific extra permission (e.g. view_salary).
    tenant_admin always bypasses.
    """
    async def checker(
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ):
        if current_user.has_role("tenant_admin"):
            return current_user

        from app.services.permission_service import PermissionService

        role_ids = [ur.role_id for ur in current_user.user_roles]
        allowed = await PermissionService.check_extra_permission(
            db, current_user.tenant_id, role_ids, permission_key
        )
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permission: {permission_key}",
            )
        return current_user

    return checker
