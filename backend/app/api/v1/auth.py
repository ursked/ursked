import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_db
from app.middleware.auth import (
    TokenType,
    create_access_token,
    create_refresh_token,
    create_two_factor_token,
    decode_token,
    dummy_verify_password,
    get_current_user,
    get_password_hash,
    verify_password,
)
from app.middleware.security import (
    clear_auth_cookies,
    set_auth_cookies,
    set_two_factor_cookie,
)
from app.services.token_store import AccountLockout, RateLimiter, TokenDenylist
from app.models.role import UserRole
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.auth import (
    ActivateAccountRequest,
    LoginRequest,
    LoginResponse,
    PasswordChangeRequest,
    TokenRefreshResponse,
    TwoFactorSetupResponse,
    TwoFactorVerifyRequest,
    ValidateTokenResponse,
)
from app.schemas.user import UserResponse
from app.services.auth_service import AuthService
from app.services.email_service import EmailService
from app.services.invite_service import InviteService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])


def _user_with_roles_options():
    """Common selectinload options for user with roles."""
    return [
        selectinload(User.two_factor),
        selectinload(User.user_roles).selectinload(UserRole.role),
    ]


def _client_ip(request: Request) -> str:
    # X-Forwarded-For is only meaningful behind a trusted proxy; the deployment
    # terminates TLS at nginx which sets it. Fall back to the socket peer.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _issue_session(response: Response, user: User) -> str:
    """Mint an access/refresh pair as httpOnly cookies. Returns the CSRF token."""
    access_token = create_access_token(
        data={"sub": str(user.id), "tenant_id": str(user.tenant_id), "roles": user.role_codes}
    )
    refresh_token = create_refresh_token(
        data={"sub": str(user.id), "tenant_id": str(user.tenant_id)}
    )
    return set_auth_cookies(response, access_token, refresh_token)


