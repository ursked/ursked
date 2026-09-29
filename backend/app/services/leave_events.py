"""Leave's reactions to other areas' changes (domain_events handlers).

employee.separated: someone who leaves the company must stop holding up other
people's leave. Before 2026-09 separating an employee cleaned up nothing, so
every request waiting on them sat there until someone noticed, and approval
rules kept routing new requests to a person who could no longer sign in.
"""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from app.models.leave import LeaveApplication, LeaveApproverAssignment, LeaveApproverRuleStep
from app.models.org_hierarchy import OrgNode
from app.models.role import LeaveApprovalStep
from app.services.domain_events import on


def _name(u) -> str:
    return f"{u.first_name} {u.last_name}".strip() if u else ""


@on("employee.separated")
async def release_separated_approver(db, tenant_id, actor, user, **_):
    """Hand the separated person's pending steps to the next valid approver,
    switch off the approval rules that name them, and take them off the units
    they headed or deputised. Admins are told what changed."""
    from app.services.leave_access import leave_editors
    from app.services.leave_approval_service import LeaveApprovalService
    from app.services.leave_notify_service import TO_EMPLOYEE, LeaveNotifier
    from app.services.notification_service import NotificationService

    who = _name(user)
    actor_id = getattr(actor, "id", None)
    notifier = LeaveNotifier(db, tenant_id)

    # 1. Pending steps assigned to them, on requests still pending.
    apps = (
        await db.execute(
            select(LeaveApplication)
            .options(
                selectinload(LeaveApplication.approval_steps),
                selectinload(LeaveApplication.employee),
            )
            .join(LeaveApprovalStep, LeaveApprovalStep.leave_application_id == LeaveApplication.id)
            .where(
                LeaveApplication.tenant_id == tenant_id,
                LeaveApplication.status == "pending",
                LeaveApplication.employee_id != user.id,
                LeaveApprovalStep.approver_id == user.id,
                LeaveApprovalStep.status == "pending",
            )
            .distinct()
        )
    ).scalars().all()
    moved = 0
    for app in apps:
        for step in [s for s in app.approval_steps if s.approver_id == user.id and s.status == "pending"]:
            repl = await LeaveApprovalService.replacement_approver(db, app, user.id)
            if repl is None:
                continue
            await LeaveApprovalService.reassign_step(
                db, app, step, repl["approver_id"], actor_id=actor_id,
                reason=f"{who} left the company.", action="auto_reassign",
            )
            moved += 1
            if LeaveApprovalService.current_step(app) is step:
                await notifier.request_waiting(
                    app, repl["approver_id"], kind="leave_reassigned",
                    lead=f"{who}, who was going to approve this, has left the company.",
                )
            await notifier.send(
                [app.employee_id], audience=TO_EMPLOYEE, kind="leave_reassigned",
                title="Your leave request has a new approver",
                body=(
                    f"{who} has left the company, so your {await notifier.describe(app)} now goes to "
                    f"{repl['approver_name']}."
                ),
                app=app,
            )

    # 2. Approval rules naming them: switched off, not deleted, with the reason
    # shown next to the rule.
    step_rule_ids = select(LeaveApproverRuleStep.assignment_id).where(
        LeaveApproverRuleStep.approver_id == user.id
    )
    rules = (
        await db.execute(
            select(LeaveApproverAssignment).where(
                LeaveApproverAssignment.tenant_id == tenant_id,
                LeaveApproverAssignment.is_active == True,  # noqa: E712
                or_(
                    LeaveApproverAssignment.approver_id == user.id,
                    LeaveApproverAssignment.id.in_(step_rule_ids),
                ),
            )
        )
    ).scalars().all()
    for rule in rules:
        rule.is_active = False
        rule.deactivated_reason = f"{who}, one of its approvers, left the company."

    # 3. Units they headed or deputised.
    nodes = (
        await db.execute(
            select(OrgNode).where(
                OrgNode.tenant_id == tenant_id,
                or_(OrgNode.head_user_id == user.id, OrgNode.deputy_head_user_id == user.id),
            )
        )
    ).scalars().all()
    units = []
    for node in nodes:
        if node.head_user_id == user.id:
            node.head_user_id = None
            units.append(f"{node.name} (head)")
        if node.deputy_head_user_id == user.id:
            node.deputy_head_user_id = None
            units.append(f"{node.name} (deputy)")
    await db.flush()

    if not (moved or rules or units):
        return
    parts = []
    if moved:
        parts.append(f"{moved} pending leave approval step(s) were passed to the next approver")
    if rules:
        parts.append(f"{len(rules)} approval rule(s) that named them were switched off; review them under Policies, Approval Rules")
    if units:
        parts.append("they were removed as " + ", ".join(units) + "; choose a replacement on the Organization page")
    body = f"{who} has left the company. " + "; ".join(parts) + "."
    # Told to HR (who review leave) and to the administrators, who fix what
    # this names: approver rules and unit heads are configuration, and since
    # 2026-09-29 administrators no longer count as leave editors.
    from app.services.employee_access import active_admin_ids

    recipients = {r[0] for r in await leave_editors(db, tenant_id, full_scope_only=True, exclude={user.id})}
    recipients |= await active_admin_ids(db, tenant_id) - {user.id}
    for uid in sorted(recipients):
        await NotificationService.notify(
            db, tenant_id, uid, type="approver_separated",
            title=f"{who} no longer approves leave",
            body=body,
        )
