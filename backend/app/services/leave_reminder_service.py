"""Daily nudges for leave requests nobody is deciding.

Before 2026-09 a request could wait forever: no reminder, no escalation, and a
request whose dates had passed stayed "pending" indefinitely, still holding
the employee's balance. This job, safe to call every minute, does three things
for each tenant, judged by the tenant's own date:

  reminder   the current approver is reminded once a day after the step has
             waited AppSettings.leave_reminder_after_days (default 2).
  escalate   after leave_escalate_after_days (default 5; 0 = never) the step
             moves to the approver's fallback: their line manager, else an
             admin/HR with leave:edit. Once per step.
  expire     a request still pending after its last day becomes "expired";
             the employee and the approver are told and the days are released.

Idempotent: every reminder, escalation and expiry leaves a row in
leave_approval_events, and a unique index on (step, action, day) makes a
second worker racing the first fail its insert instead of sending twice.

Registered by dotted path: app.services.leave_reminder_service.run_due
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.leave import LeaveApplication, LeaveApprovalEvent
from app.models.role import LeaveApprovalStep
from app.models.settings import AppSettings
from app.models.tenant import Tenant
from app.models.user import User

logger = logging.getLogger(__name__)


def _as_date(ts) -> Optional[date]:
    if ts is None:
        return None
    if isinstance(ts, datetime):
        if ts.tzinfo is not None:
            ts = ts.astimezone(timezone.utc)
        return ts.date()
    return ts


def _name(u) -> str:
    return f"{u.first_name} {u.last_name}".strip() if u else ""


async def _claim(db: AsyncSession, app, step, action: str, today: date, **fields) -> bool:
    """Write the once-a-day ledger row. False if it already exists (this job
    ran already today, or another worker got there first)."""
    exists = (
        await db.execute(
            select(LeaveApprovalEvent.id).where(
                LeaveApprovalEvent.step_id == (step.id if step is not None else None),
                LeaveApprovalEvent.leave_application_id == app.id,
                LeaveApprovalEvent.action == action,
                LeaveApprovalEvent.on_date == today,
            )
        )
    ).first()
    if exists:
        return False
    try:
        async with db.begin_nested():
            db.add(LeaveApprovalEvent(
                tenant_id=app.tenant_id,
                leave_application_id=app.id,
                step_id=step.id if step is not None else None,
                action=action,
                on_date=today,
                **fields,
            ))
    except IntegrityError:
        return False
    return True


async def _waiting_since(app, step) -> Optional[date]:
    """When the current step became this approver's to decide."""
    candidates = [_as_date(step.created_at)]
    for s in app.approval_steps:
        if s.step_order < step.step_order and s.decided_at:
            candidates.append(_as_date(s.decided_at))
    for ev in app.events or []:
        if ev.step_id == step.id and ev.action in ("reassign", "auto_reassign", "escalate"):
            # on_date is the tenant's day the job acted on; prefer it.
            candidates.append(ev.on_date or _as_date(ev.created_at))
    candidates = [c for c in candidates if c is not None]
    return max(candidates) if candidates else None


async def _escalation_target(db: AsyncSession, app, step) -> Optional[User]:
    from app.services.leave_access import leave_editors

    banned = {app.employee_id, step.approver_id}
    approver = await db.get(User, step.approver_id) if step.approver_id else None
    if approver is not None and approver.reports_to_id and approver.reports_to_id not in banned:
        mgr = await db.get(User, approver.reports_to_id)
        if mgr is not None and mgr.is_active and mgr.tenant_id == app.tenant_id:
            return mgr
    editors = await leave_editors(db, app.tenant_id, full_scope_only=True, exclude=banned)
    if editors:
        return await db.get(User, editors[0][0])
    return None


