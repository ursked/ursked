"""Every leave notification, in-app and by email, in one place.

Before 2026-09 leave events were email-only and SMTP is unconfigured on the live
install, so approvers learned about requests and employees about decisions by
word of mouth. Several events (cancel, unapprove as seen by the approver,
reassignment, the next step's approver) sent nothing at all, and the "no
approver" broadcast named whoever typed the request instead of the employee.

Rules:
  * Every event creates an in-app notification (NotificationService) and, where
    SMTP is configured, an email.
  * notify_on_leave_request governs messages TO APPROVERS (a request is waiting,
    it changed, it was cancelled, a reminder, an escalation).
  * notify_on_leave_approval governs messages TO THE EMPLOYEE (a decision, an
    override, a reversal, expiry).
  * Emails capture plain strings, never ORM objects: they are sent after the
    request's session has closed.
"""

from __future__ import annotations

import html
from typing import Iterable, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.leave import LeaveApplication, LeaveType
from app.models.settings import AppSettings
from app.models.user import User
from app.services.email_service import EmailService
from app.services.notification_service import NotificationService

ACTION_TYPE = "leave_application"

TO_APPROVER = "approver"
TO_EMPLOYEE = "employee"

NOBODY_CAN_APPROVE_EMPLOYEE = (
    "Nobody in your company can approve leave yet. Your request is waiting, and "
    "your administrator has been told. It will go to an approver as soon as "
    "someone is given the role."
)
NOBODY_CAN_APPROVE_TITLE = "Nobody can approve leave"
NOBODY_CAN_APPROVE_ADMIN = (
    "Nobody can approve leave — give someone the HR or Leave approver role. "
    "Until then leave requests wait with no approver."
)


def _name(u) -> str:
    return f"{u.first_name} {u.last_name}".strip() if u else ""


