"""Which door a session came through, and what that lets it do.

The owner's decisions (2026-09): "I am admin and also an employee. If I want to
manage the system, I log in to a separate dashboard. If I want to act as an
employee, I access the employee dashboard." And a day later: "A manager for
graphics is not an administrator of the app ... Finance employees manage
finances on a separate dashboard too." Keeping the doors apart means someone
doing their everyday things (checking a shift, approving their team's leave)
is not carrying the power to change the whole company or its payroll while
they do it, and a session left open on a phone is an employee session.

So every sign-in session belongs to one PORTAL, recorded on its user_sessions
row and carried in both tokens:

  employee  The ordinary sign-in page (/auth/login). Always this, for everyone.
            tenant_admin and finance are DORMANT: every check in the request
            answers as if the user did not hold them. Everything else (HR,
            managers, schedule editors, leave approvers, reports & data) is
            in force: the day-to-day work of the company is done here.
  admin     The administrator sign-in page (/admin/login), for tenant_admin
            holders only. tenant_admin is in force and every other role but
            the base employee role is dormant, so an admin session
            administers the system (permission_service: accounts, org chart,
            settings, policies, leave configuration, salary-access approvals,
            audit log) and does nothing operational, whoever holds it.
  finance   The finance sign-in page (/finance/login), for finance holders
            only. finance is in force, every other role but employee dormant;
            the finances module works only here.

The admin and finance sessions are PRIVILEGED: they lapse after
PRIVILEGED_IDLE without activity and after PRIVILEGED_MAX whatever happens,
every sign-in, refusal and ending is audited, and neither is ever reached by
refreshing an employee session: the portal comes from the row, which only
that door's sign-in writes. One door never grants the other's role; a person
who holds both signs in at each separately.

The choke point is apply_portal(): get_current_user calls it on the request's
user before any endpoint sees it, and User.role_codes / has_role / role_ids all
read the dormant set it leaves. Nothing re-derives roles from user_roles, so
require_role, require_permission, access_scope, employee_access, leave_access
and every inline has_role check get the same answer without being edited.
Stored roles are never touched.

A token that merely CLAIMS a privileged portal proves nothing on its own: an
ended session's access token stays signed and unexpired for up to 15 minutes.
The claim only says "look the row up"; the row decides.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.utils.client_ip import client_address

EMPLOYEE = "employee"
ADMIN = "admin"
FINANCE = "finance"
PORTALS = (EMPLOYEE, ADMIN, FINANCE)
PRIVILEGED = (ADMIN, FINANCE)

ADMIN_ROLE = "tenant_admin"
FINANCE_ROLE = "finance"
BASE_ROLE = "employee"

# The role each privileged door is for. It is dormant everywhere else.
PORTAL_ROLE = {ADMIN: ADMIN_ROLE, FINANCE: FINANCE_ROLE}
DOOR_ROLES = frozenset(PORTAL_ROLE.values())

PRIVILEGED_IDLE = timedelta(minutes=30)
PRIVILEGED_MAX = timedelta(hours=8)
# The names the admin door shipped with (5.19); the finance door has the same.
ADMIN_IDLE = PRIVILEGED_IDLE
ADMIN_MAX = PRIVILEGED_MAX
# Writing last_activity_at on every request of a busy screen would be one
# UPDATE per API call for no gain; a minute's resolution is plenty for a
# 30-minute limit.
SLIDE_EVERY = timedelta(seconds=60)

# Sent by the web client on requests it makes while the person is not using
# the app (background polling after a minute without input). Those must not
# keep an unattended privileged session alive, or a dashboard left open on a
# desk would never time out. A client that lies only keeps its own session
# alive.
IDLE_HEADER = "x-user-idle"

ADMIN_ENDED_DETAIL = "Your admin session ended. Sign in again to continue."
FINANCE_ENDED_DETAIL = "Your finance session ended. Sign in again to continue."
ENDED_DETAIL = {ADMIN: ADMIN_ENDED_DETAIL, FINANCE: FINANCE_ENDED_DETAIL}
ENDED_HEADER = "X-Session-Ended"

NOT_ELIGIBLE_DETAIL = {
    ADMIN: "This account is not an administrator.",
    FINANCE: "This account does not have the Finance role.",
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    # SQLite (tests) hands timestamps back naive; they were written as UTC.
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def is_eligible(user, portal: str) -> bool:
    """May use this door: holds its role, dormant or not. Everyone may use
    the employee door."""
    if portal == EMPLOYEE:
        return True
    return user.holds_role(PORTAL_ROLE[portal])


def is_admin_eligible(user) -> bool:
    """Holds tenant_admin, dormant or not: may use the administrator sign-in."""
    return is_eligible(user, ADMIN)


def is_finance_eligible(user) -> bool:
    """Holds finance, dormant or not: may use the finance sign-in."""
    return is_eligible(user, FINANCE)


def has_employee_workspace(user) -> bool:
    """False for a pure administrator account (tenant_admin and nothing else):
    it has no schedule, leave or payslips of its own to show."""
    return bool(set(user.stored_role_codes) - {ADMIN_ROLE})


def roles_in_force(stored, portal: str) -> set:
    """Of the stored role codes, the ones a session in `portal` may use."""
    stored = set(stored)
    if portal in PRIVILEGED:
        return stored & {PORTAL_ROLE[portal], BASE_ROLE}
    return stored - DOOR_ROLES


def apply_portal(user, portal: str) -> None:
    """Set the roles in force for this request. THE choke point; see above."""
    if portal not in PORTALS:
        portal = EMPLOYEE
    stored = set(user.stored_role_codes)
    user._dormant_role_codes = frozenset(stored - roles_in_force(stored, portal)) | (
        frozenset() if portal in PRIVILEGED else DOOR_ROLES
    )
    user.portal = portal
    user.in_admin_portal = portal == ADMIN


def idle_expires_at(row) -> Optional[datetime]:
    if row is None or row.portal not in PRIVILEGED:
        return None
    last = _aware(row.last_activity_at) or _aware(row.login_at)
    return min(last + PRIVILEGED_IDLE, _aware(row.admin_expires_at))


def session_problem(row, user, now: Optional[datetime] = None, portal: Optional[str] = None) -> Optional[str]:
    """Why this row no longer grants its privileged portal, or None while it
    does. `portal` is the one the token claims (the row's when omitted)."""
    now = now or utcnow()
    if row is None:
        return "missing"
    portal = portal or row.portal
    if row.user_id != user.id or row.portal != portal or portal not in PRIVILEGED:
        return "mismatch"
    if row.revoked_at is not None:
        return "revoked"
    if row.admin_expires_at is None or now >= _aware(row.admin_expires_at):
        return "max_age"
    if now >= idle_expires_at(row):
        return "idle"
    if not is_eligible(user, portal):
        # Role removals also invalidate every token (tokens_valid_from); this
        # is the belt to that pair of braces.
        return "not_admin" if portal == ADMIN else "not_finance"
    return None


def admin_session_problem(row, user, now: Optional[datetime] = None) -> Optional[str]:
    """session_problem for a row claimed as an admin session."""
    return session_problem(row, user, now, ADMIN)


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
    in_force = roles_in_force(user.stored_role_codes, portal)
    roles = [c for c in user.stored_role_codes if c in in_force]
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
    if portal in PRIVILEGED:
        end = min(end, now + PRIVILEGED_MAX)
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
    factor when they have one) and, for a privileged portal, checked
    eligibility; this re-checks eligibility because an admin session for a
    non-admin (or a finance session for someone without finance) must be
    impossible whatever the caller forgot."""
    from app.models.user import UserSession

    if portal not in PORTALS:
        raise ValueError(f"unknown portal {portal!r}")
    if portal in PRIVILEGED and not is_eligible(user, portal):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=NOT_ELIGIBLE_DETAIL[portal],
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
        admin_expires_at=(now + PRIVILEGED_MAX) if portal in PRIVILEGED else None,
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
    if row.portal in PRIVILEGED and row.admin_expires_at is not None:
        new_end = min(new_end, _aware(row.admin_expires_at))
    row.expires_at = new_end
    await db.flush()
    return access, refresh


async def end_session(db: AsyncSession, row, *, reason: str, actor=None, ip: Optional[str] = None) -> None:
    """Revoke a session row and deny-list its current access token. Audits the
    end of privileged sessions, which is what a reviewer wants to find."""
    from app.models.site_settings import AuditLog
    from app.services.token_store import TokenDenylist

    if row is None:
        return
    if row.revoked_at is None:
        row.revoked_at = utcnow()
        exp = int(_aware(row.expires_at).timestamp()) if row.expires_at else None
        await TokenDenylist.revoke(row.jti, exp)
        if row.portal in PRIVILEGED:
            db.add(AuditLog(
                tenant_id=row.tenant_id,
                user_id=row.user_id,
                user_email=getattr(actor, "email", None),
                action=f"{row.portal}_session_ended",
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
    because the employee portal is the least a session can be. A privileged
    claim is honoured only while its row is live; otherwise that session is
    over and the request is refused, so the client can send the person back to
    that door's sign-in instead of silently carrying on with less.
    """
    request.state.portal_session = None
    claimed = payload.get("portal")
    if claimed not in PRIVILEGED:
        apply_portal(user, EMPLOYEE)
        request.state.portal = EMPLOYEE
        return EMPLOYEE

    row = await session_by_key(db, payload.get("sid"))
    now = utcnow()
    problem = session_problem(row, user, now, claimed)
    if problem:
        await _refuse_ended(db, row, user, problem, request, claimed)

    if request.headers.get(IDLE_HEADER) != "1":
        last = _aware(row.last_activity_at)
        if last is None or now - last >= SLIDE_EVERY:
            row.last_activity_at = now
    apply_portal(user, claimed)
    request.state.portal = claimed
    request.state.portal_session = row
    return claimed