async def run_for_tenant(db: AsyncSession, tenant_id, today: date, settings: Optional[AppSettings]) -> dict:
    from app.services.leave_approval_service import LeaveApprovalService, set_status
    from app.services.leave_notify_service import TO_APPROVER, TO_EMPLOYEE, LeaveNotifier

    remind_after = (settings.leave_reminder_after_days if settings else None) or 2
    escalate_after = settings.leave_escalate_after_days if settings and settings.leave_escalate_after_days is not None else 5
    notifier = LeaveNotifier(db, tenant_id)
    out = {"reminded": 0, "escalated": 0, "expired": 0}

    # Read the ledger fresh: a session reused across runs would otherwise see
    # the events collections as they were on the first run.
    db.expire_all()
    apps = (
        await db.execute(
            select(LeaveApplication)
            .options(
                selectinload(LeaveApplication.approval_steps).selectinload(LeaveApprovalStep.approver),
                selectinload(LeaveApplication.events),
                selectinload(LeaveApplication.employee),
            )
            .where(LeaveApplication.tenant_id == tenant_id, LeaveApplication.status == "pending")
        )
    ).scalars().all()

    for app in apps:
        if await LeaveApprovalService.ensure_steps(db, app):
            await db.refresh(app, ["approval_steps"])
            step = LeaveApprovalService.current_step(app)
            if step is not None and step.approver_id != app.employee_id:
                await notifier.request_waiting(app, step.approver_id)
            continue
        step = LeaveApprovalService.current_step(app)

        if app.end_date < today:
            if not await _claim(db, app, None, "expire", today,
                                reason="Still pending after its last day."):
                continue
            LeaveApprovalService.skip_open_steps(app, note="Expired: not decided before its last day.")
            await set_status(db, app, "expired", actor=None)
            out["expired"] += 1
            what = await notifier.describe(app)
            await notifier.mark_resolved(app)
            await notifier.send(
                [app.employee_id], audience=TO_EMPLOYEE, kind="leave_expired",
                title="Your leave request expired",
                body=f"Your {what} was not decided before its last day, so it has expired. The days are back in your balance.",
                app=app,
            )
            if step is not None and step.approver_id != app.employee_id:
                await notifier.send(
                    [step.approver_id], audience=TO_APPROVER, kind="leave_expired",
                    title="A leave request expired before it was decided",
                    body=f"{_name(app.employee)}'s {what} passed its last day while waiting for you and has expired.",
                    app=app,
                )
            continue

        if step is None or step.approver_id is None or step.approver_id == app.employee_id:
            continue  # self-approval steps are the employee's own to act on
        since = await _waiting_since(app, step)
        if since is None:
            continue
        waited = (today - since).days

        already_escalated = any(e.step_id == step.id and e.action == "escalate" for e in app.events or [])
        if escalate_after and waited >= escalate_after and not already_escalated:
            target = await _escalation_target(db, app, step)
            if target is not None and await _claim(
                db, app, step, "escalate", today,
                from_approver_id=step.approver_id, to_approver_id=target.id,
                reason=f"Waited {waited} days without a decision.",
            ):
                old = step.approver
                from app.services.leave_access import ensure_reviewer_role

                await ensure_reviewer_role(db, tenant_id, target.id, context="leave approval escalated to them")
                step.approver_id = target.id
                await db.flush()
                out["escalated"] += 1
                await notifier.request_waiting(
                    app, target.id, kind="leave_escalated",
                    lead=f"It waited {waited} days for {_name(old)}, so it has been passed to you.",
                )
                what = await notifier.describe(app)
                await notifier.send(
                    [app.employee_id], audience=TO_EMPLOYEE, kind="leave_escalated",
                    title="Your leave request was passed to another approver",
                    body=f"Your {what} waited {waited} days for {_name(old)}, so it now goes to {_name(target)}.",
                    app=app,
                )
                if old is not None:
                    await notifier.send(
                        [old.id], audience=TO_APPROVER, kind="leave_escalated",
                        title="A leave request was passed on after waiting for you",
                        body=f"{_name(app.employee)}'s {what} waited {waited} days and now goes to {_name(target)}.",
                        app=app,
                    )
                continue

        if waited >= remind_after and await _claim(db, app, step, "reminder", today, to_approver_id=step.approver_id):
            out["reminded"] += 1
            await notifier.request_waiting(
                app, step.approver_id, kind="leave_reminder",
                lead=f"Reminder: this has been waiting for your decision for {waited} days.",
            )

    await db.flush()
    return out


async def run_due(db: AsyncSession, *, now: Optional[datetime] = None) -> dict:
    """Entry point for the scheduler. Idempotent; commits its own work."""
    from app.services.leave_yearend_service import LeaveYearEndService

    totals = {"tenants": 0, "reminded": 0, "escalated": 0, "expired": 0}
    tenants = (await db.execute(select(Tenant))).scalars().all()
    settings = {s.tenant_id: s for s in (await db.execute(select(AppSettings))).scalars().all()}
    for tenant in tenants:
        s = settings.get(tenant.id)
        tz = (s.timezone if s else None) or getattr(tenant, "timezone", None)
        today = LeaveYearEndService._tenant_today(tz, now)
        try:
            res = await run_for_tenant(db, tenant.id, today, s)
            await db.commit()
        except Exception:  # noqa: BLE001
            logger.exception("Leave reminders failed for tenant %s", tenant.id)
            await db.rollback()
            continue
        totals["tenants"] += 1
        for k in ("reminded", "escalated", "expired"):
            totals[k] += res[k]
    return totals