class LeaveNotifier:
    def __init__(self, db: AsyncSession, tenant_id: UUID):
        self.db = db
        self.tenant_id = tenant_id
        self._flags: Optional[tuple] = None
        self._type_names: Optional[dict] = None

    async def _enabled(self, audience: str) -> bool:
        if self._flags is None:
            row = (
                await self.db.execute(
                    select(
                        AppSettings.notify_on_leave_request,
                        AppSettings.notify_on_leave_approval,
                    ).where(AppSettings.tenant_id == self.tenant_id)
                )
            ).one_or_none()
            # No settings row yet means nobody switched anything off.
            self._flags = (
                (True, True)
                if row is None
                else (row[0] is not False, row[1] is not False)
            )
        return self._flags[0] if audience == TO_APPROVER else self._flags[1]

    async def type_name(self, code: str) -> str:
        if self._type_names is None:
            rows = (
                await self.db.execute(
                    select(LeaveType.code, LeaveType.name).where(
                        LeaveType.tenant_id == self.tenant_id
                    )
                )
            ).all()
            self._type_names = {r[0]: r[1] for r in rows}
        return self._type_names.get(code) or code.replace("_", " ").title()

    async def describe(self, app: LeaveApplication) -> str:
        """'Vacation (2026-10-01 to 2026-10-03, 3 days)'."""
        days = app.days_requested
        span = (
            f"{app.start_date}"
            if app.start_date == app.end_date
            else f"{app.start_date} to {app.end_date}"
        )
        half = f", {app.half_day.upper()} half day" if getattr(app, "half_day", None) else ""
        return f"{await self.type_name(app.leave_type)} ({span}, {days:g} day{'s' if days != 1 else ''}{half})"

    async def _user(self, user_id: Optional[int]) -> Optional[User]:
        if user_id is None:
            return None
        return (
            await self.db.execute(
                select(User).where(User.id == user_id, User.tenant_id == self.tenant_id)
            )
        ).scalar_one_or_none()

    async def send(
        self,
        user_ids: Iterable[Optional[int]],
        *,
        audience: str,
        kind: str,
        title: str,
        body: str,
        app: LeaveApplication,
        email: Optional[dict] = None,
    ) -> int:
        """Notify each distinct user. Returns how many were notified.

        `email` picks a dedicated template: {"template": "request"|"approved"|
        "rejected", ...fields}; otherwise a plain email carrying title and body
        is sent.
        """
        if not await self._enabled(audience):
            return 0
        sent = 0
        for uid in dict.fromkeys(u for u in user_ids if u is not None):
            user = await self._user(uid)
            if user is None or not user.is_active:
                continue
            await NotificationService.notify(
                self.db,
                self.tenant_id,
                uid,
                type=kind,
                title=title,
                body=body,
                action_type=ACTION_TYPE,
                action_ref_id=app.id,
            )
            self._email(user.email, _name(user), title, body, email)
            sent += 1
        return sent

    @staticmethod
    def _email(to: str, to_name: str, title: str, body: str, spec: Optional[dict]) -> None:
        if not to:
            return
        spec = dict(spec or {})
        template = spec.pop("template", None)
        if template == "request":
            EmailService.fire_and_forget(
                lambda db, s=spec: EmailService.send_leave_request_notification(
                    db, approver_email=to, approver_name=to_name, **s
                )
            )
        elif template == "approved":
            EmailService.fire_and_forget(
                lambda db, s=spec: EmailService.send_leave_approved_email(
                    db, to_email=to, employee_name=to_name, **s
                )
            )
        elif template == "rejected":
            EmailService.fire_and_forget(
                lambda db, s=spec: EmailService.send_leave_rejected_email(
                    db, to_email=to, employee_name=to_name, **s
                )
            )
        else:
            from app.services.email_templates import _base_wrapper

            page = _base_wrapper(
                f"<h2 style=\"margin:0 0 12px\">{html.escape(title)}</h2>"
                f"<p style=\"margin:0\">{html.escape(body)}</p>"
            )
            EmailService.fire_and_forget(
                lambda db: EmailService.send_email(db, to, title, page, log_type="leave_event")
            )

    async def mark_resolved(self, app: LeaveApplication) -> None:
        """Clear the 'act on this' flag on earlier notifications about `app`,
        so an approver does not open a request that is no longer theirs."""
        await NotificationService.mark_actioned(self.db, self.tenant_id, ACTION_TYPE, app.id)

    # ── Composed messages ───────────────────────────────────────────

    async def nobody_can_approve(self, app: LeaveApplication) -> int:
        """Tell every active administrator that a request has no approver
        because nobody in the company can approve leave. Administrators do
        not approve leave themselves (permission_service), so the message is
        what to change, not a request to act on: it carries no link to the
        request, and it is sent whatever the leave notification settings say,
        since without it the request would wait unseen."""
        from app.models.role import Role, UserRole

        employee = await self._user(app.employee_id)
        what = await self.describe(app)
        body = f"{_name(employee)} requested {what}. " + NOBODY_CAN_APPROVE_ADMIN
        admins = (
            await self.db.execute(
                select(User)
                .join(UserRole, UserRole.user_id == User.id)
                .join(Role, Role.id == UserRole.role_id)
                .where(
                    User.tenant_id == self.tenant_id,
                    User.is_active == True,  # noqa: E712
                    Role.code == "tenant_admin",
                    Role.is_active == True,  # noqa: E712
                )
            )
        ).scalars().unique().all()
        for admin in admins:
            await NotificationService.notify(
                self.db, self.tenant_id, admin.id,
                type="leave_nobody_can_approve",
                title=NOBODY_CAN_APPROVE_TITLE,
                body=body,
            )
            self._email(admin.email, _name(admin), NOBODY_CAN_APPROVE_TITLE, body, None)
        return len(admins)

    async def request_waiting(self, app: LeaveApplication, approver_id: int, *, kind: str = "leave_request", lead: str = "") -> None:
        employee = await self._user(app.employee_id)
        what = await self.describe(app)
        title = f"Leave request from {_name(employee)} needs your approval"
        body = (lead + " " if lead else "") + f"{_name(employee)} requested {what}. Reason: {app.reason}"
        await self.send(
            [approver_id], audience=TO_APPROVER, kind=kind, title=title, body=body, app=app,
            email={
                "template": "request",
                "employee_name": _name(employee),
                "leave_type": await self.type_name(app.leave_type),
                "start_date": str(app.start_date),
                "end_date": str(app.end_date),
                "days": app.days_requested,
                "reason": app.reason,
            },
        )

    async def decided(self, app: LeaveApplication, *, approved: bool, by: str, notes: Optional[str]) -> None:
        what = await self.describe(app)
        if approved:
            title = "Your leave was approved"
            body = f"{by} approved your {what}."
        else:
            title = "Your leave was not approved"
            body = f"{by} rejected your {what}." + (f" Reason: {notes}" if notes else "")
        await self.send(
            [app.employee_id], audience=TO_EMPLOYEE,
            kind="leave_approved" if approved else "leave_rejected",
            title=title, body=body, app=app,
            email={
                "template": "approved" if approved else "rejected",
                "leave_type": await self.type_name(app.leave_type),
                "start_date": str(app.start_date),
                "end_date": str(app.end_date),
                "reviewer_name": by,
                **({} if approved else {"reviewer_notes": notes or ""}),
            },
        )