async def _refuse_ended(db: AsyncSession, row, user, reason: str, request: Request, portal: str = ADMIN):
    if row is not None and row.user_id == user.id and row.revoked_at is None:
        await end_session(db, row, reason=reason, actor=user, ip=_ip(request))
        # Commit before refusing: the 401 rolls the request back, which would
        # undo the revocation and the audit entry.
        await db.commit()
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=ENDED_DETAIL.get(portal, ADMIN_ENDED_DETAIL),
        headers={ENDED_HEADER: portal, "WWW-Authenticate": "Bearer"},
    )


def _ip(request: Optional[Request]) -> Optional[str]:
    # Trusted proxies only; see app/utils/client_ip.py.
    return client_address(request)


def describe(user, request: Request) -> dict:
    """The portal fields of /auth/me and the sign-in responses."""
    portal = getattr(request.state, "portal", EMPLOYEE)
    row = getattr(request.state, "portal_session", None)
    out = {
        "portal": portal,
        "admin_eligible": is_admin_eligible(user),
        "finance_eligible": is_finance_eligible(user),
        "has_employee_workspace": has_employee_workspace(user),
        "expires_at": None,
        "admin_expires_at": None,
        "idle_timeout_seconds": None,
    }
    if portal in PRIVILEGED and row is not None:
        out["expires_at"] = idle_expires_at(row)
        out["admin_expires_at"] = _aware(row.admin_expires_at)
        out["idle_timeout_seconds"] = int(PRIVILEGED_IDLE.total_seconds())
    return out


__all__ = [
    "ADMIN",
    "ADMIN_ENDED_DETAIL",
    "ADMIN_IDLE",
    "ADMIN_MAX",
    "ADMIN_ROLE",
    "EMPLOYEE",
    "FINANCE",
    "FINANCE_ENDED_DETAIL",
    "FINANCE_ROLE",
    "IDLE_HEADER",
    "PRIVILEGED",
    "admin_session_problem",
    "apply_portal",
    "describe",
    "end_all_sessions",
    "end_session",
    "has_employee_workspace",
    "is_admin_eligible",
    "is_eligible",
    "is_finance_eligible",
    "open_session",
    "resolve_request",
    "roles_in_force",
    "rotate_session",
    "session_by_key",
    "session_problem",
]
