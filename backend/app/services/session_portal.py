"""Which door a session came through, and what that lets it do.

The owner's decision (2026-09): "I am admin and also an employee. If I want to
manage the system, I log in to a separate dashboard. If I want to act as an
employee, I access the employee dashboard." Keeping the two apart means an
administrator doing their everyday things (checking a shift, filing leave)
is not carrying the power to change the whole company while they do it, and a
session left open on a phone is an employee session, not an admin one.

So every sign-in session belongs to one PORTAL, recorded on its user_sessions
row and carried in both tokens:

  employee  The ordinary sign-in page (/auth/login). Always this, for everyone.
            The tenant_admin role is DORMANT: every check in the request
            answers as if the user did not hold it. HR, Finance, managers and
            the rest keep their roles; only tenant_admin is split out, because
            it is the one role that can change everything including who holds
            which role.
  admin     The administrator sign-in page (/admin/login), for tenant_admin
            holders only. Lapses after ADMIN_IDLE without activity and after
            ADMIN_MAX whatever happens. Never reached by refreshing an employee
            session: the portal comes from the row, which only the admin
            sign-in writes.

The choke point is apply_portal(): get_current_user calls it on the request's
user before any endpoint sees it, and User.role_codes / has_role / role_ids all
read the dormant set it leaves. Nothing re-derives roles from user_roles, so
require_role, require_permission (including its tenant_admin bypass),
access_scope, employee_access, leave_access and every inline has_role check get
the same answer without being edited. Stored roles are never touched.

A token that merely CLAIMS the admin portal proves nothing on its own: an
ended admin session's access token stays signed and unexpired for up to 15
minutes. The claim only says "look the row up"; the row decides.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

EMPLOYEE = "employee"
ADMIN = "admin"
PORTALS = (EMPLOYEE, ADMIN)

# The one role split out of the everyday session.
ADMIN_ROLE = "tenant_admin"

ADMIN_IDLE = timedelta(minutes=30)
ADMIN_MAX = timedelta(hours=8)
# Writing last_activity_at on every request of a busy screen would be one
# UPDATE per API call for no gain; a minute's resolution is plenty for a
# 30-minute limit.
SLIDE_EVERY = timedelta(seconds=60)

# Sent by the web client on requests it makes while the person is not using
# the app (background polling after a minute without input). Those must not
# keep an unattended admin session alive, or a dashboard left open on a desk
# would never time out. A client that lies only keeps its own session alive.
IDLE_HEADER = "x-user-idle"

ADMIN_ENDED_DETAIL = "Your admin session ended. Sign in again to continue."
ENDED_HEADER = "X-Session-Ended"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    # SQLite (tests) hands timestamps back naive; they were written as UTC.
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def is_admin_eligible(user) -> bool:
    """Holds tenant_admin, dormant or not: may use the administrator sign-in."""
    return user.holds_role(ADMIN_ROLE)


def has_employee_workspace(user) -> bool:
    """False for a pure administrator account (tenant_admin and nothing else):
    it has no schedule, leave or payslips of its own to show."""
    return bool(set(user.stored_role_codes) - {ADMIN_ROLE})


def apply_portal(user, portal: str) -> None:
    """Set the roles in force for this request. THE choke point; see above."""
    if portal == ADMIN:
        user._dormant_role_codes = frozenset()
        user.in_admin_portal = True
    else:
        user._dormant_role_codes = frozenset({ADMIN_ROLE})
        user.in_admin_portal = False


def idle_expires_at(row) -> Optional[datetime]:
    if row is None or row.portal != ADMIN:
        return None
    last = _aware(row.last_activity_at) or _aware(row.login_at)
    return min(last + ADMIN_IDLE, _aware(row.admin_expires_at))


def admin_session_problem(row, user, now: Optional[datetime] = None) -> Optional[str]:
    """Why this row no longer grants admin, or None while it does."""
    now = now or utcnow()
    if row is None:
        return "missing"
    if row.user_id != user.id or row.portal != ADMIN:
        return "mismatch"
    if row.revoked_at is not None:
        return "revoked"
    if row.admin_expires_at is None or now >= _aware(row.admin_expires_at):
        return "max_age"
    if now >= idle_expires_at(row):
        return "idle"
    if not is_admin_eligible(user):
        # Role removals also invalidate every token (tokens_valid_from); this
        # is the belt to that pair of braces.
        return "not_admin"
    return None


async def session_by_key(db: AsyncSession, sid: Optional[str]):
    from app.models.user import UserSession

    if not sid:
        return None
    return (
        await db.execute(select(UserSession).where(UserSession.session_key == sid))
    ).scalar_one_or_none()


def _claims(user, sid: str, portal: str) -> dict:
    # `roles` is informational (nothing authorizes from it); it lists the
    # roles in force for the portal so a decoded token does not overstate.
    roles = [c for c in user.stored_role_codes if portal == ADMIN or c != ADMIN_ROLE]
    return {
        "sub": str(user.id),
        "tenant_id": str(user.tenant_id),
        "sid": sid,
        "portal": portal,
        "roles": roles,
    }


def _mint(user, sid: str, portal: str) -> Tuple[str, str, dict, dict]:
    from app.middleware.auth import (
        TokenType,
        create_access_token,
        create_refresh_token,
        decode_token,
    )

    claims = _claims(user, sid, portal)
    access = create_access_token(claims)
    refresh = create_refresh_token({k: v for k, v in claims.items() if k != "roles"})
    return (
        access,
        refresh,
        decode_token(access, expected_type=TokenType.ACCESS),
        decode_token(refresh, expected_type=TokenType.REFRESH),
    )


def _session_end(portal: str, now: datetime, refresh_payload: dict) -> datetime:
    end = datetime.fromtimestamp(refresh_payload["exp"], tz=timezone.utc)
    if portal == ADMIN:
        end = min(end, now + ADMIN_MAX)
    return end


async def open_session(
    db: AsyncSession,
    user,
    portal: str,
    *,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
):
    """Start a sign-in session in `portal`. Returns (access, refresh, row).

    The caller has already authenticated the person (password, and the second
    factor when they have one) and, for the admin portal, checked eligibility;
    this re-checks eligibility because an admin session for a non-admin must be
    impossible whatever the caller forgot."""
    from app.models.user import UserSession

    if portal not in PORTALS:
        raise ValueError(f"unknown portal {portal!r}")
    if portal == ADMIN and not is_admin_eligible(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is not an administrator.",
        )
    now = utcnow()
    sid = uuid.uuid4().hex
    access, refresh, access_payload, refresh_payload = _mint(user, sid, portal)
    row = UserSession(
        user_id=user.id,
        tenant_id=user.tenant_id,
        jti=access_payload["jti"],
        session_key=sid,
        portal=portal,
        ip_address=ip_address,
        user_agent=user_agent,
        login_at=now,
        last_activity_at=now,
        expires_at=_session_end(portal, now, refresh_payload),
        admin_expires_at=(now + ADMIN_MAX) if portal == ADMIN else None,
    )
    db.add(row)
    await db.flush()
    return access, refresh, row


async def rotate_session(db: AsyncSession, user, row) -> Tuple[str, str]:
    """New token pair for an existing session (refresh). Same sid, and the
    portal is the ROW's: a refresh can never move a session between doors."""
    now = utcnow()
    access, refresh, access_payload, refresh_payload = _mint(user, row.session_key, row.portal)
    row.jti = access_payload["jti"]
    new_end = _session_end(row.portal, now, refresh_payload)
    if row.portal == ADMIN and row.admin_expires_at is not None:
        new_end = min(new_end, _aware(row.admin_expires_at))
    row.expires_at = new_end
    await db.flush()
    return access, refresh


