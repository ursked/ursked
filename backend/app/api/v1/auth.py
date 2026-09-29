import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_db
from app.middleware.auth import (
    TokenType,
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
from app.utils.client_ip import client_address, rate_limit_key
from app.models.role import UserRole
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.auth import (
    ActivateAccountRequest,
    ForgotPasswordRequest,
    LoginRequest,
    LoginResponse,
    MeResponse,
    PasswordChangeRequest,
    ResetPasswordRequest,
    SessionResponse,
    TokenRefreshResponse,
    TwoFactorConfirmRequest,
    TwoFactorDisableRequest,
    TwoFactorSetupResponse,
    TwoFactorVerifyRequest,
    ValidateTokenResponse,
)
from app.models.site_settings import AuditLog
from app.services import session_portal
from app.services.auth_service import AuthService
from app.services.email_service import EmailService
from app.services.invite_service import InviteService
from app.services.password_reset_service import PasswordResetService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])


def _user_with_roles_options():
    """Common selectinload options for user with roles."""
    return [
        selectinload(User.two_factor),
        selectinload(User.user_roles).selectinload(UserRole.role),
    ]


def _client_ip(request: Optional[Request]) -> Optional[str]:
    # Only an address a trusted proxy vouches for; see app/utils/client_ip.py
    # for why X-Forwarded-For can no longer be taken from anyone.
    return client_address(request)


async def _frontend_base(db: AsyncSession, http_request: Request) -> str:
    """Best base URL for building user-facing links. Prefers the configured
    SiteSettings.base_url (correct behind a reverse proxy); falls back to the
    request's own base with the API port swapped for the frontend port."""
    from app.models.site_settings import SiteSettings

    result = await db.execute(select(SiteSettings).limit(1))
    site = result.scalar_one_or_none()
    if site and site.base_url:
        return site.base_url.replace(":8000", ":3000").rstrip("/")
    base = str(http_request.base_url).rstrip("/")
    return base.replace(":8000", ":3000")


async def _issue_session(
    response: Response,
    user: User,
    db: AsyncSession,
    request: Request | None = None,
    portal: str = session_portal.EMPLOYEE,
) -> str:
    """Start a sign-in session and set its token pair as httpOnly cookies.
    Returns the CSRF token.

    Every session is recorded as a UserSession row: the "Active sessions"
    profile card lists them, and the row is what says which portal (employee
    or admin) the session belongs to; see app.services.session_portal.
    """
    access_token, refresh_token, row = await session_portal.open_session(
        db,
        user,
        portal,
        ip_address=_client_ip(request) if request else None,
        user_agent=(request.headers.get("user-agent", "")[:500] if request else None),
    )
    # So _me() describes the session just opened, not the one the request
    # came in with (or none, at sign-in).
    session_portal.apply_portal(user, row.portal)
    if request is not None:
        request.state.portal = row.portal
        request.state.portal_session = row
    return set_auth_cookies(response, access_token, refresh_token)


async def _retire_presented_session(http_request: Request, db: AsyncSession) -> None:
    """End the session this browser is carrying before starting another.

    One session per browser: signing in at either door replaces whatever the
    cookies held, so an admin session is never left alive behind a new
    employee one (or the other way round) with nobody watching it.
    """
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
            continue
        await TokenDenylist.revoke(payload.get("jti"), payload.get("exp"))
        row = await session_portal.session_by_key(db, payload.get("sid"))
        if row is not None and str(row.user_id) == str(payload.get("sub")):
            await session_portal.end_session(
                db, row, reason="replaced_by_new_sign_in", ip=_client_ip(http_request)
            )


def _me(user: User, request: Request) -> MeResponse:
    """The user as this session sees them: roles in force, plus the portal."""
    in_force = set(user.role_codes)
    me = MeResponse.model_validate(user)
    return me.model_copy(
        update={
            "roles": [r for r in me.roles if r.role.code in in_force],
            **session_portal.describe(user, request),
        }
    )


