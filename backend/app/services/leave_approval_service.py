from datetime import datetime, date
from typing import List, Optional
from uuid import UUID

from sqlalchemy import and_, extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.leave import LeaveApplication, LeaveApproverAssignment, LeavePolicy
from app.models.org_hierarchy import OrgNode
from app.models.role import LeaveApprovalStep, Role, UserRole
from app.models.user import User
from app.services.leave_service import LeaveService
from app.services.org_service import OrgService


class LeaveApprovalService:

    @staticmethod
    async def resolve_approval_chain(
        db: AsyncSession,
        tenant_id: UUID,
        employee_id: int,
        policy: LeavePolicy,
    ) -> List[dict]:
        """Resolve approval chain based on policy.approval_mode.

        Returns list of dicts:
            [{"approver_id": int, "approver_name": str, "step_order": int, "source": str}]

        Modes:
        - "auto":   Walk org hierarchy via OrgService.get_approval_chain()
        - "manual": Query LeaveApproverAssignment (employee → org_node → default)
        - "hybrid": Try manual first, fall back to auto
        """
        mode = policy.approval_mode or "auto"
        max_levels = policy.required_approval_levels or 1

        if mode == "auto":
            chain = await LeaveApprovalService._resolve_auto(db, tenant_id, employee_id)
        elif mode == "manual":
            chain = await LeaveApprovalService._resolve_manual(db, tenant_id, employee_id)
        elif mode == "hybrid":
            chain = await LeaveApprovalService._resolve_manual(db, tenant_id, employee_id)
            if not chain:
                chain = await LeaveApprovalService._resolve_auto(db, tenant_id, employee_id)
                for item in chain:
                    item["source"] = "hybrid_auto_fallback"
        else:
            chain = []

        # Exclude the employee themselves
        chain = [c for c in chain if c["approver_id"] != employee_id]

        # Fallback: if no approver could be resolved (no org head, no manual
        # assignment), fall back to the employee's line manager, then to the
        # tenant's admins/HR. Without this, applications would have an empty
        # chain and no one to act on them.
        if not chain:
            chain = await LeaveApprovalService._resolve_fallback(
                db, tenant_id, employee_id
            )

        # Limit to required_approval_levels
        chain = chain[:max_levels]

        # Re-assign step_order sequentially
        for i, item in enumerate(chain, start=1):
            item["step_order"] = i

        return chain

    @staticmethod
    async def _resolve_auto(
        db: AsyncSession, tenant_id: UUID, employee_id: int
    ) -> List[dict]:
        """Use org hierarchy to derive approval chain."""
        org_chain = await OrgService.get_approval_chain(db, employee_id, tenant_id)
        result = []
        for i, step in enumerate(org_chain, start=1):
            result.append({
                "approver_id": step["approver_id"],
                "approver_name": step["approver_name"],
                "step_order": i,
                "source": "auto",
            })
        return result

    @staticmethod
    async def _resolve_fallback(
        db: AsyncSession, tenant_id: UUID, employee_id: int
    ) -> List[dict]:
        """Last-resort approver resolution when no chain could be built.

        Order:
        1. The employee's line manager (users.reports_to_id), if active.
        2. The tenant's active admins/HR (tenant_admin, then hr).

        Never includes the employee themselves. Returns at most one approver so
        a fallback approval is a single, unambiguous step.
        """
        # 1. Line manager
        mgr_result = await db.execute(
            select(User.reports_to_id).where(
                User.id == employee_id, User.tenant_id == tenant_id
            )
        )
        manager_id = mgr_result.scalar_one_or_none()
        if manager_id and manager_id != employee_id:
            m_result = await db.execute(
                select(User.first_name, User.last_name).where(
                    User.id == manager_id,
                    User.tenant_id == tenant_id,
                    User.is_active == True,  # noqa: E712
                )
            )
            m = m_result.one_or_none()
            if m:
                return [{
                    "approver_id": manager_id,
                    "approver_name": f"{m.first_name} {m.last_name}",
                    "step_order": 1,
                    "source": "fallback_manager",
                }]

        # 2. Tenant admin / HR
        for role_code in ("tenant_admin", "hr"):
            admin_result = await db.execute(
                select(User.id, User.first_name, User.last_name)
                .join(UserRole, UserRole.user_id == User.id)
                .join(Role, Role.id == UserRole.role_id)
                .where(
                    User.tenant_id == tenant_id,
                    User.is_active == True,  # noqa: E712
                    User.id != employee_id,
                    Role.code == role_code,
                    Role.tenant_id == tenant_id,
                )
                .order_by(User.id)
                .limit(1)
            )
            row = admin_result.one_or_none()
            if row:
                return [{
                    "approver_id": row.id,
                    "approver_name": f"{row.first_name} {row.last_name}",
                    "step_order": 1,
                    "source": f"fallback_{role_code}",
                }]

        return []

    @staticmethod
    async def _resolve_manual(
        db: AsyncSession, tenant_id: UUID, employee_id: int
    ) -> List[dict]:
        """Resolve manual approval chain using priority-based rule matching.

        Rules are evaluated by priority (lower number = higher priority).
        First matching rule group wins, like firewall rules.
        If a matching rule has exclude=True, the employee is excluded from
        manual approval (returns empty chain).

        Match order within same priority:
        employee-specific → org_node (exact) → org_node (cascade) → default
        """
        # Get employee's org_node_id and ancestor chain
        user_result = await db.execute(
            select(User.org_node_id).where(
                User.id == employee_id, User.tenant_id == tenant_id
            )
        )
        org_node_id = user_result.scalar_one_or_none()

        # Build set of ancestor node IDs for cascade matching
        ancestor_node_ids = set()
        if org_node_id:
            ancestor_node_ids = await LeaveApprovalService._get_ancestor_node_ids(
                db, tenant_id, org_node_id
            )

        # Fetch ALL active rules for the tenant, ordered by priority then step_order
        stmt = (
            select(LeaveApproverAssignment)
            .options(selectinload(LeaveApproverAssignment.approver))
            .where(
                LeaveApproverAssignment.tenant_id == tenant_id,
                LeaveApproverAssignment.is_active == True,
            )
            .order_by(LeaveApproverAssignment.priority, LeaveApproverAssignment.step_order)
        )
        result = await db.execute(stmt)
        all_rules = list(result.scalars().all())

        if not all_rules:
            return []

        # Evaluate rules by priority — first matching priority group wins
        matched_rules: list = []
        matched_priority: int | None = None

        for rule in all_rules:
            # If we already found matches at a higher priority, skip lower ones
            if matched_priority is not None and rule.priority > matched_priority:
                break

            is_match = False
            source = "manual"

            if rule.employee_id is not None:
                # Employee-specific rule
                if rule.employee_id == employee_id:
                    is_match = True
                    source = "manual_employee"
            elif rule.org_node_id is not None:
                if org_node_id and rule.org_node_id == org_node_id:
                    # Exact org node match
                    is_match = True
                    source = "manual_org_node"
                elif rule.cascade and rule.org_node_id in ancestor_node_ids:
                    # Cascade match via ancestor
                    is_match = True
                    source = "manual_cascade"
            else:
                # Default rule (no employee_id, no org_node_id)
                is_match = True
                source = "manual_default"

            if is_match:
                if matched_priority is None:
                    matched_priority = rule.priority

                # Check for exclude — if any rule at this priority excludes,
                # the employee is excluded from manual approval entirely
                if rule.exclude:
                    return []

                matched_rules.append((rule, source))

        if not matched_rules:
            return []

        # Convert matched rules to chain (async to support role resolution)
        return await LeaveApprovalService._assignments_to_chain(
            db,
            [r for r, _ in matched_rules],
            matched_rules[0][1],
            employee_org_node_id=org_node_id,
        )

    @staticmethod
    async def _get_ancestor_node_ids(db: AsyncSession, tenant_id: UUID, org_node_id: int) -> set:
        """Walk up the org tree and return the set of all ancestor node IDs
        (excludes the node itself). Scoped to the tenant so the walk can never
        cross into another tenant's org tree."""
        ancestors = set()
        current_id = org_node_id
        visited = {current_id}

        while True:
            parent_stmt = select(OrgNode.parent_id).where(
                OrgNode.id == current_id, OrgNode.tenant_id == tenant_id
            )
            parent_result = await db.execute(parent_stmt)
            parent_id = parent_result.scalar_one_or_none()

            if not parent_id or parent_id in visited:
                break

            ancestors.add(parent_id)
            visited.add(parent_id)
            current_id = parent_id

        return ancestors

    @staticmethod
    async def _assignments_to_chain(
        db: AsyncSession,
        assignments: list,
        source: str,
        employee_org_node_id: Optional[int] = None,
    ) -> List[dict]:
        chain = []
        for a in assignments:
            approver_id = a.approver_id
            approver_name = ""

            if a.approver_role and not approver_id:
                # Dynamically resolve approver based on role
                resolved = await LeaveApprovalService._resolve_approver_role(
                    db, a, employee_org_node_id
                )
                if resolved:
                    approver_id, approver_name = resolved
                else:
                    continue  # Skip if role can't be resolved (no head/deputy assigned)
            elif a.approver:
                approver_name = f"{a.approver.first_name} {a.approver.last_name}"

            if approver_id:
                chain.append({
                    "approver_id": approver_id,
                    "approver_name": approver_name,
                    "step_order": a.step_order,
                    "source": source,
                })
        return chain

    @staticmethod
    async def _resolve_approver_role(
        db: AsyncSession,
        assignment: LeaveApproverAssignment,
        employee_org_node_id: Optional[int],
    ) -> Optional[tuple]:
        """Resolve approver_role to an actual user.

        Role resolution uses a reference org node:
        - For org_node scope rules: the rule's org_node_id
        - For employee scope rules: the target employee's org_node_id
        - For default scope rules: the requesting employee's org_node_id

        Roles:
        - node_head / node_deputy: head/deputy of the reference node
        - parent_head / parent_deputy: head/deputy of the reference node's parent

        Returns (user_id, full_name) or None if the position is vacant.
        """
        # Everything below is scoped to the assignment's tenant so role
        # resolution can never resolve into another tenant's org tree or users.
        tenant_id = assignment.tenant_id

        # Determine the reference node
        if assignment.org_node_id:
            ref_node_id = assignment.org_node_id
        elif assignment.employee_id:
            user_result = await db.execute(
                select(User.org_node_id).where(
                    User.id == assignment.employee_id, User.tenant_id == tenant_id
                )
            )
            ref_node_id = user_result.scalar_one_or_none()
        else:
            ref_node_id = employee_org_node_id

        if not ref_node_id:
            return None

        role = assignment.approver_role

        if role in ("node_head", "node_deputy"):
            target_node_id = ref_node_id
        elif role in ("parent_head", "parent_deputy"):
            parent_result = await db.execute(
                select(OrgNode.parent_id).where(
                    OrgNode.id == ref_node_id, OrgNode.tenant_id == tenant_id
                )
            )
            target_node_id = parent_result.scalar_one_or_none()
            if not target_node_id:
                return None
        else:
            return None

        # Fetch the target node with head/deputy user info
        if role in ("node_head", "parent_head"):
            col = OrgNode.head_user_id
        else:
            col = OrgNode.deputy_head_user_id

        node_result = await db.execute(
            select(col).where(
                OrgNode.id == target_node_id, OrgNode.tenant_id == tenant_id
            )
        )
        user_id = node_result.scalar_one_or_none()
        if not user_id:
            return None

        # Get user name
        user_result = await db.execute(
            select(User.first_name, User.last_name).where(
                User.id == user_id, User.tenant_id == tenant_id
            )
        )
        user_row = user_result.one_or_none()
        if not user_row:
            return None

        return (user_id, f"{user_row.first_name} {user_row.last_name}")

    @staticmethod
    async def create_approval_steps(
        db: AsyncSession,
        leave_application_id: int,
        chain: List[dict],
    ) -> List[LeaveApprovalStep]:
        """Create LeaveApprovalStep records from resolved chain."""
        steps = []
        for item in chain:
            step = LeaveApprovalStep(
                leave_application_id=leave_application_id,
                approver_id=item["approver_id"],
                step_order=item["step_order"],
                status="pending",
            )
            db.add(step)
            steps.append(step)
        await db.flush()
        return steps

    @staticmethod
    async def process_step_decision(
        db: AsyncSession,
        application: LeaveApplication,
        step: LeaveApprovalStep,
        action: str,
        notes: Optional[str],
        reviewer_id: int,
    ) -> str:
        """Process approve/reject on a step.

        Returns final application status: "pending" | "approved" | "rejected"
        """
        step.status = "approved" if action == "approve" else "rejected"
        step.decided_at = datetime.utcnow()
        step.notes = notes

        if action == "reject":
            application.status = "rejected"
            application.reviewed_by = reviewer_id
            application.reviewed_at = datetime.utcnow()
            application.reviewer_notes = notes
            await db.flush()
            return "rejected"

        # Action is approve - check if there are more pending steps
        pending_stmt = (
            select(func.count(LeaveApprovalStep.id))
            .where(
                LeaveApprovalStep.leave_application_id == application.id,
                LeaveApprovalStep.status == "pending",
                LeaveApprovalStep.id != step.id,  # exclude current step
            )
        )
        pending_result = await db.execute(pending_stmt)
        remaining = pending_result.scalar() or 0

        if remaining == 0:
            # All steps approved, mark application as approved
            application.status = "approved"
            application.reviewed_by = reviewer_id
            application.reviewed_at = datetime.utcnow()
            application.reviewer_notes = notes
            await db.flush()
            return "approved"

        # More steps remain
        await db.flush()
        return "pending"

    @staticmethod
    async def get_pending_for_approver(
        db: AsyncSession,
        tenant_id: UUID,
        approver_id: int,
        page: int = 1,
        per_page: int = 20,
    ):
        """Get leave applications where approver is the current pending step approver."""
        # Find applications where:
        # 1. There's a pending step for this approver
        # 2. All previous steps (lower step_order) are approved
        pending_app_ids_stmt = (
            select(LeaveApprovalStep.leave_application_id)
            .where(
                LeaveApprovalStep.approver_id == approver_id,
                LeaveApprovalStep.status == "pending",
            )
        )
        pending_result = await db.execute(pending_app_ids_stmt)
        candidate_app_ids = [row[0] for row in pending_result.all()]

        if not candidate_app_ids:
            return [], 0

        # Filter: only apps where it's actually this approver's turn
        valid_app_ids = []
        for app_id in candidate_app_ids:
            # Get the step for this approver
            step_stmt = select(LeaveApprovalStep).where(
                LeaveApprovalStep.leave_application_id == app_id,
                LeaveApprovalStep.approver_id == approver_id,
                LeaveApprovalStep.status == "pending",
            )
            step_result = await db.execute(step_stmt)
            step = step_result.scalar_one_or_none()
            if not step:
                continue

            # Check all previous steps are approved
            prev_stmt = (
                select(func.count(LeaveApprovalStep.id))
                .where(
                    LeaveApprovalStep.leave_application_id == app_id,
                    LeaveApprovalStep.step_order < step.step_order,
                    LeaveApprovalStep.status != "approved",
                )
            )
            prev_result = await db.execute(prev_stmt)
            blocked = prev_result.scalar() or 0
            if blocked == 0:
                valid_app_ids.append(app_id)

        total = len(valid_app_ids)
        paged_ids = valid_app_ids[(page - 1) * per_page : page * per_page]

        if not paged_ids:
            return [], total

        # Fetch applications
        stmt = (
            select(LeaveApplication)
            .options(
                selectinload(LeaveApplication.employee),
                selectinload(LeaveApplication.reviewer),
                selectinload(LeaveApplication.approval_steps).selectinload(
                    LeaveApprovalStep.approver
                ),
            )
            .where(
                LeaveApplication.id.in_(paged_ids),
                LeaveApplication.tenant_id == tenant_id,
                LeaveApplication.status == "pending",
            )
            .order_by(LeaveApplication.created_at.desc())
        )
        result = await db.execute(stmt)
        applications = list(result.scalars().all())

        return applications, total

    @staticmethod
    async def get_supervised_employee_ids(
        db: AsyncSession, tenant_id: UUID, user_id: int
    ) -> List[int]:
        """Get employee IDs that this user supervises.

        Checks:
        1. LeaveApproverAssignment: any employees assigned to this user as approver
        2. Org hierarchy: members of nodes where this user is head/deputy head
        """
        employee_ids = set()

        # 1. From LeaveApproverAssignment
        stmt = (
            select(LeaveApproverAssignment.employee_id)
            .where(
                LeaveApproverAssignment.tenant_id == tenant_id,
                LeaveApproverAssignment.approver_id == user_id,
                LeaveApproverAssignment.is_active == True,
                LeaveApproverAssignment.employee_id.isnot(None),
            )
        )
        result = await db.execute(stmt)
        for row in result.all():
            employee_ids.add(row[0])

        # 2. From org hierarchy (nodes where user is head or deputy)
        nodes_stmt = (
            select(OrgNode.id)
            .where(
                OrgNode.tenant_id == tenant_id,
                OrgNode.is_active == True,
                (OrgNode.head_user_id == user_id) | (OrgNode.deputy_head_user_id == user_id),
            )
        )
        nodes_result = await db.execute(nodes_stmt)
        node_ids = [row[0] for row in nodes_result.all()]

        if node_ids:
            members_stmt = (
                select(User.id)
                .where(
                    User.tenant_id == tenant_id,
                    User.org_node_id.in_(node_ids),
                    User.is_active == True,
                    User.id != user_id,
                )
            )
            members_result = await db.execute(members_stmt)
            for row in members_result.all():
                employee_ids.add(row[0])

        return list(employee_ids)

    @staticmethod
    async def get_team_stats(
        db: AsyncSession,
        tenant_id: UUID,
        user_id: int,
        is_admin: bool,
    ) -> dict:
        """Return leave statistics scoped to supervised employees.

        HR/admin see all. Others see only their supervised employees.
        Returns: {summary, by_type, by_month, by_status}
        """
        year_start = date(date.today().year, 1, 1)
        year_end = date(date.today().year, 12, 31)

        # Determine employee scope
        if is_admin:
            scope_filter = LeaveApplication.tenant_id == tenant_id
        else:
            emp_ids = await LeaveApprovalService.get_supervised_employee_ids(
                db, tenant_id, user_id
            )
            if not emp_ids:
                return {
                    "summary": {"total": 0, "pending": 0, "approved": 0, "rejected": 0},
                    "by_type": [],
                    "by_month": [],
                    "by_status": {"pending": 0, "approved": 0, "rejected": 0},
                }
            scope_filter = and_(
                LeaveApplication.tenant_id == tenant_id,
                LeaveApplication.employee_id.in_(emp_ids),
            )

        base_filter = and_(
            scope_filter,
            LeaveApplication.start_date >= year_start,
            LeaveApplication.end_date <= year_end,
        )

        # Summary counts
        summary_stmt = (
            select(
                func.count(LeaveApplication.id).label("total"),
                func.count(LeaveApplication.id).filter(
                    LeaveApplication.status == "pending"
                ).label("pending"),
                func.count(LeaveApplication.id).filter(
                    LeaveApplication.status == "approved"
                ).label("approved"),
                func.count(LeaveApplication.id).filter(
                    LeaveApplication.status == "rejected"
                ).label("rejected"),
            )
            .where(base_filter)
        )
        summary_result = await db.execute(summary_stmt)
        row = summary_result.one()
        summary = {
            "total": row.total or 0,
            "pending": row.pending or 0,
            "approved": row.approved or 0,
            "rejected": row.rejected or 0,
        }

        # By type
        by_type_stmt = (
            select(
                LeaveApplication.leave_type,
                func.count(LeaveApplication.id).label("count"),
                func.coalesce(func.sum(LeaveApplication.days_requested), 0).label("days"),
            )
            .where(base_filter)
            .group_by(LeaveApplication.leave_type)
            .order_by(func.count(LeaveApplication.id).desc())
        )
        by_type_result = await db.execute(by_type_stmt)
        by_type = [
            {"leave_type": r.leave_type, "count": r.count, "days": float(r.days)}
            for r in by_type_result.all()
        ]

        # By month
        by_month_stmt = (
            select(
                extract("month", LeaveApplication.start_date).label("month"),
                func.count(LeaveApplication.id).label("count"),
                func.coalesce(func.sum(LeaveApplication.days_requested), 0).label("days"),
            )
            .where(base_filter)
            .group_by(extract("month", LeaveApplication.start_date))
            .order_by(extract("month", LeaveApplication.start_date))
        )
        by_month_result = await db.execute(by_month_stmt)
        month_names = [
            "", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
            "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"
        ]
        by_month = [
            {
                "month": month_names[int(r.month)] if int(r.month) <= 12 else str(r.month),
                "count": r.count,
                "days": float(r.days),
            }
            for r in by_month_result.all()
        ]

        # By status
        by_status_stmt = (
            select(
                LeaveApplication.status,
                func.count(LeaveApplication.id).label("count"),
            )
            .where(base_filter)
            .group_by(LeaveApplication.status)
        )
        by_status_result = await db.execute(by_status_stmt)
        by_status = {r.status: r.count for r in by_status_result.all()}

        return {
            "summary": summary,
            "by_type": by_type,
            "by_month": by_month,
            "by_status": by_status,
        }

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
                LeaveApprovalStep.status == "pending",
            )
            .order_by(LeaveApprovalStep.step_order)
            .limit(1)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()
