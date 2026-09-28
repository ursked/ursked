"""The approval chain: who approves a leave request, in what order, and what
happens to the chain as the request moves.

How the chain is resolved (the one function every caller uses: filing, the
employee's "who approves me" preview, the admin chain tester and the org chart's
approval-chain view, so they can never disagree):

  1. The employee's leave policy picks a mode.
       auto    the org chart: the head of the employee's unit, then the head of
               each unit above it.
       manual  the approver rule that applies to the employee. Rule priority
               decides WHICH rule applies (then how specific it is: an
               employee rule beats a unit rule beats a sub-unit rule beats the
               default); the chain is that rule's own ordered approvers.
       hybrid  the rule's approvers first, then org-chart heads after them.
  2. The requester, inactive users and repeats are dropped; an inactive or
     vacant approver is skipped and the next candidate moves up. A unit head who
     is vacant, inactive or on approved leave today is replaced by the unit's
     deputy when there is one.
  3. The list is cut to the policy's required approval levels.
  4. If nobody is left: the employee's line manager, else a full-scope user
     with leave:edit (admin, then HR), else anyone else with leave:edit.
  5. If there is still nobody (a company whose only admin files leave), the
     single step is the requester's own, and it can only be completed through
     the explicit, audit-logged self-approval action.

Every request therefore has at least one step. The legacy "no steps, any
reviewer may approve" path is gone: it let any manager approve any request
company-wide, and let the only admin approve their own leave unrecorded.
"""

from datetime import date, datetime
from types import SimpleNamespace
from typing import Iterable, List, Optional
from uuid import UUID

from sqlalchemy import and_, exists, extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from app.models.leave import (
    LeaveApplication,
    LeaveApprovalEvent,
    LeaveApproverAssignment,
    LeaveApproverRuleStep,
    LeavePolicy,
    LeaveType,
)
from app.models.org_hierarchy import OrgNode
from app.models.role import LeaveApprovalStep
from app.models.user import User
from app.services.leave_service import LeaveService

# Step status vocabulary. "skipped" is a step that will never be decided
# because the request left "pending" some other way (rejected at an earlier
# step, cancelled, expired, approved by override). Leaving those "pending"
# inflated every approver's "Pending my review" count.
STEP_PENDING = "pending"
STEP_APPROVED = "approved"
STEP_REJECTED = "rejected"
STEP_SKIPPED = "skipped"

SOURCE_SELF = "self_approval"


def _name(u) -> str:
    return f"{u.first_name} {u.last_name}".strip() if u else ""


async def set_status(
    db: AsyncSession,
    application: LeaveApplication,
    new_status: str,
    *,
    actor=None,
) -> None:
    """Change a request's status and tell the rest of the app.

    Area F excuses absences when leave is approved (and un-excuses them when it
    is revoked) by listening for leave.status_changed, so every transition must
    go through here rather than assigning `status` directly.
    """
    from app.services import domain_events

    old = application.status
    if old == new_status:
        return
    application.status = new_status
    await db.flush()
    await domain_events.emit(
        "leave.status_changed",
        db=db,
        tenant_id=application.tenant_id,
        actor=actor,
        application=application,
        old_status=old,
        new_status=new_status,
    )


async def record_event(
    db: AsyncSession,
    application: LeaveApplication,
    action: str,
    *,
    actor_id: Optional[int] = None,
    step: Optional[LeaveApprovalStep] = None,
    from_approver_id: Optional[int] = None,
    to_approver_id: Optional[int] = None,
    reason: Optional[str] = None,
    on_date: Optional[date] = None,
    audit: bool = True,
) -> LeaveApprovalEvent:
    """Ledger row shown on the request, plus an audit_logs row for the
    actions a person takes on someone else's behalf."""
    ev = LeaveApprovalEvent(
        tenant_id=application.tenant_id,
        leave_application_id=application.id,
        step_id=step.id if step is not None else None,
        action=action,
        actor_id=actor_id,
        from_approver_id=from_approver_id,
        to_approver_id=to_approver_id,
        reason=reason,
        on_date=on_date,
    )
    db.add(ev)
    if audit:
        from app.models.site_settings import AuditLog

        db.add(AuditLog(
            tenant_id=application.tenant_id,
            user_id=actor_id,
            action=f"leave_{action}",
            resource_type="leave_application",
            resource_id=str(application.id),
            details={
                "step_id": step.id if step is not None else None,
                "from_approver_id": from_approver_id,
                "to_approver_id": to_approver_id,
                "reason": reason,
                "employee_id": application.employee_id,
            },
        ))
    await db.flush()
    return ev