@router.post("/login", response_model=LoginResponse)
async def login(
    request: LoginRequest,
    http_request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    identifier = request.username.strip().lower()
    ip = _client_ip(http_request)

    if await RateLimiter.hit(
        f"login:ip:{ip}",
        settings.LOGIN_RATE_LIMIT_ATTEMPTS,
        settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS,
    ):
        logger.warning("Login rate limit exceeded for ip=%s", ip)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Please try again later.",
        )

    if await AccountLockout.is_locked(identifier):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Account temporarily locked after repeated failed attempts. "
                f"Try again in {settings.ACCOUNT_LOCKOUT_MINUTES} minutes."
            ),
        )

    stmt = (
        select(User)
        .options(*_user_with_roles_options())
        .where(
            (User.username == request.username) | (User.email == request.username),
            User.is_active == True,
        )
    )
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        # Spend the same time as a real bcrypt comparison so response latency
        # does not reveal whether the account exists.
        dummy_verify_password(request.password)

    if not user or not verify_password(request.password, user.password_hash):
        await AccountLockout.record_failure(identifier)
        logger.warning("Login failed for username=%s ip=%s", request.username, ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    await AccountLockout.clear(identifier)

    # NOTE: `must_change_password` is NOT a login gate. Invited users who have
    # never activated hold a random placeholder password (see
    # InviteService.generate_placeholder_password) that no one knows, so they
    # simply fail the credential check above — there is nothing to special-case.
    # A user who authenticates successfully but still has must_change_password
    # set (e.g. a self-hosted first admin, or an admin-forced reset) IS allowed
    # in, but the client must route them straight to a forced password change;
    # the flag is surfaced on the login response and on /auth/me.

    # 2FA required: issue a challenge token ONLY. It is typed `2fa_pending`, so
    # get_current_user rejects it and it grants no API access on its own.
    if user.two_factor and user.two_factor.status == "enabled" and user.two_factor.totp_verified:
        challenge = create_two_factor_token(
            data={"sub": str(user.id), "tenant_id": str(user.tenant_id)}
        )
        set_two_factor_cookie(response, challenge)
        return LoginResponse(expires_in=0, user=None, requires_2fa=True)

    csrf_token = _issue_session(response, user)
    return LoginResponse(
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=UserResponse.model_validate(user),
        requires_2fa=False,
        csrf_token=csrf_token,
    )


@router.get("/validate-invite-token", response_model=ValidateTokenResponse)
async def validate_invite_token(
    token: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    invite = await InviteService.validate_token(db, token)
    if not invite:
        return ValidateTokenResponse(valid=False)

    # Look up user and tenant for display
    stmt = select(User).where(User.id == invite.user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    tenant_name = None
    if invite.tenant_id:
        t_result = await db.execute(select(Tenant.name).where(Tenant.id == invite.tenant_id))
        tenant_name = t_result.scalar()

    return ValidateTokenResponse(
        valid=True,
        email=user.email if user else None,
        first_name=user.first_name if user else None,
        tenant_name=tenant_name,
    )


@router.post("/activate-account")
async def activate_account(
    data: ActivateAccountRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    invite = await InviteService.validate_token(db, data.token)
    if not invite:
        raise HTTPException(status_code=400, detail="Invalid or expired activation token")

    user = await InviteService.activate_user(db, invite, data.new_password)
    await db.commit()

    # Send account activated confirmation email
    base_url = str(request.base_url).rstrip("/")
    login_url = f"{base_url.replace(':8000', ':3000')}/auth/login"

    EmailService.fire_and_forget(
        lambda db, _email=user.email, _name=user.first_name, _url=login_url:
            EmailService.send_account_activated_email(
                db,
                to_email=_email,
                first_name=_name,
                login_url=_url,
            )
    )

    return {"message": "Account activated successfully. You can now sign in."}


@router.post("/2fa/verify", response_model=LoginResponse)
async def verify_2fa(
    request: TwoFactorVerifyRequest,
    http_request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    challenge = http_request.cookies.get(settings.TWO_FACTOR_COOKIE_NAME)
    if not challenge:
        raise HTTPException(status_code=401, detail="No pending 2FA challenge")

    # Requires the 2fa_pending type specifically: an access or refresh token
    # cannot be substituted here.
    payload = decode_token(challenge, expected_type=TokenType.TWO_FACTOR)

    user_id = int(payload.get("sub"))

    if await RateLimiter.hit(
        f"2fa:{user_id}",
        settings.TWO_FACTOR_RATE_LIMIT_ATTEMPTS,
        settings.TWO_FACTOR_RATE_LIMIT_WINDOW_SECONDS,
    ):
        logger.warning("2FA rate limit exceeded for user_id=%s", user_id)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many verification attempts. Please sign in again.",
        )

    stmt = (
        select(User)
        .options(*_user_with_roles_options())
        .where(User.id == user_id, User.is_active == True)
    )
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    verified = await AuthService.verify_2fa_code(db, user, request.code)
    if not verified:
        raise HTTPException(status_code=401, detail="Invalid 2FA code")

    await RateLimiter.reset(f"2fa:{user_id}")

    # Burn the challenge so it cannot be replayed.
    await TokenDenylist.revoke(payload.get("jti"), payload.get("exp"))
    response.delete_cookie(settings.TWO_FACTOR_COOKIE_NAME, path="/")

    csrf_token = _issue_session(response, user)
    return LoginResponse(
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=UserResponse.model_validate(user),
        requires_2fa=False,
        csrf_token=csrf_token,
    )


@router.post("/refresh", response_model=TokenRefreshResponse)
async def refresh_token(
    http_request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    token = http_request.cookies.get(settings.REFRESH_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="No refresh token")

    payload = decode_token(token, expected_type=TokenType.REFRESH)

    jti = payload.get("jti")
    if jti and await TokenDenylist.is_revoked(jti):
        raise HTTPException(status_code=401, detail="Refresh token has been revoked")

    user_id = int(payload.get("sub"))

    stmt = (
        select(User)
        .options(selectinload(User.user_roles).selectinload(UserRole.role))
        .where(User.id == user_id, User.is_active == True)
    )
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    if user.tokens_valid_from:
        issued_at = payload.get("iat")
        valid_from = user.tokens_valid_from
        if valid_from.tzinfo is None:
            valid_from = valid_from.replace(tzinfo=timezone.utc)
        if issued_at is None or issued_at < int(valid_from.timestamp()):
            raise HTTPException(status_code=401, detail="Session expired, please sign in again")

    # Rotation: the presented refresh token is single-use.
    await TokenDenylist.revoke(jti, payload.get("exp"))

    csrf_token = _issue_session(response, user)
    return TokenRefreshResponse(
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        csrf_token=csrf_token,
    )


@router.post("/logout")
async def logout(http_request: Request, response: Response):
    """Clear cookies and deny-list the presented tokens."""
    for cookie_name, expected in (
        (settings.ACCESS_COOKIE_NAME, TokenType.ACCESS),
        (settings.REFRESH_COOKIE_NAME, TokenType.REFRESH),
    ):
        raw = http_request.cookies.get(cookie_name)
        if not raw:
            continue
        try:
            payload = decode_token(raw, expected_type=expected)
        except HTTPException:
            continue  # already invalid; nothing to revoke
        await TokenDenylist.revoke(payload.get("jti"), payload.get("exp"))

    clear_auth_cookies(response)
    return {"message": "Logged out"}


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    return UserResponse.model_validate(current_user)


@router.post("/2fa/setup", response_model=TwoFactorSetupResponse)
async def setup_2fa(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(User).options(selectinload(User.two_factor)).where(User.id == current_user.id)
    result = await db.execute(stmt)
    user = result.scalar_one()

    setup_data = await AuthService.setup_2fa(db, user)

    # Send 2FA enabled confirmation email (fire-and-forget)
    EmailService.fire_and_forget(
        lambda db: EmailService.send_2fa_enabled_email(
            db,
            to_email=current_user.email,
            first_name=current_user.first_name,
        )
    )

    return TwoFactorSetupResponse(**setup_data)


@router.post("/2fa/disable")
async def disable_2fa(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(User).options(selectinload(User.two_factor)).where(User.id == current_user.id)
    result = await db.execute(stmt)
    user = result.scalar_one()

    success = await AuthService.disable_2fa(db, user)
    if not success:
        raise HTTPException(status_code=400, detail="2FA is not enabled")

    return {"message": "2FA disabled successfully"}


@router.post("/change-password")
async def change_password(
    request: PasswordChangeRequest,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(request.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    current_user.password_hash = get_password_hash(request.new_password)
    # Clearing this both satisfies a forced first-login change (self-hosted first
    # admin) and is harmless otherwise. It is the single place a user rotating
    # their own password lifts the "must change" flag.
    current_user.must_change_password = False
    # Invalidate every existing session, then re-issue one for this device so
    # the caller is not logged out of the browser they just used.
    current_user.tokens_valid_from = datetime.now(timezone.utc)
    await db.flush()

    csrf_token = _issue_session(response, current_user)

    # Send password changed confirmation email (fire-and-forget)
    EmailService.fire_and_forget(
        lambda db: EmailService.send_password_changed_email(
            db,
            to_email=current_user.email,
            first_name=current_user.first_name,
        )
    )

    return {"message": "Password changed successfully", "csrf_token": csrf_token}