async def end_session(db: AsyncSession, row, *, reason: str, actor=None, ip: Optional[str] = None) -> None:
    """Revoke a session row and deny-list its current access token. Audits the
    end of admin sessions, which is what a reviewer wants to find."""
    from app.models.site_settings import AuditLog
    from app.services.token_store import TokenDenylist

    if row is None:
        return
    if row.revoked_at is None:
        row.revoked_at = utcnow()
        exp = int(_aware(row.expires_at).timestamp()) if row.expires_at else None
        await TokenDenylist.revoke(row.jti, exp)
        if row.portal == ADMIN:
            db.add(AuditLog(
                tenant_id=row.tenant_id,
                user_id=row.user_id,
                user_email=getattr(actor, "email", None),
                action="admin_session_ended",
                resource_type="user_session",
                resource_id=str(row.id),
                ip_address=ip,
                details={"reason": reason},
            ))
        await db.flush()


async def end_all_sessions(db: AsyncSession, user_id: int, *, reason: str, keep_sid: Optional[str] = None) -> int:
    """Revoke every open session of a user (password change). Returns how many."""
    from app.models.user import UserSession

    rows = (
        await db.execute(
            select(UserSession).where(
                UserSession.user_id == user_id,
                UserSession.revoked_at.is_(None),
            )
        )
    ).scalars().all()
    n = 0
    for row in rows:
        if keep_sid and row.session_key == keep_sid:
            continue
        await end_session(db, row, reason=reason)
        n += 1
    return n


