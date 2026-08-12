"""Salary Enrollment Service

Separation-of-duties gate on salary visibility.

- A user must have an active 'viewer' enrollment to see other people's salary.
- A user must have an active 'approver' enrollment to approve viewer requests.
- A request is approved by a DIFFERENT active approver (never self-approval).
- tenant_admin is NOT special-cased here (must be enrolled like anyone else).
- Grants are permanent until revoked. The last active approver cannot be revoked.

The approval workflow surfaces as in-app notifications (actionable) and emails
with a deep-link. The email token only identifies the request for the review
page; the actual decision is made through authenticated endpoints, so the token
never authorizes a state change.
"""
import logging
import secrets
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.salary_enrollment import SalaryEnrollment, SalaryEnrollmentRequest
from app.models.site_settings import SiteSettings
from app.models.user import User
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)

TOKEN_EXPIRY_DAYS = 7
VALID_KINDS = ("viewer", "approver")


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
        out = []
        for enr, user in rows:
            out.append({
                "id": enr.id,
                "user_id": enr.user_id,
                "user_name": user.full_name,
                "kind": enr.kind,
                "status": enr.status,
                "granted_by": enr.granted_by,
                "granted_at": enr.granted_at,
            })
        return out

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
            token_expires_at=datetime.utcnow() + timedelta(days=TOKEN_EXPIRY_DAYS),
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
        # Separation of duties: never approve your own request.
        if approver_id == req.user_id:
            raise SalaryEnrollmentError("You cannot approve your own request; another approver must decide.")

        req.decided_by = approver_id
        req.decided_at = datetime.utcnow()
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
        return req

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
            existing.granted_at = datetime.utcnow()
            existing.revoked_by = None
            existing.revoked_at = None
            await db.flush()
            return existing
        enr = SalaryEnrollment(
            tenant_id=tenant_id, user_id=user_id, kind=kind,
            status="active", granted_by=granted_by, granted_at=datetime.utcnow(),
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
        enr.revoked_at = datetime.utcnow()
        await db.flush()
        await SalaryEnrollmentService._audit(
            db, tenant_id, actor_id=actor_id, subject_id=user_id,
            action="salary_enrollment.revoked", req_id=enr.id, kind=kind,
        )
        await NotificationService.notify(
            db, tenant_id, user_id, "salary_enrollment_decided",
            "Salary access revoked", f"Your {kind} access was revoked.",
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
                SalaryEnrollmentRequest.token_expires_at > datetime.utcnow(),
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
        """Ensure every tenant_admin user is an active viewer + approver. Called on
        tenant provisioning so a fresh tenant is never left with no approver."""
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
        for uid in set(admin_ids):
            for kind in ("viewer", "approver"):
                if not await SalaryEnrollmentService._has_active(db, tenant_id, uid, kind):
                    exists = (await db.execute(
                        select(SalaryEnrollment).where(
                            SalaryEnrollment.tenant_id == tenant_id,
                            SalaryEnrollment.user_id == uid,
                            SalaryEnrollment.kind == kind,
                        )
                    )).scalar_one_or_none()
                    if exists:
                        exists.status = "active"
                    else:
                        db.add(SalaryEnrollment(
                            tenant_id=tenant_id, user_id=uid, kind=kind,
                            status="active", granted_by=None, granted_at=datetime.utcnow(),
                        ))
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
            link = f"{base}/finances/salary-access/review?token={req.token}"
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
                    lambda d, e=email: EmailService.send_email(d, e, subject, html)
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
                    lambda d, e=row[0]: EmailService.send_email(d, e, subject, html)
                )
        except Exception:
            logger.exception("Failed to queue requester notification email")