async def _password_sign_in(
    request: LoginRequest,
    http_request: Request,
    response: Response,
    db: AsyncSession,
    portal: str,
) -> LoginResponse:
    """Username/email + password sign-in, for either door.

    `portal` is the door: session_portal.EMPLOYEE for /auth/login (everyone,
    always an employee session), ADMIN for /auth/admin/login (tenant_admin
    holders only) or FINANCE for /auth/finance/login (finance holders only).
    Every door shares the account lockout, since guessing a password at one
    door is guessing it at all of them; each has its own per-IP limit so a
    privileged door cannot be used to lock people out of the others.
    """
    identifier = request.username.strip().lower()
    ip = _client_ip(http_request)
    is_privileged_door = portal in session_portal.PRIVILEGED
    audit_extra = {"portal": portal} if is_privileged_door else {}

    limit_key, per_address = rate_limit_key(
        f"{portal + '-login' if is_privileged_door else 'login'}", http_request
    )
    if await RateLimiter.hit(
        limit_key,
        settings.LOGIN_RATE_LIMIT_ATTEMPTS if per_address else settings.LOGIN_RATE_LIMIT_GLOBAL_ATTEMPTS,
        settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS,
    ):
        logger.warning("Login rate limit exceeded for ip=%s portal=%s", ip, portal)
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

    # Case-insensitive on both username and email (audit E-16): emails are
    # stored lowercased now, but older rows and usernames may not be, and
    # "Ana@X.com" typed on a phone keyboard must still sign in. More than one
    # row can match (the same email in two tenants, or two usernames that
    # differ only by case); the password decides which account is meant,
    # instead of scalar_one_or_none() raising a 500.
    stmt = (
        select(User)
        .options(*_user_with_roles_options())
        .where(
            (func.lower(User.username) == identifier) | (func.lower(User.email) == identifier),
            User.is_active == True,
        )
        .order_by(User.id)
    )
    result = await db.execute(stmt)
    candidates = list(result.scalars().all())
    user = None
    for candidate in candidates:
        if verify_password(request.password, candidate.password_hash):
            user = candidate
            break

    if not candidates:
        # Spend the same time as a real bcrypt comparison so response latency
        # does not reveal whether the account exists.
        dummy_verify_password(request.password)

    if user is None:
        # For the audit entry and the lockout alert: the account the attempt
        # was aimed at, if any.
        user = candidates[0] if candidates else None
        just_locked = await AccountLockout.record_failure(identifier)
        logger.warning("Login failed for username=%s ip=%s", request.username, ip)
        # Record the failed attempt in the audit log so a tenant admin can review.
        db.add(AuditLog(
            tenant_id=user.tenant_id if user else None,
            user_id=user.id if user else None,
            user_email=request.username,
            action="login_failure",
            ip_address=ip,
            user_agent=http_request.headers.get("user-agent", "")[:500],
            details={"reason": "invalid_credentials", **audit_extra},
        ))
        await db.flush()
        # If this failure just tripped the lockout AND the account exists, alert
        # the real owner. The send is fire-and-forget (off the response path), so
        # it does not add a timing oracle for account existence.
        if just_locked and user and user.email:
            when = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            EmailService.fire_and_forget(
                lambda db, to=user.email, name=user.first_name, addr=ip, ts=when:
                    EmailService.send_security_alert_email(
                        db,
                        to_email=to,
                        first_name=name,
                        event=(
                            "Your account was temporarily locked after several failed "
                            "sign-in attempts."
                        ),
                        ip_address=addr,
                        when=ts,
                        log_type="account_locked",
                    )
            )
        # Commit before refusing: the 401 below rolls the request back, which
        # used to discard the login_failure audit row (the live install had
        # none at all) and would now also discard the queued lockout alert.
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    if is_privileged_door and not session_portal.is_eligible(user, portal):
        # Only after the password proved who is asking, so a privileged door
        # does not tell a stranger which accounts are administrators or in
        # Finance. Audited like a failed sign-in; the IP limit above already
        # counted it.
        db.add(AuditLog(
            tenant_id=user.tenant_id,
            user_id=user.id,
            user_email=user.email,
            action="login_failure",
            ip_address=ip,
            user_agent=http_request.headers.get("user-agent", "")[:500],
            details={"reason": "not_admin" if portal == session_portal.ADMIN else "not_finance", **audit_extra},
        ))
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=session_portal.NOT_ELIGIBLE_DETAIL[portal],
        )

    await AccountLockout.clear(identifier)

    # Record successful login in the audit log.
    db.add(AuditLog(
        tenant_id=user.tenant_id,
        user_id=user.id,
        user_email=user.email,
        action="login_success",
        ip_address=ip,
        user_agent=http_request.headers.get("user-agent", "")[:500],
        details=audit_extra or None,
    ))
    await db.flush()

    # NOTE: `must_change_password` is NOT a login gate. Invited users who have
    # never activated hold a random placeholder password (see
    # InviteService.generate_placeholder_password) that no one knows, so they
    # simply fail the credential check above — there is nothing to special-case.
    # A user who authenticates successfully but still has must_change_password
    # set (e.g. a self-hosted first admin, or an admin-forced reset) IS allowed
    # in, but the client must route them straight to a forced password change;
    # the flag is surfaced on the login response and on /auth/me.

    # 2FA required: issue a challenge token ONLY. It is typed `2fa_pending`, so
    # get_current_user rejects it and it grants no API access on its own. It
    # carries the door, so /2fa/verify opens the session the person asked for.
    if user.two_factor and user.two_factor.status == "enabled" and user.two_factor.totp_verified:
        challenge = create_two_factor_token(
            data={"sub": str(user.id), "tenant_id": str(user.tenant_id), "portal": portal}
        )
        set_two_factor_cookie(response, challenge)
        return LoginResponse(expires_in=0, user=None, requires_2fa=True)

    await _retire_presented_session(http_request, db)
    csrf_token = await _issue_session(response, user, db, request=http_request, portal=portal)
    return LoginResponse(
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=_me(user, http_request),
        requires_2fa=False,
        csrf_token=csrf_token,
    )


