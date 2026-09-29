"""Salary Enrollment Service

Separation-of-duties gate on salary visibility.

- A user must have an active 'viewer' enrollment to see other people's salary.
- A user must have an active 'approver' enrollment to approve viewer requests.
- A request is approved by a DIFFERENT active approver (never self-approval).
- Nor by an approver whose own approver enrollment the requester granted. That
  closes the obvious puppet loop: an admin makes X an approver, X approves the
  admin. (A longer chain of accounts one person controls is not blocked; see
  below.)
- tenant_admin is NOT special-cased here (must be enrolled like anyone else).
  A new install makes its first administrator an approver ONLY, so somebody can
  approve requests, but the administrator sees no figures until another person
  approves them (owner's decision, 2026-09; migration 066 applied it to
  existing installs).
- Grants are permanent until revoked. The last active approver cannot be revoked.

Every grant, decline and revoke is audit-logged and announced (in-app and by
email) to every other active approver and every tenant administrator, as well
as to the person concerned. That is the honest extent of the control: someone
who can create user accounts can still invent a second identity and use it to
approve themselves. What stops that going unnoticed is the separation above,
the announcement to everyone else who could object, and the audit trail.

The approval workflow surfaces as in-app notifications (actionable) and emails
with a deep-link. The email token only identifies the request for the review
page; the actual decision is made through authenticated endpoints, so the token
never authorizes a state change.
"""
import logging
import secrets
from datetime import timedelta
from html import escape as html_escape
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.salary_enrollment import SalaryEnrollment, SalaryEnrollmentRequest
from app.models.site_settings import SiteSettings
from app.models.user import User
from app.services.notification_service import NotificationService
from app.utils.timeutil import utcnow

logger = logging.getLogger(__name__)

TOKEN_EXPIRY_DAYS = 7
VALID_KINDS = ("viewer", "approver")

# Plain-English verbs for the grant history on the Salary Access tab.
_HISTORY_LABELS = {
    "salary_enrollment.request_created": "asked for",
    "salary_enrollment.request_approved": "approved",
    "salary_enrollment.request_declined": "declined",
    "salary_enrollment.revoked": "revoked",
    "salary_enrollment.seeded": "granted at setup",
    "salary_enrollment.bootstrap_revoked": "removed setup-granted",
}


class SalaryEnrollmentError(ValueError):
    """Raised for workflow violations (translated to HTTP 400 at the API layer)."""