class LeaveApprovalService:

    # ── Resolution ───────────────────────────────────────────────────

    @staticmethod
    async def resolve_chain_for_employee(
        db: AsyncSession,
        tenant_id: UUID,
        employee: User,
        *,
        exclude_ids: Iterable[int] = (),
        on_date: Optional[date] = None,
    ) -> List[dict]:
        """The chain a request filed now by `employee` would get."""
        policy = await LeaveService.get_policy_for_employee(
            db, tenant_id, getattr(employee, "employee_type", None)
        )
        return await LeaveApprovalService.resolve_approval_chain(
            db, tenant_id, employee.id, policy, exclude_ids=exclude_ids, on_date=on_date
        )

    @staticmethod
    async def resolve_approval_chain(
        db: AsyncSession,
        tenant_id: UUID,
        employee_id: int,
        policy: Optional[LeavePolicy],
        *,
        exclude_ids: Iterable[int] = (),
        on_date: Optional[date] = None,
    ) -> List[dict]:
        """Resolve the approval chain (see the module docstring).

        Returns [{"approver_id", "approver_name", "step_order", "source",
        "is_deputy", "node_name"}], never empty.
        """
        today = on_date or date.today()
        excluded = {e for e in exclude_ids if e is not None}
        mode = (policy.approval_mode if policy is not None else None) or "auto"
        max_levels = max(1, (policy.required_approval_levels if policy is not None else 1) or 1)

        candidates: List[dict] = []
        if policy is not None and mode in ("manual", "hybrid"):
            candidates += await LeaveApprovalService._resolve_manual(
                db, tenant_id, employee_id, on_date=today
            )
        if policy is None or mode in ("auto", "hybrid"):
            auto = await LeaveApprovalService._resolve_auto(
                db, tenant_id, employee_id, on_date=today
            )
            if mode == "hybrid":
                for item in auto:
                    item["source"] = "hybrid_org_chart"
            candidates += auto

        chain = await LeaveApprovalService._clean(
            db, tenant_id, candidates, exclude={employee_id} | excluded
        )
        chain = chain[:max_levels]

        if not chain:
            chain = await LeaveApprovalService._resolve_fallback(
                db, tenant_id, employee_id, exclude=excluded
            )
        if not chain:
            chain = await LeaveApprovalService._resolve_any_editor(
                db, tenant_id, employee_id, exclude=excluded
            )
        if not chain:
            me = (
                await db.execute(
                    select(User.first_name, User.last_name).where(
                        User.id == employee_id, User.tenant_id == tenant_id
                    )
                )
            ).one_or_none()
            chain = [{
                "approver_id": employee_id,
                "approver_name": f"{me.first_name} {me.last_name}" if me else "",
                "source": SOURCE_SELF,
                "is_deputy": False,
                "node_name": None,
            }]

        for i, item in enumerate(chain, start=1):
            item["step_order"] = i
            item.setdefault("is_deputy", False)
            item.setdefault("node_name", None)
        return chain

    @staticmethod
    async def _clean(
        db: AsyncSession, tenant_id: UUID, candidates: List[dict], *, exclude: set
    ) -> List[dict]:
        """Drop excluded, inactive and repeated approvers, keeping order.

        The same person can surface twice (head of two nested units, or named
        by a rule and again by the org chart in hybrid mode); approving twice
        in a row is noise, so they keep their first, earliest step only.
        """
        ids = {c["approver_id"] for c in candidates if c.get("approver_id")}
        active = set()
        if ids:
            active = set(
                (
                    await db.execute(
                        select(User.id).where(
                            User.id.in_(ids),
                            User.tenant_id == tenant_id,
                            User.is_active == True,  # noqa: E712
                        )
                    )
                ).scalars().all()
            )
        seen: set = set()
        out = []
        for c in candidates:
            aid = c.get("approver_id")
            if not aid or aid in exclude or aid in seen or aid not in active:
                continue
            seen.add(aid)
            out.append(dict(c))
        return out

    @staticmethod
    async def _on_leave(db: AsyncSession, user_id: int, today: date) -> bool:
        return bool(
            (
                await db.execute(
                    select(func.count())
                    .select_from(LeaveApplication)
                    .where(
                        LeaveApplication.employee_id == user_id,
                        LeaveApplication.status == "approved",
                        LeaveApplication.start_date <= today,
                        LeaveApplication.end_date >= today,
                    )
                )
            ).scalar()
        )

    @staticmethod
    async def _active_user(db: AsyncSession, tenant_id: UUID, user_id: Optional[int]) -> Optional[User]:
        if not user_id:
            return None
        return (
            await db.execute(
                select(User).where(
                    User.id == user_id,
                    User.tenant_id == tenant_id,
                    User.is_active == True,  # noqa: E712
                )
            )
        ).scalar_one_or_none()

    @staticmethod
    async def _unit_approver(
        db: AsyncSession,
        tenant_id: UUID,
        node: OrgNode,
        today: date,
        *,
        requester_id: Optional[int] = None,
    ) -> Optional[tuple]:
        """The person who approves for a unit: its head, or its deputy standing
        in. Returns (user_id, name, is_deputy) or None.

        The deputy stands in when the head is vacant, inactive or on approved
        leave today. A head who is merely on leave with no deputy stays the
        approver (reminders and escalation cover the wait); an inactive head
        with no deputy is skipped. This is what the approval-rules screen says
        about "Alternate Manager", and the org-chart route now does the same.
        """
        head = await LeaveApprovalService._active_user(db, tenant_id, node.head_user_id)
        deputy = await LeaveApprovalService._active_user(db, tenant_id, node.deputy_head_user_id)
        if deputy is not None and deputy.id == requester_id:
            deputy = None
        if head is not None and not await LeaveApprovalService._on_leave(db, head.id, today):
            return head.id, _name(head), False
        if deputy is not None and not await LeaveApprovalService._on_leave(db, deputy.id, today):
            return deputy.id, _name(deputy), True
        if head is not None:
            return head.id, _name(head), False
        if deputy is not None:
            return deputy.id, _name(deputy), True
        return None

    @staticmethod
    async def _resolve_auto(
        db: AsyncSession, tenant_id: UUID, employee_id: int, *, on_date: Optional[date] = None
    ) -> List[dict]:
        """Org-chart heads from the employee's unit upwards."""
        today = on_date or date.today()
        org_node_id = (
            await db.execute(
                select(User.org_node_id).where(User.id == employee_id, User.tenant_id == tenant_id)
            )
        ).scalar_one_or_none()
        if not org_node_id:
            return []

        nodes = {
            n.id: n
            for n in (
                await db.execute(select(OrgNode).where(OrgNode.tenant_id == tenant_id))
            ).scalars().all()
        }
        chain: List[dict] = []
        current = org_node_id
        # The visited set guarantees termination; hierarchies can be any depth.
        visited: set = set()
        while current and current not in visited:
            visited.add(current)
            node = nodes.get(current)
            if node is None:
                break
            current = node.parent_id
            if not node.is_active:
                continue
            # A head never approves their own leave; the unit above does.
            if node.head_user_id == employee_id:
                continue
            picked = await LeaveApprovalService._unit_approver(
                db, tenant_id, node, today, requester_id=employee_id
            )
            if picked is None:
                continue
            uid, name, is_deputy = picked
            chain.append({
                "approver_id": uid,
                "approver_name": name,
                "source": "auto",
                "is_deputy": is_deputy,
                "node_name": node.name,
            })
        return chain

    @staticmethod
    async def _resolve_fallback(
        db: AsyncSession,
        tenant_id: UUID,
        employee_id: int,
        *,
        exclude: Iterable[int] = (),
    ) -> List[dict]:
        """Last-resort approver when the policy's chain is empty.

        1. The employee's line manager (users.reports_to_id), if active.
        2. A full-scope user with leave:edit: an admin, then HR.

        Never includes the employee themselves. Returns at most one approver so
        a fallback approval is a single, unambiguous step.
        """
        from app.services.leave_access import leave_editors

        excluded = {e for e in exclude if e is not None} | {employee_id}
        manager_id = (
            await db.execute(
                select(User.reports_to_id).where(User.id == employee_id, User.tenant_id == tenant_id)
            )
        ).scalar_one_or_none()
        if manager_id and manager_id not in excluded:
            m = await LeaveApprovalService._active_user(db, tenant_id, manager_id)
            if m is not None:
                return [{
                    "approver_id": m.id,
                    "approver_name": _name(m),
                    "step_order": 1,
                    "source": "fallback_manager",
                }]

        editors = await leave_editors(db, tenant_id, full_scope_only=True, exclude=excluded)
        if editors:
            uid, first, last, code = editors[0]
            return [{
                "approver_id": uid,
                "approver_name": f"{first} {last}",
                "step_order": 1,
                "source": f"fallback_{code}",
            }]
        return []

    @staticmethod
    async def _resolve_any_editor(
        db: AsyncSession, tenant_id: UUID, employee_id: int, *, exclude: Iterable[int] = ()
    ) -> List[dict]:
        """Anyone else who holds leave:edit, whatever their scope."""
        from app.services.leave_access import leave_editors

        editors = await leave_editors(
            db, tenant_id, exclude={employee_id, *[e for e in exclude if e is not None]}
        )
        if not editors:
            return []
        uid, first, last, _code = editors[0]
        return [{
            "approver_id": uid,
            "approver_name": f"{first} {last}",
            "step_order": 1,
            "source": "fallback_leave_editor",
        }]

    @staticmethod
    def _rule_steps(rule: LeaveApproverAssignment) -> list:
        steps = list(rule.steps or [])
        if steps:
            return steps
        # A rule written without step rows (only possible for rows inserted
        # outside the API) still means its own single approver.
        if rule.approver_id or rule.approver_role:
            return [SimpleNamespace(step_order=1, approver_id=rule.approver_id, approver_role=rule.approver_role)]
        return []

    @staticmethod
    def _rule_scope(rule: LeaveApproverAssignment) -> tuple:
        return (rule.employee_id, rule.org_node_id, bool(rule.cascade) if rule.org_node_id else False)

    @staticmethod
    async def match_rule(
        db: AsyncSession, tenant_id: UUID, employee_id: int
    ) -> Optional[tuple]:
        """The approver rule that applies to an employee: (rule, source, group).

        `group` is the rule plus any legacy rules with the same scope and
        priority, which before 2026-09 were how a multi-step chain was written.
        """
        org_node_id = (
            await db.execute(
                select(User.org_node_id).where(User.id == employee_id, User.tenant_id == tenant_id)
            )
        ).scalar_one_or_none()
        ancestors = set()
        if org_node_id:
            ancestors = await LeaveApprovalService._get_ancestor_node_ids(db, tenant_id, org_node_id)

        rules = (
            await db.execute(
                select(LeaveApproverAssignment)
                .options(selectinload(LeaveApproverAssignment.steps))
                .where(
                    LeaveApproverAssignment.tenant_id == tenant_id,
                    LeaveApproverAssignment.is_active == True,  # noqa: E712
                )
            )
        ).scalars().all()

        matches = []
        for r in rules:
            if r.employee_id is not None:
                if r.employee_id == employee_id:
                    matches.append((r, 0, "manual_employee"))
            elif r.org_node_id is not None:
                if org_node_id and r.org_node_id == org_node_id:
                    matches.append((r, 1, "manual_org_node"))
                elif r.cascade and r.org_node_id in ancestors:
                    matches.append((r, 2, "manual_cascade"))
            else:
                matches.append((r, 3, "manual_default"))
        if not matches:
            return None
        matches.sort(key=lambda m: (m[0].priority, m[1], m[0].id))
        winner, _spec, source = matches[0]
        key = LeaveApprovalService._rule_scope(winner)
        group = [
            m[0] for m in matches
            if m[0].priority == winner.priority
            and LeaveApprovalService._rule_scope(m[0]) == key
            and not m[0].exclude
        ]
        return winner, source, group

    @staticmethod
    async def _resolve_manual(
        db: AsyncSession, tenant_id: UUID, employee_id: int, *, on_date: Optional[date] = None
    ) -> List[dict]:
        """The ordered approvers of the rule that applies to the employee.

        An "exclude" rule that wins means the employee is outside manual
        approval: in hybrid mode the org chart takes over, otherwise the
        fallback does.
        """
        today = on_date or date.today()
        found = await LeaveApprovalService.match_rule(db, tenant_id, employee_id)
        if found is None:
            return []
        winner, source, group = found
        if winner.exclude:
            return []

        employee_org_node_id = (
            await db.execute(
                select(User.org_node_id).where(User.id == employee_id, User.tenant_id == tenant_id)
            )
        ).scalar_one_or_none()

        ordered = []
        for r in group:
            for st in LeaveApprovalService._rule_steps(r):
                ordered.append((r.step_order or 1, st.step_order or 1, r.id, r, st))
        ordered.sort(key=lambda t: t[:3])

        chain: List[dict] = []
        for _ro, _so, _rid, rule, st in ordered:
            if st.approver_role:
                resolved = await LeaveApprovalService._resolve_approver_role(
                    db, rule, employee_org_node_id,
                    role=st.approver_role, requester_id=employee_id, today=today,
                )
                if resolved is None:
                    continue  # vacant position: skipped, the next step moves up
                uid, name, is_deputy = resolved
                chain.append({"approver_id": uid, "approver_name": name, "source": source, "is_deputy": is_deputy})
            elif st.approver_id:
                u = await LeaveApprovalService._active_user(db, tenant_id, st.approver_id)
                if u is None:
                    continue  # inactive approver: skipped, the next step moves up
                chain.append({"approver_id": u.id, "approver_name": _name(u), "source": source, "is_deputy": False})
        return chain

    @staticmethod
    async def _get_ancestor_node_ids(db: AsyncSession, tenant_id: UUID, org_node_id: int) -> set:
        """Walk up the org tree and return the set of all ancestor node IDs
        (excludes the node itself). Scoped to the tenant so the walk can never
        cross into another tenant's org tree."""
        ancestors = set()
        current_id = org_node_id
        visited = {current_id}

        while True:
            parent_id = (
                await db.execute(
                    select(OrgNode.parent_id).where(
                        OrgNode.id == current_id, OrgNode.tenant_id == tenant_id
                    )
                )
            ).scalar_one_or_none()
            if not parent_id or parent_id in visited:
                break
            ancestors.add(parent_id)
            visited.add(parent_id)
            current_id = parent_id

        return ancestors

    @staticmethod
    async def _resolve_approver_role(
        db: AsyncSession,
        assignment: LeaveApproverAssignment,
        employee_org_node_id: Optional[int],
        *,
        role: Optional[str] = None,
        requester_id: Optional[int] = None,
        today: Optional[date] = None,
    ) -> Optional[tuple]:
        """Resolve a position (node_head, node_deputy, parent_head,
        parent_deputy) to a person: (user_id, name, is_deputy) or None.

        The reference unit is the rule's unit for unit rules, else the
        employee's own unit. "Head" positions use the deputy when the head is
        vacant, inactive or on leave; "deputy" positions always mean the deputy.
        """
        tenant_id = assignment.tenant_id
        role = role or assignment.approver_role
        today = today or date.today()

        if assignment.org_node_id:
            ref_node_id = assignment.org_node_id
        elif assignment.employee_id:
            ref_node_id = (
                await db.execute(
                    select(User.org_node_id).where(
                        User.id == assignment.employee_id, User.tenant_id == tenant_id
                    )
                )
            ).scalar_one_or_none()
        else:
            ref_node_id = employee_org_node_id
        if not ref_node_id:
            return None

        if role in ("node_head", "node_deputy"):
            target_id = ref_node_id
        elif role in ("parent_head", "parent_deputy"):
            target_id = (
                await db.execute(
                    select(OrgNode.parent_id).where(
                        OrgNode.id == ref_node_id, OrgNode.tenant_id == tenant_id
                    )
                )
            ).scalar_one_or_none()
            if not target_id:
                return None
        else:
            return None

        node = (
            await db.execute(
                select(OrgNode).where(OrgNode.id == target_id, OrgNode.tenant_id == tenant_id)
            )
        ).scalar_one_or_none()
        if node is None:
            return None

        if role in ("node_head", "parent_head"):
            return await LeaveApprovalService._unit_approver(
                db, tenant_id, node, today, requester_id=requester_id
            )
        deputy = await LeaveApprovalService._active_user(db, tenant_id, node.deputy_head_user_id)
        if deputy is None:
            return None
        return deputy.id, _name(deputy), True

    # ── Steps ────────────────────────────────────────────────────────

    @staticmethod
    async def create_approval_steps(
        db: AsyncSession,
        leave_application_id: int,
        chain: List[dict],
        *,
        tenant_id: Optional[UUID] = None,
        employee_id: Optional[int] = None,
        granted_by: Optional[int] = None,
    ) -> List[LeaveApprovalStep]:
        """Create LeaveApprovalStep records from a resolved chain.

        Anyone who ends up approving (a unit head, a line manager) gets a
        reviewer role if they had none, so the request is never routed to
        someone with no screen to act on it.
        """
        from app.services.leave_access import ensure_reviewer_role

        steps = []
        for item in chain:
            if tenant_id is not None and item["approver_id"] != employee_id:
                await ensure_reviewer_role(
                    db, tenant_id, item["approver_id"],
                    granted_by=granted_by, context="routed a leave request",
                )
            step = LeaveApprovalStep(
                leave_application_id=leave_application_id,
                approver_id=item["approver_id"],
                step_order=item["step_order"],
                status=STEP_PENDING,
            )
            db.add(step)
            steps.append(step)
        await db.flush()
        return steps

    @staticmethod
    async def ensure_steps(db: AsyncSession, application: LeaveApplication) -> bool:
        """Give a pending request filed before 2026-09 with no steps a chain.

        Those requests relied on the removed "any reviewer may approve" path;
        without steps nobody could act on them now. Returns True if steps were
        created (the caller should reload the request)."""
        if application.status != "pending" or application.approval_steps:
            return False
        employee = (
            await db.execute(select(User).where(User.id == application.employee_id))
        ).scalar_one_or_none()
        if employee is None:
            return False
        chain = await LeaveApprovalService.resolve_chain_for_employee(
            db, application.tenant_id, employee
        )
        await LeaveApprovalService.create_approval_steps(
            db, application.id, chain,
            tenant_id=application.tenant_id, employee_id=employee.id,
        )
        return True

    @staticmethod
    def current_step(application: LeaveApplication) -> Optional[LeaveApprovalStep]:
        """The step waiting for a decision now: the first pending step, if every
        step before it is approved."""
        for s in sorted(application.approval_steps or [], key=lambda s: s.step_order):
            if s.status == STEP_APPROVED:
                continue
            return s if s.status == STEP_PENDING else None
        return None

    @staticmethod
    def is_self_step(application: LeaveApplication, step: Optional[LeaveApprovalStep]) -> bool:
        return step is not None and step.approver_id == application.employee_id

    @staticmethod
    def skip_open_steps(application: LeaveApplication, *, note: Optional[str] = None) -> None:
        for s in application.approval_steps or []:
            if s.status == STEP_PENDING:
                s.status = STEP_SKIPPED
                s.decided_at = datetime.utcnow()
                if note:
                    s.notes = note

    @staticmethod
    async def process_step_decision(
        db: AsyncSession,
        application: LeaveApplication,
        step: LeaveApprovalStep,
        action: str,
        notes: Optional[str],
        reviewer_id: int,
        *,
        actor=None,
    ) -> str:
        """Process approve/reject on a step.

        Returns final application status: "pending" | "approved" | "rejected"
        """
        step.status = STEP_APPROVED if action == "approve" else STEP_REJECTED
        step.decided_at = datetime.utcnow()
        step.notes = notes

        if action == "reject":
            LeaveApprovalService.skip_open_steps(application)
            application.reviewed_by = reviewer_id
            application.reviewed_at = datetime.utcnow()
            application.reviewer_notes = notes
            await set_status(db, application, "rejected", actor=actor)
            return "rejected"

        remaining = [
            s for s in (application.approval_steps or [])
            if s.id != step.id and s.status == STEP_PENDING
        ]
        if not remaining:
            application.reviewed_by = reviewer_id
            application.reviewed_at = datetime.utcnow()
            application.reviewer_notes = notes
            await set_status(db, application, "approved", actor=actor)
            return "approved"

        await db.flush()
        return "pending"

    @staticmethod
    async def reassign_step(
        db: AsyncSession,
        application: LeaveApplication,
        step: LeaveApprovalStep,
        new_approver_id: int,
        *,
        actor_id: Optional[int],
        reason: Optional[str],
        action: str = "reassign",
        on_date: Optional[date] = None,
    ) -> None:
        from app.services.leave_access import ensure_reviewer_role

        old = step.approver_id
        await ensure_reviewer_role(
            db, application.tenant_id, new_approver_id,
            granted_by=actor_id, context="assigned a leave approval step",
        )
        step.approver_id = new_approver_id
        await record_event(
            db, application, action,
            actor_id=actor_id, step=step,
            from_approver_id=old, to_approver_id=new_approver_id,
            reason=reason, on_date=on_date,
        )

    @staticmethod
    async def replacement_approver(
        db: AsyncSession,
        application: LeaveApplication,
        leaving_id: int,
        *,
        prefer_manager_of: Optional[int] = None,
    ) -> Optional[dict]:
        """Who should take over a step from `leaving_id`.

        Tries the approver's own line manager first (escalation), then whoever
        the request's chain would resolve to without them and without anyone
        already on the chain, then the full-scope fallback. Never the requester.
        """
        tenant_id = application.tenant_id
        taken = {s.approver_id for s in application.approval_steps or [] if s.approver_id}
        banned = {application.employee_id, leaving_id}
        if prefer_manager_of is not None:
            mgr_id = (
                await db.execute(
                    select(User.reports_to_id).where(
                        User.id == prefer_manager_of, User.tenant_id == tenant_id
                    )
                )
            ).scalar_one_or_none()
            m = await LeaveApprovalService._active_user(db, tenant_id, mgr_id)
            if m is not None and m.id not in banned and m.id not in taken:
                return {"approver_id": m.id, "approver_name": _name(m), "source": "approver_manager"}

        employee = (
            await db.execute(select(User).where(User.id == application.employee_id))
        ).scalar_one_or_none()
        if employee is not None:
            chain = await LeaveApprovalService.resolve_chain_for_employee(
                db, tenant_id, employee, exclude_ids=banned | taken
            )
            for c in chain:
                if c["source"] != SOURCE_SELF and c["approver_id"] not in banned | taken:
                    return c
        fb = await LeaveApprovalService._resolve_fallback(
            db, tenant_id, application.employee_id, exclude=banned
        )
        return fb[0] if fb else None

    # ── Queues and stats ─────────────────────────────────────────────

    @staticmethod
    async def get_pending_for_approver(
        db: AsyncSession,
        tenant_id: UUID,
        approver_id: int,
        page: int = 1,
        per_page: int = 20,
    ):
        """Pending requests whose CURRENT step is this approver's.

        Only requests still pending count; steps left open on cancelled or
        rejected requests used to be counted here and inflated the badge. A
        requester's own self-approval step is not a review task and is offered
        on their own request instead.
        """
        prev = aliased(LeaveApprovalStep)
        blocked = exists().where(
            prev.leave_application_id == LeaveApprovalStep.leave_application_id,
            prev.step_order < LeaveApprovalStep.step_order,
            prev.status != STEP_APPROVED,
        )
        base = (
            select(LeaveApplication.id)
            .join(LeaveApprovalStep, LeaveApprovalStep.leave_application_id == LeaveApplication.id)
            .where(
                LeaveApplication.tenant_id == tenant_id,
                LeaveApplication.status == "pending",
                LeaveApplication.employee_id != approver_id,
                LeaveApprovalStep.approver_id == approver_id,
                LeaveApprovalStep.status == STEP_PENDING,
                ~blocked,
            )
            .distinct()
        )
        total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0
        if not total:
            return [], 0

        stmt = (
            select(LeaveApplication)
            .options(
                selectinload(LeaveApplication.employee),
                selectinload(LeaveApplication.reviewer),
                selectinload(LeaveApplication.approval_steps).selectinload(LeaveApprovalStep.approver),
                selectinload(LeaveApplication.events),
            )
            .where(LeaveApplication.id.in_(base))
            .order_by(LeaveApplication.created_at.desc(), LeaveApplication.id.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
        applications = list((await db.execute(stmt)).scalars().all())
        return applications, total

    @staticmethod
    async def get_supervised_employee_ids(
        db: AsyncSession, tenant_id: UUID, user_id: int
    ) -> List[int]:
        """Employees this user supervises: named on an employee rule for them,
        or members of units they head or deputise."""
        employee_ids = set()
        rows = (
            await db.execute(
                select(LeaveApproverAssignment.employee_id)
                .join(
                    LeaveApproverRuleStep,
                    LeaveApproverRuleStep.assignment_id == LeaveApproverAssignment.id,
                    isouter=True,
                )
                .where(
                    LeaveApproverAssignment.tenant_id == tenant_id,
                    LeaveApproverAssignment.is_active == True,  # noqa: E712
                    LeaveApproverAssignment.employee_id.isnot(None),
                    (LeaveApproverAssignment.approver_id == user_id)
                    | (LeaveApproverRuleStep.approver_id == user_id),
                )
            )
        ).all()
        employee_ids.update(r[0] for r in rows)

        node_ids = (
            await db.execute(
                select(OrgNode.id).where(
                    OrgNode.tenant_id == tenant_id,
                    OrgNode.is_active == True,  # noqa: E712
                    (OrgNode.head_user_id == user_id) | (OrgNode.deputy_head_user_id == user_id),
                )
            )
        ).scalars().all()
        if node_ids:
            employee_ids.update(
                (
                    await db.execute(
                        select(User.id).where(
                            User.tenant_id == tenant_id,
                            User.org_node_id.in_(node_ids),
                            User.is_active == True,  # noqa: E712
                            User.id != user_id,
                        )
                    )
                ).scalars().all()
            )
        return list(employee_ids)

    @staticmethod
    async def get_team_stats(db: AsyncSession, tenant_id: UUID, scope_filter, *, year: Optional[int] = None) -> dict:
        """Leave statistics for this year over the requests `scope_filter`
        selects, which is the same filter as the Team Overview table so the
        table and the numbers above it can never disagree."""
        year = year or date.today().year
        year_start = date(year, 1, 1)
        year_end = date(year, 12, 31)
        base_filter = and_(
            LeaveApplication.tenant_id == tenant_id,
            scope_filter,
            LeaveApplication.start_date <= year_end,
            LeaveApplication.end_date >= year_start,
        )

        row = (
            await db.execute(
                select(
                    func.count(LeaveApplication.id).label("total"),
                    func.count(LeaveApplication.id).filter(LeaveApplication.status == "pending").label("pending"),
                    func.count(LeaveApplication.id).filter(LeaveApplication.status == "approved").label("approved"),
                    func.count(LeaveApplication.id).filter(LeaveApplication.status == "rejected").label("rejected"),
                ).where(base_filter)
            )
        ).one()
        summary = {
            "total": row.total or 0,
            "pending": row.pending or 0,
            "approved": row.approved or 0,
            "rejected": row.rejected or 0,
        }

        type_names = {
            r[0]: r[1]
            for r in (
                await db.execute(
                    select(LeaveType.code, LeaveType.name).where(LeaveType.tenant_id == tenant_id)
                )
            ).all()
        }
        by_type = [
            {
                "leave_type": r.leave_type,
                "leave_type_name": type_names.get(r.leave_type) or r.leave_type.replace("_", " ").title(),
                "count": r.count,
                "days": float(r.days),
            }
            for r in (
                await db.execute(
                    select(
                        LeaveApplication.leave_type,
                        func.count(LeaveApplication.id).label("count"),
                        func.coalesce(func.sum(LeaveApplication.days_requested), 0).label("days"),
                    )
                    .where(base_filter)
                    .group_by(LeaveApplication.leave_type)
                    .order_by(func.count(LeaveApplication.id).desc())
                )
            ).all()
        ]

        month_names = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
                       "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        by_month = [
            {
                "month": month_names[int(r.month)] if int(r.month) <= 12 else str(r.month),
                "count": r.count,
                "days": float(r.days),
            }
            for r in (
                await db.execute(
                    select(
                        extract("month", LeaveApplication.start_date).label("month"),
                        func.count(LeaveApplication.id).label("count"),
                        func.coalesce(func.sum(LeaveApplication.days_requested), 0).label("days"),
                    )
                    .where(base_filter)
                    .group_by(extract("month", LeaveApplication.start_date))
                    .order_by(extract("month", LeaveApplication.start_date))
                )
            ).all()
        ]

        by_status = {
            r.status: r.count
            for r in (
                await db.execute(
                    select(LeaveApplication.status, func.count(LeaveApplication.id).label("count"))
                    .where(base_filter)
                    .group_by(LeaveApplication.status)
                )
            ).all()
        }

        return {"summary": summary, "by_type": by_type, "by_month": by_month, "by_status": by_status}

    @staticmethod
    async def get_next_pending_step(
        db: AsyncSession, application_id: int
    ) -> Optional[LeaveApprovalStep]:
        """Get the next pending approval step for an application."""
        stmt = (
            select(LeaveApprovalStep)
            .options(selectinload(LeaveApprovalStep.approver))
            .where(
                LeaveApprovalStep.leave_application_id == application_id,
                LeaveApprovalStep.status == STEP_PENDING,
            )
            .order_by(LeaveApprovalStep.step_order)
            .limit(1)
        )
        return (await db.execute(stmt)).scalar_one_or_none()