@router.post("/login", response_model=LoginResponse)
async def login(
    request: LoginRequest,
    http_request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """The ordinary sign-in page. Always an EMPLOYEE session, administrators
    included: their tenant_admin role is dormant in it (admin mode)."""
    return await _password_sign_in(request, http_request, response, db, session_portal.EMPLOYEE)


@router.post("/admin/login", response_model=LoginResponse)
async def admin_login(
    request: LoginRequest,
    http_request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """The administrator sign-in page. Opens an ADMIN session (30 idle minutes,
    8 hours at most) for tenant_admin holders; anyone else is refused after
    their password is checked. The only way into the admin portal: no endpoint
    turns an employee session into an admin one."""
    return await _password_sign_in(request, http_request, response, db, session_portal.ADMIN)


@router.post("/finance/login", response_model=LoginResponse)
async def finance_login(
    request: LoginRequest,
    http_request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """The finance sign-in page. Opens a FINANCE session (30 idle minutes, 8
    hours at most) for holders of the finance role; anyone else is refused
    after their password is checked. The finance role is dormant in every
    other session, so this is the only way to manage finances. The admin door
    never grants finance, nor this door administration."""
    return await _password_sign_in(request, http_request, response, db, session_portal.FINANCE)


async def _exit_privileged(
    http_request: Request,
    response: Response,
    current_user: User,
    db: AsyncSession,
    portal: str,
) -> LoginResponse:
    """End this admin or finance session and sign the same person into an
    employee session without asking for the password again. Safe because it
    only ever lowers what the browser can do; the way up is always that
    door's sign-in."""
    if getattr(http_request.state, "portal", None) != portal:
        raise HTTPException(
            status_code=400,
            detail=f"This is not {'an admin' if portal == session_portal.ADMIN else 'a finance'} session.",
        )
    row = http_request.state.portal_session
    await session_portal.end_session(
        db, row, reason="switched_to_employee", actor=current_user, ip=_client_ip(http_request)
    )
    refresh_raw = http_request.cookies.get(settings.REFRESH_COOKIE_NAME)
    if refresh_raw:
        try:
            payload = decode_token(refresh_raw, expected_type=TokenType.REFRESH)
            await TokenDenylist.revoke(payload.get("jti"), payload.get("exp"))
        except HTTPException:
            pass
    csrf_token = await _issue_session(
        response, current_user, db, request=http_request, portal=session_portal.EMPLOYEE
    )
    return LoginResponse(
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=_me(current_user, http_request),
        requires_2fa=False,
        csrf_token=csrf_token,
    )


@router.post("/admin/exit", response_model=LoginResponse)
async def exit_admin_session(
    http_request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """"Go to my employee dashboard" from the admin dashboard."""
    return await _exit_privileged(http_request, response, current_user, db, session_portal.ADMIN)


@router.post("/finance/exit", response_model=LoginResponse)
async def exit_finance_session(
    http_request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """"Go to my employee dashboard" from the finance dashboard."""
    return await _exit_privileged(http_request, response, current_user, db, session_portal.FINANCE)


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


# Identical message for any address — never reveal whether an account exists.
_FORGOT_PASSWORD_MESSAGE = (
    "If an account exists for that address, we've sent a password reset link."
)


@router.post("/forgot-password")
async def forgot_password(
    data: ForgotPasswordRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Begin a password reset. Always returns the same message and status so it
    cannot be used to enumerate accounts."""
    email = (data.email or "").strip().lower()

    # Rate-limit per address AND per IP so this can't be used to mailbomb someone
    # or to brute the address space. Over-limit still returns the neutral message.
    reset_key, per_address = rate_limit_key("pwreset", http_request)
    over_ip = await RateLimiter.hit(
        reset_key,
        settings.PASSWORD_RESET_RATE_LIMIT_ATTEMPTS if per_address
        else settings.PASSWORD_RESET_RATE_LIMIT_GLOBAL_ATTEMPTS,
        settings.PASSWORD_RESET_RATE_LIMIT_WINDOW_SECONDS,
    )
    over_email = await RateLimiter.hit(
        f"pwreset:email:{email}",
        settings.PASSWORD_RESET_RATE_LIMIT_ATTEMPTS,
        settings.PASSWORD_RESET_RATE_LIMIT_WINDOW_SECONDS,
    )
    if not over_ip and not over_email:
        try:
            frontend_base = await _frontend_base(db, http_request)
            await PasswordResetService.request_reset(db, email, frontend_base)
        except Exception:
            # Never surface internal errors here — that would be an oracle too.
            logger.exception("forgot-password processing failed for a request")

    return {"message": _FORGOT_PASSWORD_MESSAGE}


@router.get("/validate-reset-token", response_model=ValidateTokenResponse)
async def validate_reset_token(
    token: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    valid = await PasswordResetService.validate_token(db, token)
    return ValidateTokenResponse(valid=valid)


@router.post("/reset-password")
async def reset_password(
    data: ResetPasswordRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Complete a password reset with a valid token. Cap attempts to keep the
    token space from being brute-forced."""
    verify_key, per_address = rate_limit_key("pwreset-verify", http_request)
    if await RateLimiter.hit(
        verify_key,
        settings.LOGIN_RATE_LIMIT_ATTEMPTS if per_address else settings.LOGIN_RATE_LIMIT_GLOBAL_ATTEMPTS,
        settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS,
    ):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Please request a new reset link.",
        )

    ok = await PasswordResetService.complete_reset(db, data.token, data.new_password)
    if not ok:
        raise HTTPException(
            status_code=400,
            detail="This password reset link is invalid or has expired. Please request a new one.",
        )
    return {"message": "Your password has been reset. You can now sign in."}


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

    # The door the password was given at (signed into the challenge). A
    # challenge minted before admin mode carries none: employee.
    portal = payload.get("portal")
    if portal not in session_portal.PRIVILEGED:
        portal = session_portal.EMPLOYEE
    if portal in session_portal.PRIVILEGED and not session_portal.is_eligible(user, portal):
        raise HTTPException(status_code=403, detail=session_portal.NOT_ELIGIBLE_DETAIL[portal])

    await _retire_presented_session(http_request, db)
    csrf_token = await _issue_session(response, user, db, request=http_request, portal=portal)
    return LoginResponse(
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=_me(user, http_request),
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

    # Admin mode: a refresh continues the SAME session, in the portal its row
    # records. The refresh token's own portal claim is ignored, so no refresh
    # can turn an employee session into an admin or finance one, and an ended
    # privileged session cannot be revived by refreshing.
    sid = payload.get("sid")
    row = await session_portal.session_by_key(db, sid) if sid else None
    if sid and (row is None or row.user_id != user.id or row.revoked_at is not None):
        raise HTTPException(status_code=401, detail="Session expired, please sign in again")
    if row is not None and row.portal in session_portal.PRIVILEGED:
        problem = session_portal.session_problem(row, user)
        if problem:
            await session_portal.end_session(
                db, row, reason=problem, actor=user, ip=_client_ip(http_request)
            )
            await db.commit()
            raise HTTPException(
                status_code=401,
                detail=session_portal.ENDED_DETAIL[row.portal],
                headers={"X-Session-Ended": row.portal},
            )

    # Rotation: the presented refresh token is single-use.
    await TokenDenylist.revoke(jti, payload.get("exp"))

    if row is None:
        # A refresh token from before admin mode (no sid): start a recorded
        # employee session in its place.
        csrf_token = await _issue_session(response, user, db, request=http_request)
    else:
        access_token, new_refresh = await session_portal.rotate_session(db, user, row)
        csrf_token = set_auth_cookies(response, access_token, new_refresh)
    return TokenRefreshResponse(
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        csrf_token=csrf_token,
    )


@router.post("/logout")
async def logout(
    http_request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Clear cookies, deny-list the presented tokens, and mark the session
    revoked (which also ends an admin session: see session_portal)."""
    from app.models.user import UserSession

    now = datetime.now(timezone.utc)
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
        jti = payload.get("jti")
        await TokenDenylist.revoke(jti, payload.get("exp"))
        # Mark the persistent session row as revoked (if it exists): by its
        # sid, which both tokens carry, or by the JTI for pre-admin-mode rows.
        session = await session_portal.session_by_key(db, payload.get("sid"))
        if session is None and expected == TokenType.ACCESS and jti:
            result = await db.execute(
                select(UserSession).where(UserSession.jti == jti)
            )
            session = result.scalar_one_or_none()
        if session is not None and str(session.user_id) == str(payload.get("sub")):
            if session.portal in session_portal.PRIVILEGED:
                await session_portal.end_session(
                    db, session, reason="signed_out", ip=_client_ip(http_request)
                )
            elif session.revoked_at is None:
                session.revoked_at = now

    await db.commit()
    clear_auth_cookies(response)
    return {"message": "Logged out"}


@router.get("/me", response_model=MeResponse)
async def get_me(request: Request, current_user: User = Depends(get_current_user)):
    """Who is signed in, the roles in force for this session and its portal
    (admin mode). The web client picks the employee or admin workspace from
    `portal`; the server enforces the difference regardless."""
    return _me(current_user, request)


@router.get("/2fa/status")
async def two_factor_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Whether two-factor sign-in is on for the caller, and how many unused
    recovery codes remain (the codes themselves are only ever shown once)."""
    stmt = (
        select(User).options(selectinload(User.two_factor)).where(User.id == current_user.id)
        .execution_options(populate_existing=True)
    )
    user = (await db.execute(stmt)).scalar_one()
    tf = user.two_factor
    enabled = bool(tf and tf.status == "enabled" and tf.totp_verified)
    return {
        "enabled": enabled,
        "pending_setup": bool(tf and tf.status == "pending_setup"),
        "recovery_codes_remaining": len(tf.backup_codes or []) if enabled else 0,
    }


@router.post("/2fa/setup", response_model=TwoFactorSetupResponse)
async def setup_2fa(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Start enrolment: a new secret, QR code and recovery codes. Nothing is
    switched on until /2fa/confirm proves the authenticator app works, so a
    half-finished setup can never lock anyone out."""
    stmt = (
        select(User).options(selectinload(User.two_factor)).where(User.id == current_user.id)
        .execution_options(populate_existing=True)
    )
    result = await db.execute(stmt)
    user = result.scalar_one()

    tf = user.two_factor
    if tf and tf.status == "enabled" and tf.totp_verified:
        raise HTTPException(
            status_code=400,
            detail="Two-factor sign-in is already on. Turn it off first to set up a new device.",
        )

    setup_data = await AuthService.setup_2fa(db, user)
    return TwoFactorSetupResponse(**setup_data)


@router.post("/2fa/confirm")
async def confirm_2fa(
    body: TwoFactorConfirmRequest,
    http_request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Finish enrolment with a code from the authenticator app.

    Before this existed nothing ever moved a setup from pending to enabled
    outside the sign-in flow, and sign-in only asks for a code once enabled,
    so two-factor could not actually be turned on.
    """
    if await RateLimiter.hit(
        f"2fa-confirm:{current_user.id}",
        settings.TWO_FACTOR_RATE_LIMIT_ATTEMPTS,
        settings.TWO_FACTOR_RATE_LIMIT_WINDOW_SECONDS,
    ):
        raise HTTPException(status_code=429, detail="Too many attempts. Wait a few minutes and try again.")
    stmt = (
        select(User).options(selectinload(User.two_factor)).where(User.id == current_user.id)
        .execution_options(populate_existing=True)
    )
    user = (await db.execute(stmt)).scalar_one()
    tf = user.two_factor
    if not tf or tf.status != "pending_setup" or not tf.totp_secret:
        raise HTTPException(status_code=400, detail="Start two-factor setup first.")
    # Only a live TOTP code confirms: a recovery code proves nothing about the app.
    import pyotp

    if not pyotp.TOTP(tf.totp_secret).verify(body.code.strip().replace(" ", ""), valid_window=1):
        raise HTTPException(status_code=400, detail="That code is not correct. Check the time on your phone and try again.")
    tf.status = "enabled"
    tf.totp_verified = True
    db.add(AuditLog(
        tenant_id=user.tenant_id, user_id=user.id, user_email=user.email,
        action="two_factor_enabled", resource_type="user", resource_id=str(user.id),
        ip_address=_client_ip(http_request),
    ))
    await db.flush()

    EmailService.fire_and_forget(
        lambda db, to=user.email, name=user.first_name: EmailService.send_2fa_enabled_email(
            db, to_email=to, first_name=name,
        )
    )
    return {"message": "Two-factor sign-in is on.", "recovery_codes_remaining": len(tf.backup_codes or [])}


@router.post("/2fa/disable")
async def disable_2fa(
    body: TwoFactorDisableRequest,
    http_request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Turn two-factor off. Needs the account password, so a session left open
    on someone else's screen cannot quietly remove the second factor."""
    if await RateLimiter.hit(
        f"2fa-disable:{current_user.id}",
        settings.TWO_FACTOR_RATE_LIMIT_ATTEMPTS,
        settings.TWO_FACTOR_RATE_LIMIT_WINDOW_SECONDS,
    ):
        raise HTTPException(status_code=429, detail="Too many attempts. Wait a few minutes and try again.")
    if not verify_password(body.password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Your password is not correct.")

    stmt = (
        select(User).options(selectinload(User.two_factor)).where(User.id == current_user.id)
        .execution_options(populate_existing=True)
    )
    result = await db.execute(stmt)
    user = result.scalar_one()

    was_enabled = bool(user.two_factor and user.two_factor.status == "enabled")
    success = await AuthService.disable_2fa(db, user)
    if not success:
        raise HTTPException(status_code=400, detail="2FA is not enabled")
    if was_enabled:
        db.add(AuditLog(
            tenant_id=user.tenant_id, user_id=user.id, user_email=user.email,
            action="two_factor_disabled", resource_type="user", resource_id=str(user.id),
            ip_address=_client_ip(http_request),
        ))
        await db.flush()

    return {"message": "2FA disabled successfully"}


@router.post("/change-password")
async def change_password(
    request: PasswordChangeRequest,
    http_request: Request,
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
    # Admin mode: a password change ends every session, admin ones included,
    # and the replacement for this browser is an EMPLOYEE session. Changing a
    # password is exactly when an admin session should have to be re-earned
    # at the administrator sign-in.
    await session_portal.end_all_sessions(db, current_user.id, reason="password_changed")

    csrf_token = await _issue_session(response, current_user, db, request=http_request)

    # Send password changed confirmation email (fire-and-forget)
    EmailService.fire_and_forget(
        lambda db: EmailService.send_password_changed_email(
            db,
            to_email=current_user.email,
            first_name=current_user.first_name,
        )
    )

    return {"message": "Password changed successfully", "csrf_token": csrf_token}


# ── Sessions ─────────────────────────────────────────────────────────

@router.get("/sessions", response_model=list[SessionResponse])
async def list_sessions(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List the current user's active (non-revoked, non-expired) sessions.

    CE scope: users see their OWN sessions only. The session matching the
    caller's current token is flagged `is_current=True`.
    """
    from app.models.user import UserSession

    now = datetime.now(timezone.utc)
    stmt = (
        select(UserSession)
        .where(
            UserSession.user_id == current_user.id,
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > now,
        )
        .order_by(UserSession.login_at.desc())
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()

    payload = getattr(request.state, "token_payload", {})
    current_jti = payload.get("jti")
    current_sid = payload.get("sid")

    return [
        SessionResponse(
            id=s.id,
            ip_address=s.ip_address,
            user_agent=s.user_agent,
            login_at=s.login_at.isoformat() if s.login_at else None,
            last_activity_at=s.last_activity_at.isoformat() if s.last_activity_at else None,
            is_current=(s.session_key == current_sid) if current_sid else (s.jti == current_jti),
            portal=s.portal or "employee",
        )
        for s in rows
    ]


@router.delete("/sessions/{session_id}", status_code=204)
async def revoke_session(
    session_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Revoke a specific session (sign it out). Users can only revoke their own."""
    from app.models.user import UserSession

    stmt = select(UserSession).where(
        UserSession.id == session_id,
        UserSession.user_id == current_user.id,
        UserSession.revoked_at.is_(None),
    )
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Marks it revoked and deny-lists its current access token so it is
    # rejected at once. /auth/refresh checks the row, so its refresh token
    # dies with it, and an admin session revoked here is over for good.
    await session_portal.end_session(
        db, session, reason="revoked_by_user", actor=current_user, ip=_client_ip(request)
    )
    await db.commit()


# ── Login Events ─────────────────────────────────────────────────────

@router.get("/login-events")
async def list_login_events(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    mine: bool = Query(False, description="Only my own sign-ins (always true for non-admins)"),
):
    """Recent sign-in successes and failures.

    Everyone may see their own (My Profile > Security: "was that me?"); a
    tenant admin may also see the whole tenant's. Failed attempts are matched
    to an account only when the account exists, so this never reveals which
    usernames someone tried.

    EE scope (not built): cross-tenant security dashboard.
    """
    from sqlalchemy import func

    base = select(AuditLog).where(
        AuditLog.tenant_id == current_user.tenant_id,
        AuditLog.action.in_(["login_success", "login_failure"]),
    )
    if mine or not current_user.has_role("tenant_admin"):
        base = base.where(AuditLog.user_id == current_user.id)

    total = await db.scalar(select(func.count()).select_from(base.subquery()))

    stmt = (
        base
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()

    return {
        "items": [
            {
                "id": r.id,
                "user_email": r.user_email,
                "action": r.action,
                "ip_address": r.ip_address,
                "user_agent": r.user_agent,
                "details": r.details,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
    }