class SalaryEnrollmentService:
    # ── Status checks ─────────────────────────────────────────────────
    @staticmethod
    async def _has_active(db: AsyncSession, tenant_id: UUID, user_id: int, kind: str) -> bool:
        stmt = select(SalaryEnrollment.id).where(
            SalaryEnrollment.tenant_id == tenant_id,
            SalaryEnrollment.user_id == user_id,
            SalaryEnrollment.kind == kind,
            SalaryEnrollment.status == "active",
        )
        return (await db.execute(stmt)).first() is not None

    @staticmethod
    async def is_viewer(db: AsyncSession, tenant_id: UUID, user_id: int) -> bool:
        return await SalaryEnrollmentService._has_active(db, tenant_id, user_id, "viewer")

    @staticmethod
    async def is_approver(db: AsyncSession, tenant_id: UUID, user_id: int) -> bool:
        return await SalaryEnrollmentService._has_active(db, tenant_id, user_id, "approver")

    @staticmethod
    async def _active_approver_ids(db: AsyncSession, tenant_id: UUID) -> List[int]:
        stmt = select(SalaryEnrollment.user_id).where(
            SalaryEnrollment.tenant_id == tenant_id,
            SalaryEnrollment.kind == "approver",
            SalaryEnrollment.status == "active",
        )
        return [r[0] for r in (await db.execute(stmt)).all()]

    # ── Listings (for the admin page) ─────────────────────────────────
    @staticmethod
    async def list_enrollments(db: AsyncSession, tenant_id: UUID) -> List[Dict[str, Any]]:
        stmt = (
            select(SalaryEnrollment, User)
            .join(User, User.id == SalaryEnrollment.user_id)
            .where(
                SalaryEnrollment.tenant_id == tenant_id,
                SalaryEnrollment.status == "active",
            )
            .order_by(SalaryEnrollment.kind, User.last_name)
        )
        rows = (await db.execute(stmt)).all()
        names = await SalaryEnrollmentService._names(
            db, {enr.granted_by for enr, _ in rows if enr.granted_by}
        )
        out = []
        for enr, user in rows:
            out.append({
                "id": enr.id,
                "user_id": enr.user_id,
                "user_name": user.full_name,
                "kind": enr.kind,
                "status": enr.status,
                "granted_by": enr.granted_by,
                # None = granted at setup, not by a person.
                "granted_by_name": names.get(enr.granted_by) if enr.granted_by else None,
                "granted_at": enr.granted_at,
            })
        return out

    @staticmethod
    async def grant_history(
        db: AsyncSession, tenant_id: UUID, limit: int = 200
    ) -> List[Dict[str, Any]]:
        """Who granted, declined or revoked what, to whom, and when, newest
        first, from the audit log (which every such change writes). Shown to
        approvers and tenant administrators on the Salary Access tab."""
        from app.models.site_settings import AuditLog

        rows = list((await db.execute(
            select(AuditLog)
            .where(
                AuditLog.tenant_id == tenant_id,
                AuditLog.resource_type == "salary_enrollment",
            )
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .limit(limit)
        )).scalars().all())
        ids = set()
        for r in rows:
            if r.user_id:
                ids.add(r.user_id)
            subject = (r.details or {}).get("subject_id")
            if isinstance(subject, int):
                ids.add(subject)
        names = await SalaryEnrollmentService._names(db, ids)
        out = []
        for r in rows:
            d = r.details or {}
            subject = d.get("subject_id")
            out.append({
                "id": r.id,
                "at": r.created_at,
                "action": r.action,
                "label": _HISTORY_LABELS.get(r.action, r.action.split(".")[-1].replace("_", " ")),
                "actor_id": r.user_id,
                # No actor = the system (first-run setup or a migration).
                "actor_name": names.get(r.user_id) if r.user_id else None,
                "subject_id": subject if isinstance(subject, int) else None,
                "subject_name": names.get(subject) if isinstance(subject, int) else None,
                "kind": d.get("kind"),
            })
        return out

    @staticmethod
    async def _names(db: AsyncSession, user_ids) -> Dict[int, str]:
        ids = {i for i in user_ids if i}
        if not ids:
            return {}
        users = (await db.execute(select(User).where(User.id.in_(ids)))).scalars().all()
        return {u.id: u.full_name for u in users}

    @staticmethod
    async def list_requests(
        db: AsyncSession, tenant_id: UUID, status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        stmt = (
            select(SalaryEnrollmentRequest, User)
            .join(User, User.id == SalaryEnrollmentRequest.user_id)
            .where(SalaryEnrollmentRequest.tenant_id == tenant_id)
        )
        if status:
            stmt = stmt.where(SalaryEnrollmentRequest.status == status)
        stmt = stmt.order_by(SalaryEnrollmentRequest.requested_at.desc())
        rows = (await db.execute(stmt)).all()
        out = []
        for req, user in rows:
            out.append({
                "id": req.id,
                "user_id": req.user_id,
                "user_name": user.full_name,
                "kind": req.kind,
                "status": req.status,
                "reason": req.reason,
                "requested_at": req.requested_at,
                "decided_by": req.decided_by,
                "decided_at": req.decided_at,
                "decision_note": req.decision_note,
            })
        return out

    @staticmethod
    async def my_status(db: AsyncSession, tenant_id: UUID, user_id: int) -> Dict[str, Any]:
        pending_stmt = select(SalaryEnrollmentRequest).where(
            SalaryEnrollmentRequest.tenant_id == tenant_id,
            SalaryEnrollmentRequest.user_id == user_id,
            SalaryEnrollmentRequest.status == "pending",
        )
        pending = list((await db.execute(pending_stmt)).scalars().all())
        return {
            "is_viewer": await SalaryEnrollmentService.is_viewer(db, tenant_id, user_id),
            "is_approver": await SalaryEnrollmentService.is_approver(db, tenant_id, user_id),
            "pending_kinds": [p.kind for p in pending],
            # Ids too, so the requester can withdraw their own request.
            "pending_requests": [{"id": p.id, "kind": p.kind} for p in pending],
        }

    # ── Request / decide / revoke ─────────────────────────────────────
    @staticmethod
    async def create_request(
        db: AsyncSession,
        tenant_id: UUID,
        user_id: int,
        kind: str,
        reason: Optional[str],
        requested_by: int,
    ) -> SalaryEnrollmentRequest:
        if kind not in VALID_KINDS:
            raise SalaryEnrollmentError(f"Invalid kind '{kind}'.")
        if await SalaryEnrollmentService._has_active(db, tenant_id, user_id, kind):
            raise SalaryEnrollmentError(f"User is already an active {kind}.")
        # One pending request per (user, kind).
        dup = select(SalaryEnrollmentRequest.id).where(
            SalaryEnrollmentRequest.tenant_id == tenant_id,
            SalaryEnrollmentRequest.user_id == user_id,
            SalaryEnrollmentRequest.kind == kind,
            SalaryEnrollmentRequest.status == "pending",
        )
        if (await db.execute(dup)).first() is not None:
            raise SalaryEnrollmentError(f"A pending {kind} request already exists for this user.")

        req = SalaryEnrollmentRequest(
            tenant_id=tenant_id,
            user_id=user_id,
            kind=kind,
            status="pending",
            reason=reason,
            requested_by=requested_by,
            token=secrets.token_urlsafe(48),
            token_expires_at=utcnow() + timedelta(days=TOKEN_EXPIRY_DAYS),
        )
        db.add(req)
        await db.flush()

        await SalaryEnrollmentService._audit(
            db, tenant_id, actor_id=requested_by, subject_id=user_id,
            action="salary_enrollment.request_created", req_id=req.id, kind=kind,
        )
        await SalaryEnrollmentService._notify_approvers(db, tenant_id, req, user_id)
        return req

    @staticmethod
    async def decide(
        db: AsyncSession,
        tenant_id: UUID,
        request_id: int,
        approver_id: int,
        approve: bool,
        note: Optional[str] = None,
    ) -> SalaryEnrollmentRequest:
        req = (await db.execute(
            select(SalaryEnrollmentRequest).where(
                SalaryEnrollmentRequest.id == request_id,
                SalaryEnrollmentRequest.tenant_id == tenant_id,
            )
        )).scalar_one_or_none()
        if not req:
            raise SalaryEnrollmentError("Request not found.")
        if req.status != "pending":
            raise SalaryEnrollmentError(f"Request is already {req.status}.")
        if not await SalaryEnrollmentService.is_approver(db, tenant_id, approver_id):
            raise SalaryEnrollmentError("Only an active approver can decide this request.")
        if approve:
            block = await SalaryEnrollmentService.approval_block(db, tenant_id, req.user_id, approver_id)
            if block:
                raise SalaryEnrollmentError(block)
        elif approver_id == req.user_id:
            # Declining your own request is withdrawing it; keep one path for that.
            raise SalaryEnrollmentError("You cannot decide your own request. Withdraw it instead.")

        req.decided_by = approver_id
        req.decided_at = utcnow()
        req.decision_note = note
        req.token = None
        req.token_expires_at = None

        if approve:
            req.status = "approved"
            await SalaryEnrollmentService._grant(db, tenant_id, req.user_id, req.kind, approver_id)
            action = "salary_enrollment.request_approved"
            title = "Salary access approved"
            body = f"Your request for {req.kind} access was approved."
        else:
            req.status = "declined"
            action = "salary_enrollment.request_declined"
            title = "Salary access declined"
            body = f"Your request for {req.kind} access was declined."
            if note:
                body += f" Note: {note}"

        await db.flush()
        await SalaryEnrollmentService._audit(
            db, tenant_id, actor_id=approver_id, subject_id=req.user_id,
            action=action, req_id=req.id, kind=req.kind,
        )
        await NotificationService.mark_actioned(db, tenant_id, "approve_salary_request", req.id)
        await NotificationService.notify(
            db, tenant_id, req.user_id, "salary_enrollment_decided", title, body,
        )
        await SalaryEnrollmentService._email_requester(db, tenant_id, req.user_id, title, body)
        verb = "approved" if approve else "declined"
        await SalaryEnrollmentService._announce(
            db, tenant_id, actor_id=approver_id, subject_id=req.user_id,
            title=f"Salary access {'granted' if approve else 'declined'}",
            what=f"{verb} {{subject}}'s request for {req.kind} access to salary figures",
        )
        return req

    @staticmethod
    async def approval_block(
        db: AsyncSession, tenant_id: UUID, subject_id: int, approver_id: int
    ) -> Optional[str]:
        """Why `approver_id` may not approve a request for `subject_id` to get
        access (viewer or approver), or None if they may.

        Separation of duties: never your own request, and never the request of
        the person who made you an approver. Without the second rule an admin
        could make a puppet account an approver and have it approve the admin,
        which is granting yourself access with one extra click."""
        if approver_id == subject_id:
            return "You cannot approve your own request; another approver must decide."
        own = (await db.execute(
            select(SalaryEnrollment).where(
                SalaryEnrollment.tenant_id == tenant_id,
                SalaryEnrollment.user_id == approver_id,
                SalaryEnrollment.kind == "approver",
                SalaryEnrollment.status == "active",
            )
        )).scalar_one_or_none()
        if own is not None and own.granted_by is not None and own.granted_by == subject_id:
            subject = (await db.execute(select(User).where(User.id == subject_id))).scalar_one_or_none()
            name = subject.full_name if subject else "this person"
            return (
                f"{name} made you an approver, so you cannot approve their request. "
                "An approver they did not appoint must decide."
            )
        return None

    @staticmethod
    async def _grant(
        db: AsyncSession, tenant_id: UUID, user_id: int, kind: str, granted_by: int
    ) -> SalaryEnrollment:
        existing = (await db.execute(
            select(SalaryEnrollment).where(
                SalaryEnrollment.tenant_id == tenant_id,
                SalaryEnrollment.user_id == user_id,
                SalaryEnrollment.kind == kind,
            )
        )).scalar_one_or_none()
        if existing:
            existing.status = "active"
            existing.granted_by = granted_by
            existing.granted_at = utcnow()
            existing.revoked_by = None
            existing.revoked_at = None
            await db.flush()
            return existing
        enr = SalaryEnrollment(
            tenant_id=tenant_id, user_id=user_id, kind=kind,
            status="active", granted_by=granted_by, granted_at=utcnow(),
        )
        db.add(enr)
        await db.flush()
        return enr

    @staticmethod
    async def revoke(
        db: AsyncSession, tenant_id: UUID, user_id: int, kind: str, actor_id: int
    ) -> bool:
        if kind not in VALID_KINDS:
            raise SalaryEnrollmentError(f"Invalid kind '{kind}'.")
        # Guard: never remove the last active approver (would lock out approvals).
        if kind == "approver":
            approvers = await SalaryEnrollmentService._active_approver_ids(db, tenant_id)
            if user_id in approvers and len(approvers) <= 1:
                raise SalaryEnrollmentError("Cannot remove the last approver.")

        enr = (await db.execute(
            select(SalaryEnrollment).where(
                SalaryEnrollment.tenant_id == tenant_id,
                SalaryEnrollment.user_id == user_id,
                SalaryEnrollment.kind == kind,
                SalaryEnrollment.status == "active",
            )
        )).scalar_one_or_none()
        if not enr:
            return False
        enr.status = "revoked"
        enr.revoked_by = actor_id
        enr.revoked_at = utcnow()
        await db.flush()
        await SalaryEnrollmentService._audit(
            db, tenant_id, actor_id=actor_id, subject_id=user_id,
            action="salary_enrollment.revoked", req_id=enr.id, kind=kind,
        )
        await NotificationService.notify(
            db, tenant_id, user_id, "salary_enrollment_decided",
            "Salary access revoked", f"Your {kind} access was revoked.",
        )
        await SalaryEnrollmentService._announce(
            db, tenant_id, actor_id=actor_id, subject_id=user_id,
            title="Salary access revoked",
            what=f"revoked {{subject}}'s {kind} access to salary figures",
        )
        return True

    @staticmethod
    async def cancel_request(
        db: AsyncSession, tenant_id: UUID, request_id: int, actor_id: int
    ) -> bool:
        req = (await db.execute(
            select(SalaryEnrollmentRequest).where(
                SalaryEnrollmentRequest.id == request_id,
                SalaryEnrollmentRequest.tenant_id == tenant_id,
            )
        )).scalar_one_or_none()
        if not req or req.status != "pending":
            return False
        if req.user_id != actor_id and req.requested_by != actor_id:
            raise SalaryEnrollmentError("Only the requester can cancel this request.")
        req.status = "cancelled"
        req.token = None
        req.token_expires_at = None
        await db.flush()
        await NotificationService.mark_actioned(db, tenant_id, "approve_salary_request", req.id)
        return True

    # ── Token deep-link (read-only) ───────────────────────────────────
    @staticmethod
    async def get_request_by_token(db: AsyncSession, token: str) -> Optional[Dict[str, Any]]:
        req = (await db.execute(
            select(SalaryEnrollmentRequest).where(
                SalaryEnrollmentRequest.token == token,
                SalaryEnrollmentRequest.status == "pending",
                SalaryEnrollmentRequest.token_expires_at > utcnow(),
            )
        )).scalar_one_or_none()
        if not req:
            return None
        user = (await db.execute(select(User).where(User.id == req.user_id))).scalar_one_or_none()
        return {
            "id": req.id,
            "user_id": req.user_id,
            "user_name": user.full_name if user else f"#{req.user_id}",
            "kind": req.kind,
            "reason": req.reason,
            "requested_at": req.requested_at,
        }

    # ── Bootstrap seed (idempotent) ───────────────────────────────────
    @staticmethod
    async def seed_admin(db: AsyncSession, tenant_id: UUID) -> None:
        """Ensure every tenant_admin user is an active APPROVER. Called on tenant
        provisioning so a fresh tenant is never left with nobody who can approve
        a request (see migration 056 for what that deadlock looked like).

        Approver only, not viewer: the owner's rule is that an administrator
        sets payroll up but sees no salary figures unless another person agrees.
        Being an approver shows no figures; it only lets them approve other
        people's requests, never their own (approval_block)."""
        from app.models.role import Role, UserRole

        admin_ids = [r[0] for r in (await db.execute(
            select(User.id)
            .join(UserRole, UserRole.user_id == User.id)
            .join(Role, Role.id == UserRole.role_id)
            .where(
                User.tenant_id == tenant_id,
                Role.code == "tenant_admin",
                Role.is_active == True,  # noqa: E712
            )
        )).all()]
        kind = "approver"
        for uid in sorted(set(admin_ids)):
            if await SalaryEnrollmentService._has_active(db, tenant_id, uid, kind):
                continue
            enr = (await db.execute(
                select(SalaryEnrollment).where(
                    SalaryEnrollment.tenant_id == tenant_id,
                    SalaryEnrollment.user_id == uid,
                    SalaryEnrollment.kind == kind,
                )
            )).scalar_one_or_none()
            if enr:
                enr.status = "active"
            else:
                enr = SalaryEnrollment(
                    tenant_id=tenant_id, user_id=uid, kind=kind,
                    status="active", granted_by=None, granted_at=utcnow(),
                )
                db.add(enr)
            await db.flush()
            await SalaryEnrollmentService._audit(
                db, tenant_id, actor_id=None, subject_id=uid,
                action="salary_enrollment.seeded", req_id=enr.id, kind=kind,
            )
        await db.flush()

    # ── Internal helpers ──────────────────────────────────────────────
    @staticmethod
    async def _audit(
        db: AsyncSession, tenant_id: UUID, *, actor_id: Optional[int], subject_id: Optional[int],
        action: str, req_id: int, kind: str,
    ) -> None:
        from app.models.site_settings import AuditLog

        db.add(AuditLog(
            tenant_id=tenant_id,
            user_id=actor_id,
            action=action,
            resource_type="salary_enrollment",
            resource_id=str(req_id),
            details={"kind": kind, "subject_id": subject_id},
        ))
        await db.flush()

    @staticmethod
    async def _notify_approvers(
        db: AsyncSession, tenant_id: UUID, req: SalaryEnrollmentRequest, subject_id: int
    ) -> None:
        approver_ids = await SalaryEnrollmentService._active_approver_ids(db, tenant_id)
        # An approver cannot approve their own request, so skip notifying the subject.
        approver_ids = [a for a in approver_ids if a != subject_id]
        subject = (await db.execute(select(User).where(User.id == subject_id))).scalar_one_or_none()
        subject_name = subject.full_name if subject else f"#{subject_id}"
        title = "Salary access request"
        body = f"{subject_name} requested {req.kind} access to salary data."
        for aid in approver_ids:
            await NotificationService.notify(
                db, tenant_id, aid, "salary_enrollment_request", title, body,
                action_type="approve_salary_request", action_ref_id=req.id,
            )
        # Best-effort emails with a deep-link to the review page.
        await SalaryEnrollmentService._email_approvers(db, tenant_id, approver_ids, req, subject_name)

    @staticmethod
    async def _oversight_ids(db: AsyncSession, tenant_id: UUID) -> List[int]:
        """Everyone who should hear about a change in salary access: every
        active approver and every active tenant administrator."""
        from app.models.role import Role, UserRole

        admins = [r[0] for r in (await db.execute(
            select(User.id)
            .join(UserRole, UserRole.user_id == User.id)
            .join(Role, Role.id == UserRole.role_id)
            .where(
                User.tenant_id == tenant_id,
                User.is_active == True,  # noqa: E712
                Role.code == "tenant_admin",
                Role.is_active == True,  # noqa: E712
            )
        )).all()]
        approvers = await SalaryEnrollmentService._active_approver_ids(db, tenant_id)
        return sorted(set(admins) | set(approvers))

    @staticmethod
    async def _announce(
        db: AsyncSession, tenant_id: UUID, *, actor_id: int, subject_id: int,
        title: str, what: str,
    ) -> None:
        """Tell every OTHER approver and tenant administrator (in-app and by
        email) that salary access changed. The actor did it and the subject has
        their own notice. This is the check on a grant nobody else agreed to:
        a second identity can approve, but it cannot do so unseen."""
        recipients = [
            uid for uid in await SalaryEnrollmentService._oversight_ids(db, tenant_id)
            if uid not in (actor_id, subject_id)
        ]
        if not recipients:
            return
        names = await SalaryEnrollmentService._names(db, {actor_id, subject_id})
        actor = names.get(actor_id, "Someone")
        subject = names.get(subject_id, "a user")
        body = (
            f"{actor} {what.replace('{subject}', subject)}. You are told because you "
            "approve salary access or administer this organization. If you did not "
            "expect this, review it under Finances, Salary Access."
        )
        for uid in recipients:
            await NotificationService.notify(
                db, tenant_id, uid, "salary_enrollment_changed", title, body,
            )
        try:
            from app.services.email_service import EmailService

            base = await SalaryEnrollmentService._frontend_base(db)
            html = (
                f"<p>{html_escape(body)}</p>"
                f"<p><a href=\"{base}/salary-access\">Open Salary Access</a></p>"
            )
            emails = [r[0] for r in (await db.execute(
                select(User.email).where(User.id.in_(recipients), User.email.isnot(None))
            )).all()]
            for email in emails:
                EmailService.fire_and_forget(
                    lambda d, e=email: EmailService.send_email(
                        d, e, title, html,
                        log_type="salary_access_changed", tenant_id=tenant_id,
                    )
                )
        except Exception:
            logger.exception("Failed to queue salary access change emails")

    @staticmethod
    async def _frontend_base(db: AsyncSession) -> str:
        settings = (await db.execute(select(SiteSettings).limit(1))).scalar_one_or_none()
        base = (settings.base_url if settings and settings.base_url else "http://localhost:8000")
        return base.replace(":8000", ":3000").rstrip("/")

    @staticmethod
    async def _email_approvers(
        db: AsyncSession, tenant_id: UUID, approver_ids: List[int],
        req: SalaryEnrollmentRequest, subject_name: str,
    ) -> None:
        try:
            from app.services.email_service import EmailService

            base = await SalaryEnrollmentService._frontend_base(db)
            link = f"{base}/salary-access/review?token={req.token}"
            emails = [r[0] for r in (await db.execute(
                select(User.email).where(User.id.in_(approver_ids), User.email.isnot(None))
            )).all()]
            subject = "Salary access request awaiting your approval"
            html = (
                f"<p>{subject_name} has requested <b>{req.kind}</b> access to salary data.</p>"
                f"<p><a href=\"{link}\">Review this request</a></p>"
            )
            for email in emails:
                EmailService.fire_and_forget(
                    lambda d, e=email: EmailService.send_email(
                        d, e, subject, html,
                        log_type="salary_access_request", tenant_id=tenant_id,
                    )
                )
        except Exception:
            logger.exception("Failed to queue approver notification emails")

    @staticmethod
    async def _email_requester(
        db: AsyncSession, tenant_id: UUID, user_id: int, subject: str, body: str
    ) -> None:
        try:
            from app.services.email_service import EmailService

            row = (await db.execute(select(User.email).where(User.id == user_id))).first()
            if row and row[0]:
                html = f"<p>{body}</p>"
                EmailService.fire_and_forget(
                    lambda d, e=row[0]: EmailService.send_email(
                        d, e, subject, html,
                        log_type="salary_access_decision", tenant_id=tenant_id,
                    )
                )
        except Exception:
            logger.exception("Failed to queue requester notification email")