async def resolve_request(db: AsyncSession, user, payload: dict, request: Request) -> str:
    """Decide the portal of an authenticated request and apply it to `user`.

    Called by get_current_user on every request. An employee claim (or no
    claim: tokens minted before admin mode, API clients) needs no lookup,
    because the employee portal is the least a session can be. An admin claim
    is honoured only while its row is live; otherwise the admin session is
    over and the request is refused, so the client can send the person back to
    the administrator sign-in instead of silently carrying on with less.
    """
    request.state.portal_session = None
    if payload.get("portal") != ADMIN or not is_admin_eligible(user):
        if payload.get("portal") == ADMIN:
            # Claims admin but no longer holds the role: end it like any other
            # lapsed admin session.
            row = await session_by_key(db, payload.get("sid"))
            await _refuse_ended(db, row, user, "not_admin", request)
        apply_portal(user, EMPLOYEE)
        request.state.portal = EMPLOYEE
        return EMPLOYEE

    row = await session_by_key(db, payload.get("sid"))
    now = utcnow()
    problem = admin_session_problem(row, user, now)
    if problem:
        await _refuse_ended(db, row, user, problem, request)

    if request.headers.get(IDLE_HEADER) != "1":
        last = _aware(row.last_activity_at)
        if last is None or now - last >= SLIDE_EVERY:
            row.last_activity_at = now
    apply_portal(user, ADMIN)
    request.state.portal = ADMIN
    request.state.portal_session = row
    return ADMIN


async def _refuse_ended(db: AsyncSession, row, user, reason: str, request: Request):
    if row is not None and row.user_id == user.id and row.revoked_at is None:
        await end_session(db, row, reason=reason, actor=user, ip=_ip(request))
        # Commit before refusing: the 401 rolls the request back, which would
        # undo the revocation and the audit entry.
        await db.commit()
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=ADMIN_ENDED_DETAIL,
        headers={ENDED_HEADER: "admin", "WWW-Authenticate": "Bearer"},
    )


def _ip(request: Optional[Request]) -> Optional[str]:
    if request is None:
        return None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def describe(user, request: Request) -> dict:
    """The portal fields of /auth/me and the sign-in responses."""
    portal = getattr(request.state, "portal", EMPLOYEE)
    row = getattr(request.state, "portal_session", None)
    out = {
        "portal": portal,
        "admin_eligible": is_admin_eligible(user),
        "has_employee_workspace": has_employee_workspace(user),
        "expires_at": None,
        "admin_expires_at": None,
        "idle_timeout_seconds": None,
    }
    if portal == ADMIN and row is not None:
        out["expires_at"] = idle_expires_at(row)
        out["admin_expires_at"] = _aware(row.admin_expires_at)
        out["idle_timeout_seconds"] = int(ADMIN_IDLE.total_seconds())
    return out


__all__ = [
    "ADMIN",
    "ADMIN_ENDED_DETAIL",
    "ADMIN_IDLE",
    "ADMIN_MAX",
    "ADMIN_ROLE",
    "EMPLOYEE",
    "IDLE_HEADER",
    "admin_session_problem",
    "apply_portal",
    "describe",
    "end_all_sessions",
    "end_session",
    "has_employee_workspace",
    "is_admin_eligible",
    "open_session",
    "resolve_request",
    "rotate_session",
    "session_by_key",
]
