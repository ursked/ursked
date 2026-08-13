import csv
import io
from collections import defaultdict
from datetime import date, timedelta
from typing import Dict, List, Optional
from uuid import UUID

from sqlalchemy import and_, delete, extract, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.schedule import DateRemark, ScheduleSnapshot, ScheduleTemplate, Shift
from app.models.settings import AppSettings, ShiftStatusType
from app.models.org_hierarchy import NodeScheduleVisibility, OrgNode
from app.models.configurable_types import UserOrgNode
from app.models.leave import LeaveApplication, LeaveApproverAssignment
from app.models.user import User


class ScheduleConflictError(Exception):
    """Raised when a shift-creation request violates leave overlap or a
    tenant schedule guardrail (consecutive-days / rest-days).

    ``conflicts`` is a list of {employee_id, date, type, message} dicts so the
    API layer can surface exactly what blocked the request. The editor may
    retry with force=True to override guardrail (but never leave) conflicts.
    """

    def __init__(self, conflicts: List[dict]):
        self.conflicts = conflicts
        super().__init__(f"{len(conflicts)} scheduling conflict(s)")


class ScheduleService:
    # ── Schedule Visibility ──────────────────────────────────────────────

    @staticmethod
    async def _get_descendant_node_ids(
        db: AsyncSession, node_ids: List[int], tenant_id: UUID
    ) -> List[int]:
        """Collect all descendant node IDs from a set of root nodes (BFS).

        No depth cap: a `visited` set bounds the walk to each node once, so it
        terminates for any tree depth (and is safe even against corrupt cyclic
        data), while supporting arbitrarily deep hierarchies."""
        visited: set[int] = set(node_ids)
        current_layer = list(node_ids)
        while current_layer:
            stmt = select(OrgNode.id).where(
                OrgNode.tenant_id == tenant_id,
                OrgNode.parent_id.in_(current_layer),
                OrgNode.is_active == True,  # noqa: E712
            )
            result = await db.execute(stmt)
            children = [row[0] for row in result.all() if row[0] not in visited]
            if not children:
                break
            visited.update(children)
            current_layer = children
        return list(visited)

    @staticmethod
    async def _get_user_node_ids(
        db: AsyncSession, user_id: int, tenant_id: UUID
    ) -> List[int]:
        """All org nodes a user belongs to: the primary (User.org_node_id) AND
        every secondary assignment (UserOrgNode). Multi-node staff (e.g. someone
        who splits time across two teams) should be scoped to all of them."""
        node_ids: set[int] = set()
        primary = (
            await db.execute(
                select(User.org_node_id).where(
                    User.id == user_id, User.tenant_id == tenant_id
                )
            )
        ).one_or_none()
        if primary and primary[0]:
            node_ids.add(primary[0])
        secondary = await db.execute(
            select(UserOrgNode.org_node_id)
            .join(User, User.id == UserOrgNode.user_id)
            .where(UserOrgNode.user_id == user_id, User.tenant_id == tenant_id)
        )
        for row in secondary.all():
            if row[0]:
                node_ids.add(row[0])
        return list(node_ids)

    @staticmethod
    async def _get_node_member_ids(
        db: AsyncSession, node_ids: List[int], tenant_id: UUID
    ) -> List[int]:
        """All active users who belong to any of the given nodes — counting both
        the primary assignment (User.org_node_id) AND secondary ones
        (UserOrgNode). Returns [] for an empty node set."""
        if not node_ids:
            return []
        member_ids: set[int] = set()
        primary = await db.execute(
            select(User.id).where(
                User.tenant_id == tenant_id,
                User.org_node_id.in_(node_ids),
                User.is_active == True,  # noqa: E712
            )
        )
        for row in primary.all():
            member_ids.add(row[0])
        secondary = await db.execute(
            select(UserOrgNode.user_id)
            .join(User, User.id == UserOrgNode.user_id)
            .where(
                User.tenant_id == tenant_id,
                UserOrgNode.org_node_id.in_(node_ids),
                User.is_active == True,  # noqa: E712
            )
        )
        for row in secondary.all():
            member_ids.add(row[0])
        return list(member_ids)

    # Valid schedule-visibility modes. "inherit" means "use the parent node's
    # effective mode" (and ultimately the tenant default at the root).
    _VISIBILITY_MODES = {"own_node", "own_and_children", "own_and_parent", "all"}

    @staticmethod
    async def _effective_node_visibility(
        db: AsyncSession, node_id: int, tenant_id: UUID, tenant_default: str
    ) -> str:
        """Resolve a node's effective visibility mode.

        A node may set schedule_visibility to override; when unset (NULL /
        'inherit') it walks up to the nearest ancestor that sets one, falling
        back to the tenant-wide default at the root. A visited set bounds the
        walk against corrupt cyclic parent links."""
        visited: set[int] = set()
        current: Optional[int] = node_id
        while current is not None and current not in visited:
            visited.add(current)
            row = (
                await db.execute(
                    select(OrgNode.schedule_visibility, OrgNode.parent_id).where(
                        OrgNode.id == current, OrgNode.tenant_id == tenant_id
                    )
                )
            ).one_or_none()
            if row is None:
                break
            mode, parent_id = row[0], row[1]
            if mode and mode in ScheduleService._VISIBILITY_MODES:
                return mode
            current = parent_id
        return tenant_default if tenant_default in ScheduleService._VISIBILITY_MODES else "own_node"

    @staticmethod
    async def get_visible_employee_ids(
        db: AsyncSession,
        tenant_id: UUID,
        current_user_id: int,
        user_roles: List[str],
    ) -> Optional[List[int]]:
        """Determine which employee IDs the current user can see in the schedule.

        Returns None if the user can see ALL employees (admin roles).
        Returns a list of visible employee IDs otherwise.
        """
        admin_roles = {"tenant_admin", "hr", "schedule_editor"}
        if admin_roles.intersection(set(user_roles)):
            return None  # No filter — see everyone

        # Load tenant visibility setting
        settings_stmt = select(AppSettings).where(AppSettings.tenant_id == tenant_id)
        settings_result = await db.execute(settings_stmt)
        settings = settings_result.scalar_one_or_none()
        visibility = getattr(settings, "schedule_employee_visibility", "own_node") if settings else "own_node"

        # Always include self
        visible_ids: set = {current_user_id}

        # All nodes the user belongs to (primary + secondary assignments).
        user_node_ids = await ScheduleService._get_user_node_ids(
            db, current_user_id, tenant_id
        )

        # ── Supervisor scope: nodes where user is head/deputy ─────────
        head_nodes_stmt = (
            select(OrgNode.id)
            .where(
                OrgNode.tenant_id == tenant_id,
                OrgNode.is_active == True,
                or_(
                    OrgNode.head_user_id == current_user_id,
                    OrgNode.deputy_head_user_id == current_user_id,
                ),
            )
        )
        head_nodes_result = await db.execute(head_nodes_stmt)
        head_node_ids = [row[0] for row in head_nodes_result.all()]

        if head_node_ids:
            # A supervisor sees their whole subtree, members counted via primary
            # AND secondary assignment.
            all_supervised_node_ids = await ScheduleService._get_descendant_node_ids(
                db, head_node_ids, tenant_id
            )
            visible_ids.update(
                await ScheduleService._get_node_member_ids(
                    db, all_supervised_node_ids, tenant_id
                )
            )

        # Also check explicit approver assignments
        approver_stmt = (
            select(LeaveApproverAssignment.employee_id)
            .where(
                LeaveApproverAssignment.tenant_id == tenant_id,
                LeaveApproverAssignment.approver_id == current_user_id,
                LeaveApproverAssignment.is_active == True,
                LeaveApproverAssignment.employee_id.isnot(None),
            )
        )
        approver_result = await db.execute(approver_stmt)
        for row in approver_result.all():
            visible_ids.add(row[0])

        # ── Explicit per-node grants ──────────────────────────────────
        # An admin can grant a user visibility into a specific node's schedule
        # (and, by default, its subtree) even when they don't head it.
        grants_stmt = select(
            NodeScheduleVisibility.org_node_id,
            NodeScheduleVisibility.include_descendants,
        ).where(
            NodeScheduleVisibility.tenant_id == tenant_id,
            NodeScheduleVisibility.user_id == current_user_id,
        )
        grants_result = await db.execute(grants_stmt)
        granted_rows = grants_result.all()
        if granted_rows:
            granted_node_ids: set[int] = set()
            roots_with_descendants = [r[0] for r in granted_rows if r[1]]
            granted_node_ids.update(r[0] for r in granted_rows)
            if roots_with_descendants:
                granted_node_ids.update(
                    await ScheduleService._get_descendant_node_ids(
                        db, roots_with_descendants, tenant_id
                    )
                )
            visible_ids.update(
                await ScheduleService._get_node_member_ids(
                    db, list(granted_node_ids), tenant_id
                )
            )

        # ── Regular employee scope ────────────────────────────────────
        # Effective visibility mode is resolved PER NODE: a node may override the
        # tenant-wide default (own_node / own_and_children / own_and_parent / all),
        # inheriting from its ancestors when unset. Applied to every node the user
        # belongs to (so multi-node staff get the union).
        for node_id in user_node_ids:
            mode = await ScheduleService._effective_node_visibility(
                db, node_id, tenant_id, visibility
            )
            if mode == "all":
                return None  # No filter — this node grants full visibility

            scope_node_ids: set[int] = {node_id}
            if mode == "own_and_children":
                scope_node_ids.update(
                    await ScheduleService._get_descendant_node_ids(
                        db, [node_id], tenant_id
                    )
                )
            elif mode == "own_and_parent":
                parent_row = (
                    await db.execute(
                        select(OrgNode.parent_id).where(
                            OrgNode.id == node_id, OrgNode.tenant_id == tenant_id
                        )
                    )
                ).one_or_none()
                if parent_row and parent_row[0]:
                    scope_node_ids.add(parent_row[0])

            visible_ids.update(
                await ScheduleService._get_node_member_ids(
                    db, list(scope_node_ids), tenant_id
                )
            )

        return list(visible_ids)

    # ── Schedule Grid ───────────────────────────────────────────────────

    @staticmethod
    async def get_schedule_grid(
        db: AsyncSession,
        tenant_id: UUID,
        start_date: date,
        end_date: date,
        department_id: Optional[int] = None,
        section_id: Optional[int] = None,
        org_node_id: Optional[int] = None,
        search: Optional[str] = None,
        visible_employee_ids: Optional[List[int]] = None,
        published_only: bool = False,
    ) -> dict:
        """
        Fetch the schedule grid: employees with their shifts in the given
        date range, grouped by employee, plus date remarks and aggregate stats.

        ``published_only`` hides DRAFT (unpublished) shifts — used for the
        employee-facing view so staff only ever see a released schedule.
        """
        # 1. Build the user query with filters
        user_stmt = (
            select(User)
            .options(selectinload(User.section), selectinload(User.unit))
            .where(User.tenant_id == tenant_id, User.is_active == True)
        )

        if department_id:
            user_stmt = user_stmt.where(User.department_id == department_id)

        if section_id:
            user_stmt = user_stmt.where(User.section_id == section_id)

        # Org-node scope: include employees assigned to the node OR any of its
        # descendants (a Division selection covers all its Depts/Sections/Teams).
        if org_node_id:
            node_ids = await ScheduleService._get_descendant_node_ids(
                db, [org_node_id], tenant_id
            )
            user_stmt = user_stmt.where(User.org_node_id.in_(node_ids))

        if search:
            search_filter = (
                User.first_name.ilike(f"%{search}%")
                | User.last_name.ilike(f"%{search}%")
                | User.email.ilike(f"%{search}%")
                | User.username.ilike(f"%{search}%")
            )
            user_stmt = user_stmt.where(search_filter)

        # Apply visibility filter (None = show all, list = restrict)
        if visible_employee_ids is not None:
            user_stmt = user_stmt.where(User.id.in_(visible_employee_ids))

        user_stmt = user_stmt.order_by(User.first_name, User.last_name)

        result = await db.execute(user_stmt)
        users = result.scalars().unique().all()
        employee_ids = [u.id for u in users]

        # 2. Load shifts for those employees in the date range
        shifts_by_employee: Dict[int, list] = defaultdict(list)

        if employee_ids:
            shift_stmt = (
                select(Shift)
                .where(
                    Shift.tenant_id == tenant_id,
                    Shift.employee_id.in_(employee_ids),
                    Shift.date >= start_date,
                    Shift.date <= end_date,
                )
                .order_by(Shift.date, Shift.sequence_number)
            )
            if published_only:
                shift_stmt = shift_stmt.where(Shift.is_published == True)  # noqa: E712
            shift_result = await db.execute(shift_stmt)
            shifts = shift_result.scalars().all()

            for shift in shifts:
                shifts_by_employee[shift.employee_id].append(shift)

        # 3. Build the date list
        dates: List[str] = []
        current = start_date
        while current <= end_date:
            dates.append(current.isoformat())
            current += timedelta(days=1)

        # 4. Load date remarks
        remark_stmt = (
            select(DateRemark)
            .where(
                DateRemark.tenant_id == tenant_id,
                DateRemark.date >= start_date,
                DateRemark.date <= end_date,
            )
            .order_by(DateRemark.date)
        )
        remark_result = await db.execute(remark_stmt)
        date_remarks = remark_result.scalars().all()

        # 5. Load tenant status types for category-based stats
        status_stmt = select(ShiftStatusType).where(ShiftStatusType.tenant_id == tenant_id)
        status_result = await db.execute(status_stmt)
        status_types = status_result.scalars().all()
        category_map = {st.code: st.category for st in status_types}

        # Compute stats using category lookup (fallback: "leave" for unknown codes)
        all_shifts = [s for shifts_list in shifts_by_employee.values() for s in shifts_list]
        total_shifts = len(all_shifts)
        scheduled_count = sum(1 for s in all_shifts if category_map.get(s.status, "leave") == "work")
        leave_count = sum(1 for s in all_shifts if category_map.get(s.status, "leave") == "leave")
        rest_day_count = sum(1 for s in all_shifts if category_map.get(s.status, "leave") == "rest")

        stats = {
            "total_shifts": total_shifts,
            "total_employees": len(users),
            "scheduled_count": scheduled_count,
            "leave_count": leave_count,
            "rest_day_count": rest_day_count,
        }

        # 6. Assemble employee data
        employees = []
        for user in users:
            user_shifts = shifts_by_employee.get(user.id, [])
            shift_dicts = []
            for s in user_shifts:
                shift_dicts.append({
                    "id": s.id,
                    "employee_id": s.employee_id,
                    "employee_name": f"{user.first_name} {user.last_name}",
                    "date": s.date,
                    "start_time": s.start_time,
                    "end_time": s.end_time,
                    "sequence_number": s.sequence_number,
                    "status": s.status,
                    "work_arrangement": s.work_arrangement,
                    "role_id": s.role_id,
                    "role_name": s.role_name,
                    "color": s.color,
                    "notes": s.notes,
                    "remarks": s.remarks,
                    "is_published": s.is_published,
                })

            employees.append({
                "employee_id": user.id,
                "employee_name": f"{user.first_name} {user.last_name}",
                "section_name": user.section.name if user.section else None,
                "unit_name": user.unit.name if user.unit else None,
                "shifts": shift_dicts,
            })

        # 7. Serialize date remarks
        remark_dicts = []
        for r in date_remarks:
            remark_dicts.append({
                "id": r.id,
                "date": r.date,
                "title": r.title,
                "description": r.description,
                "is_holiday": r.is_holiday,
                "is_special": r.is_special,
                "is_recurring": r.is_recurring,
            })

        return {
            "employees": employees,
            "dates": dates,
            "date_remarks": remark_dicts,
            "stats": stats,
        }

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    async def _get_category_map(db: AsyncSession, tenant_id: UUID) -> Dict[str, str]:
        """Load status code → category mapping for tenant."""
        stmt = select(ShiftStatusType).where(ShiftStatusType.tenant_id == tenant_id)
        result = await db.execute(stmt)
        return {st.code: st.category for st in result.scalars().all()}

    # ── Shift CRUD ──────────────────────────────────────────────────────

    @staticmethod
    async def _next_sequence_number(
        db: AsyncSession,
        tenant_id: UUID,
        employee_id: int,
        shift_date: date,
    ) -> int:
        """Return max(sequence_number) + 1 for the given employee + date, defaulting to 1."""
        stmt = select(func.max(Shift.sequence_number)).where(
            Shift.tenant_id == tenant_id,
            Shift.employee_id == employee_id,
            Shift.date == shift_date,
        )
        result = await db.execute(stmt)
        max_seq = result.scalar()
        return (max_seq or 0) + 1

    @staticmethod
    async def _approved_leave_dates(
        db: AsyncSession,
        tenant_id: UUID,
        employee_id: int,
        start_date: date,
        end_date: date,
    ) -> set:
        """Return the set of dates in [start_date, end_date] on which the
        employee has an APPROVED leave application. Used to block scheduling
        someone onto a day they're already approved off."""
        stmt = select(
            LeaveApplication.start_date, LeaveApplication.end_date
        ).where(
            LeaveApplication.tenant_id == tenant_id,
            LeaveApplication.employee_id == employee_id,
            LeaveApplication.status == "approved",
            LeaveApplication.start_date <= end_date,
            LeaveApplication.end_date >= start_date,
        )
        result = await db.execute(stmt)
        blocked: set = set()
        for app_start, app_end in result.all():
            d = max(app_start, start_date)
            last = min(app_end, end_date)
            while d <= last:
                blocked.add(d)
                d += timedelta(days=1)
        return blocked

    @staticmethod
    async def check_scheduling_conflicts(
        db: AsyncSession,
        tenant_id: UUID,
        employee_id: int,
        target_dates: List[date],
        status: str,
        *,
        force: bool = False,
    ) -> List[dict]:
        """Evaluate scheduling guardrails for a set of work dates.

        Returns a list of conflict dicts. Leave-overlap conflicts are ALWAYS
        returned (cannot be forced). Guardrail conflicts (consecutive-days /
        rest-days) are suppressed when ``force=True``.

        Only "work"-category statuses are checked — assigning a rest_day or a
        leave status never conflicts.
        """
        if not target_dates:
            return []

        category_map = await ScheduleService._get_category_map(db, tenant_id)
        if category_map.get(status, "leave") != "work":
            return []

        conflicts: List[dict] = []
        target_set = set(target_dates)
        span_start = min(target_dates)
        span_end = max(target_dates)

        # 1. Approved-leave overlap (never forceable).
        leave_dates = await ScheduleService._approved_leave_dates(
            db, tenant_id, employee_id, span_start, span_end
        )
        for d in sorted(target_set & leave_dates):
            conflicts.append({
                "employee_id": employee_id,
                "date": d.isoformat(),
                "type": "approved_leave",
                "forceable": False,
                "message": f"Employee is on approved leave on {d.isoformat()}.",
            })

        # 2. Tenant guardrails (consecutive-days / rest-days).
        settings_result = await db.execute(
            select(AppSettings).where(AppSettings.tenant_id == tenant_id)
        )
        settings = settings_result.scalar_one_or_none()
        max_consec = getattr(settings, "max_consecutive_work_days", 0) or 0
        min_rest = getattr(settings, "min_rest_days_per_week", 0) or 0

        if max_consec or min_rest:
            # Build the employee's projected work-day set: existing work shifts
            # plus the new target dates, over a window padded to catch runs that
            # straddle the edges.
            window_start = span_start - timedelta(days=7)
            window_end = span_end + timedelta(days=7)
            existing = await db.execute(
                select(Shift.date, Shift.status).where(
                    Shift.tenant_id == tenant_id,
                    Shift.employee_id == employee_id,
                    Shift.date >= window_start,
                    Shift.date <= window_end,
                )
            )
            work_days: set = set(target_set)
            for d, st in existing.all():
                if category_map.get(st, "leave") == "work":
                    work_days.add(d)

            if max_consec:
                for d in sorted(target_set):
                    # Count the consecutive work-day run containing d.
                    run = 1
                    p = d - timedelta(days=1)
                    while p in work_days:
                        run += 1
                        p -= timedelta(days=1)
                    n = d + timedelta(days=1)
                    while n in work_days:
                        run += 1
                        n += timedelta(days=1)
                    if run > max_consec:
                        conflicts.append({
                            "employee_id": employee_id,
                            "date": d.isoformat(),
                            "type": "max_consecutive_work_days",
                            "forceable": True,
                            "message": (
                                f"Scheduling {d.isoformat()} makes a run of {run} "
                                f"consecutive work days (limit {max_consec})."
                            ),
                        })
                        break  # one guardrail hit per run is enough

            if min_rest:
                max_work_per_week = 7 - min_rest
                for d in sorted(target_set):
                    # Rolling 7-day window centred so d is included; check the
                    # window starting at d for simplicity/determinism.
                    work_in_window = sum(
                        1 for i in range(7) if (d + timedelta(days=i)) in work_days
                    )
                    if work_in_window > max_work_per_week:
                        conflicts.append({
                            "employee_id": employee_id,
                            "date": d.isoformat(),
                            "type": "min_rest_days_per_week",
                            "forceable": True,
                            "message": (
                                f"The 7 days from {d.isoformat()} contain "
                                f"{work_in_window} work days, leaving fewer than "
                                f"{min_rest} rest day(s)."
                            ),
                        })
                        break

        if force:
            conflicts = [c for c in conflicts if not c["forceable"]]
        return conflicts

    @staticmethod
    async def create_shift(
        db: AsyncSession,
        tenant_id: UUID,
        data: dict,
        created_by: Optional[int] = None,
        *,
        force: bool = False,
    ) -> Shift:
        """Create a new shift. Auto-calculates sequence_number.

        Raises ScheduleConflictError if the shift lands on approved leave or
        breaches a tenant guardrail (unless force=True for guardrails).
        """
        status = data.get("status", "scheduled")

        conflicts = await ScheduleService.check_scheduling_conflicts(
            db, tenant_id, data["employee_id"], [data["date"]], status, force=force
        )
        if conflicts:
            raise ScheduleConflictError(conflicts)

        sequence_number = await ScheduleService._next_sequence_number(
            db, tenant_id, data["employee_id"], data["date"]
        )

        # If status is not a "work" category, clear time fields
        start_time = data.get("start_time")
        end_time = data.get("end_time")
        category_map = await ScheduleService._get_category_map(db, tenant_id)
        if category_map.get(status, "leave") != "work":
            start_time = None
            end_time = None

        shift = Shift(
            tenant_id=tenant_id,
            employee_id=data["employee_id"],
            date=data["date"],
            start_time=start_time,
            end_time=end_time,
            sequence_number=sequence_number,
            status=status,
            work_arrangement=data.get("work_arrangement"),
            role_name=data.get("role_name"),
            color=data.get("color"),
            notes=data.get("notes"),
            remarks=data.get("remarks"),
            created_by=created_by,
        )
        db.add(shift)
        await db.flush()
        await db.refresh(shift)
        return shift

    @staticmethod
    async def bulk_create_shifts(
        db: AsyncSession,
        tenant_id: UUID,
        data: dict,
        created_by: Optional[int] = None,
        *,
        force: bool = False,
    ) -> tuple:
        """
        Create shifts for multiple employees across a date range.
        Optionally skip weekends and/or holidays.

        Returns ``(created_shifts, skipped_conflicts)``. Dates that would land
        on approved leave (or breach a guardrail when force=False) are skipped
        rather than failing the whole batch, and reported back to the caller.
        """
        employee_ids: List[int] = data["employee_ids"]
        start_date: date = data["start_date"]
        end_date: date = data["end_date"]
        skip_weekends: bool = data.get("skip_weekends", False)
        skip_holidays: bool = data.get("skip_holidays", False)
        skip_days_names: List[str] = data.get("skip_days", [])

        # Map day names to Python weekday numbers (Monday=0 .. Sunday=6)
        DAY_NAME_TO_NUM = {
            "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
            "friday": 4, "saturday": 5, "sunday": 6,
        }
        skip_day_nums: set = {DAY_NAME_TO_NUM[d.lower()] for d in skip_days_names if d.lower() in DAY_NAME_TO_NUM}

        # Load holiday dates if needed
        holiday_dates: set = set()
        if skip_holidays:
            from app.models.schedule import DateRemark
            stmt = select(DateRemark.date).where(
                DateRemark.tenant_id == tenant_id,
                DateRemark.date >= start_date,
                DateRemark.date <= end_date,
                DateRemark.is_holiday == True,
            )
            result = await db.execute(stmt)
            holiday_dates = {row[0] for row in result.all()}

        # Determine category for time clearing
        status = data.get("status", "scheduled")
        category_map = await ScheduleService._get_category_map(db, tenant_id)
        is_work = category_map.get(status, "leave") == "work"

        start_time = data.get("start_time") if is_work else None
        end_time = data.get("end_time") if is_work else None

        # Build the list of eligible dates after applying skip filters.
        eligible_dates: List[date] = []
        current = start_date
        while current <= end_date:
            if skip_weekends and current.weekday() >= 5:
                current += timedelta(days=1)
                continue
            if current.weekday() in skip_day_nums:
                current += timedelta(days=1)
                continue
            if skip_holidays and current in holiday_dates:
                current += timedelta(days=1)
                continue
            eligible_dates.append(current)
            current += timedelta(days=1)

        created_shifts: List[Shift] = []
        skipped_conflicts: List[dict] = []

        for employee_id in employee_ids:
            # Determine which eligible dates conflict for this employee.
            conflicts = await ScheduleService.check_scheduling_conflicts(
                db, tenant_id, employee_id, eligible_dates, status, force=force
            )
            blocked_dates = {c["date"] for c in conflicts}
            skipped_conflicts.extend(conflicts)

            for d in eligible_dates:
                if d.isoformat() in blocked_dates:
                    continue
                seq = await ScheduleService._next_sequence_number(
                    db, tenant_id, employee_id, d
                )
                shift = Shift(
                    tenant_id=tenant_id,
                    employee_id=employee_id,
                    date=d,
                    start_time=start_time,
                    end_time=end_time,
                    sequence_number=seq,
                    status=status,
                    work_arrangement=data.get("work_arrangement"),
                    role_name=data.get("role_name"),
                    color=data.get("color"),
                    notes=data.get("notes"),
                    remarks=data.get("remarks"),
                    created_by=created_by,
                )
                db.add(shift)
                created_shifts.append(shift)

        await db.flush()
        for shift in created_shifts:
            await db.refresh(shift)

        return created_shifts, skipped_conflicts

    @staticmethod
    async def update_shift(
        db: AsyncSession,
        shift_id: int,
        tenant_id: UUID,
        data: dict,
    ) -> Optional[Shift]:
        """Update shift fields using PATCH semantics (only provided keys)."""
        stmt = select(Shift).where(Shift.id == shift_id, Shift.tenant_id == tenant_id)
        result = await db.execute(stmt)
        shift = result.scalar_one_or_none()

        if not shift:
            return None

        # If employee_id or date will change, pre-compute the new sequence_number
        # BEFORE applying changes (to avoid autoflush unique constraint violation)
        new_sequence_number = None
        if "employee_id" in data or "date" in data:
            target_emp = data.get("employee_id", shift.employee_id)
            target_date = data.get("date", shift.date)
            if target_emp != shift.employee_id or target_date != shift.date:
                seq_stmt = select(func.max(Shift.sequence_number)).where(
                    Shift.tenant_id == tenant_id,
                    Shift.employee_id == target_emp,
                    Shift.date == target_date,
                )
                seq_result = await db.execute(seq_stmt)
                max_seq = seq_result.scalar()
                new_sequence_number = (max_seq or 0) + 1

        for key, value in data.items():
            if value is not None and hasattr(shift, key):
                setattr(shift, key, value)

        if new_sequence_number is not None:
            shift.sequence_number = new_sequence_number

        # If status was changed to a non-"work" category, clear times
        if "status" in data and data["status"] is not None:
            category_map = await ScheduleService._get_category_map(db, tenant_id)
            if category_map.get(data["status"], "leave") != "work":
                shift.start_time = None
                shift.end_time = None

        await db.flush()
        await db.refresh(shift)
        return shift

    @staticmethod
    async def delete_shift(
        db: AsyncSession,
        shift_id: int,
        tenant_id: UUID,
    ) -> bool:
        """Delete a shift by id and tenant_id. Returns True if deleted."""
        stmt = select(Shift).where(Shift.id == shift_id, Shift.tenant_id == tenant_id)
        result = await db.execute(stmt)
        shift = result.scalar_one_or_none()

        if not shift:
            return False

        await db.delete(shift)
        await db.flush()
        return True

    # ── Copy Shifts ─────────────────────────────────────────────────────

    @staticmethod
    async def copy_shifts(
        db: AsyncSession,
        tenant_id: UUID,
        source_employee_id: int,
        source_start_date: date,
        source_end_date: date,
        target_employee_ids: List[int],
        target_start_date: date,
        created_by: Optional[int] = None,
    ) -> List[Shift]:
        """
        Copy shifts from a source employee in a date range to one or more
        target employees, offsetting dates so that source_start_date maps
        to target_start_date.
        """
        day_offset = (target_start_date - source_start_date).days

        # Load source shifts
        stmt = (
            select(Shift)
            .where(
                Shift.tenant_id == tenant_id,
                Shift.employee_id == source_employee_id,
                Shift.date >= source_start_date,
                Shift.date <= source_end_date,
            )
            .order_by(Shift.date, Shift.sequence_number)
        )
        result = await db.execute(stmt)
        source_shifts = result.scalars().all()

        created_shifts: List[Shift] = []

        for target_employee_id in target_employee_ids:
            for src in source_shifts:
                new_date = src.date + timedelta(days=day_offset)
                seq = await ScheduleService._next_sequence_number(
                    db, tenant_id, target_employee_id, new_date
                )
                new_shift = Shift(
                    tenant_id=tenant_id,
                    employee_id=target_employee_id,
                    date=new_date,
                    start_time=src.start_time,
                    end_time=src.end_time,
                    sequence_number=seq,
                    status=src.status,
                    work_arrangement=src.work_arrangement,
                    role_id=src.role_id,
                    role_name=src.role_name,
                    color=src.color,
                    notes=src.notes,
                    remarks=src.remarks,
                    created_by=created_by,
                )
                db.add(new_shift)
                created_shifts.append(new_shift)

        await db.flush()
        for shift in created_shifts:
            await db.refresh(shift)

        return created_shifts

    # ── Date Remarks ────────────────────────────────────────────────────

    @staticmethod
    async def get_date_remarks(
        db: AsyncSession,
        tenant_id: UUID,
        start_date: date,
        end_date: date,
    ) -> List[DateRemark]:
        """Get date remarks for a date range and tenant."""
        stmt = (
            select(DateRemark)
            .where(
                DateRemark.tenant_id == tenant_id,
                DateRemark.date >= start_date,
                DateRemark.date <= end_date,
            )
            .order_by(DateRemark.date)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def create_date_remark(
        db: AsyncSession,
        tenant_id: UUID,
        data: dict,
    ) -> DateRemark:
        """Create a new date remark."""
        remark = DateRemark(
            tenant_id=tenant_id,
            date=data["date"],
            title=data["title"],
            description=data.get("description"),
            is_holiday=data.get("is_holiday", False),
            is_special=data.get("is_special", False),
            is_recurring=data.get("is_recurring", False),
        )
        db.add(remark)
        await db.flush()
        await db.refresh(remark)
        return remark

    @staticmethod
    async def update_date_remark(
        db: AsyncSession,
        tenant_id: UUID,
        remark_id: int,
        data: dict,
    ) -> Optional[DateRemark]:
        """Update an existing date remark."""
        stmt = select(DateRemark).where(
            DateRemark.id == remark_id,
            DateRemark.tenant_id == tenant_id,
        )
        result = await db.execute(stmt)
        remark = result.scalar_one_or_none()
        if not remark:
            return None
        for key, value in data.items():
            if value is not None and hasattr(remark, key):
                setattr(remark, key, value)
        await db.flush()
        await db.refresh(remark)
        return remark

    @staticmethod
    async def delete_date_remark(
        db: AsyncSession,
        tenant_id: UUID,
        remark_id: int,
    ) -> bool:
        """Delete a date remark."""
        stmt = select(DateRemark).where(
            DateRemark.id == remark_id,
            DateRemark.tenant_id == tenant_id,
        )
        result = await db.execute(stmt)
        remark = result.scalar_one_or_none()
        if not remark:
            return False
        await db.delete(remark)
        await db.flush()
        return True

    @staticmethod
    async def get_holidays(
        db: AsyncSession,
        tenant_id: UUID,
        year: Optional[int] = None,
    ) -> List[DateRemark]:
        """Get all holidays for a tenant, optionally filtered by year."""
        stmt = (
            select(DateRemark)
            .where(
                DateRemark.tenant_id == tenant_id,
                DateRemark.is_holiday == True,
            )
        )
        if year:
            stmt = stmt.where(extract('year', DateRemark.date) == year)
        stmt = stmt.order_by(DateRemark.date)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    # ── Schedule Templates ──────────────────────────────────────────────

    @staticmethod
    async def get_templates(
        db: AsyncSession,
        tenant_id: UUID,
    ) -> List[ScheduleTemplate]:
        """List active schedule templates for a tenant."""
        stmt = (
            select(ScheduleTemplate)
            .where(
                ScheduleTemplate.tenant_id == tenant_id,
                ScheduleTemplate.is_active == True,
            )
            .order_by(ScheduleTemplate.name)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def create_template(
        db: AsyncSession,
        tenant_id: UUID,
        data: dict,
        created_by: Optional[int] = None,
    ) -> ScheduleTemplate:
        """Create a new schedule template."""
        template = ScheduleTemplate(
            tenant_id=tenant_id,
            name=data["name"],
            description=data.get("description"),
            template_data=data["template_data"],
            created_by=created_by,
        )
        db.add(template)
        await db.flush()
        await db.refresh(template)
        return template

    @staticmethod
    async def apply_template(
        db: AsyncSession,
        tenant_id: UUID,
        template_id: int,
        employee_ids: List[int],
        start_date: date,
        created_by: Optional[int] = None,
    ) -> List[Shift]:
        """
        Apply a schedule template to a list of employees starting from a
        given date.  The template_data is expected to be a list of day
        entries (index 0 = day 0, etc.), each containing shift details.
        """
        stmt = select(ScheduleTemplate).where(
            ScheduleTemplate.id == template_id,
            ScheduleTemplate.tenant_id == tenant_id,
            ScheduleTemplate.is_active == True,
        )
        result = await db.execute(stmt)
        template = result.scalar_one_or_none()

        if not template:
            return []

        template_data = template.template_data
        # template_data should be a list of day entries, e.g.:
        # [
        #   {"start_time": "08:00", "end_time": "16:00", "status": "scheduled", ...},
        #   {"status": "rest_day"},
        #   ...
        # ]
        if not isinstance(template_data, list):
            return []

        category_map = await ScheduleService._get_category_map(db, tenant_id)
        created_shifts: List[Shift] = []

        for employee_id in employee_ids:
            for day_index, day_entry in enumerate(template_data):
                if not day_entry:
                    continue

                shift_date = start_date + timedelta(days=day_index)
                status = day_entry.get("status", "scheduled")

                # template_data is JSON, so times arrive as "HH:MM" strings —
                # coerce to time objects (the Time column rejects raw strings).
                from datetime import time as _time

                def _coerce(v):
                    if v is None or isinstance(v, _time):
                        return v
                    try:
                        return _time.fromisoformat(str(v))
                    except ValueError:
                        return None

                start_time = _coerce(day_entry.get("start_time"))
                end_time = _coerce(day_entry.get("end_time"))

                # Clear times for non-"work" category statuses
                if category_map.get(status, "leave") != "work":
                    start_time = None
                    end_time = None

                seq = await ScheduleService._next_sequence_number(
                    db, tenant_id, employee_id, shift_date
                )

                shift = Shift(
                    tenant_id=tenant_id,
                    employee_id=employee_id,
                    date=shift_date,
                    start_time=start_time,
                    end_time=end_time,
                    sequence_number=seq,
                    status=status,
                    work_arrangement=day_entry.get("work_arrangement"),
                    role_name=day_entry.get("role_name"),
                    color=day_entry.get("color"),
                    notes=day_entry.get("notes"),
                    remarks=day_entry.get("remarks"),
                    created_by=created_by,
                )
                db.add(shift)
                created_shifts.append(shift)

        await db.flush()
        for shift in created_shifts:
            await db.refresh(shift)

        return created_shifts

    # ── Leave → Schedule Overlay ───────────────────────────────────────

    @staticmethod
    async def overlay_leave_on_shifts(
        db: AsyncSession,
        tenant_id: UUID,
        employee_id: int,
        leave_application_id: int,
        leave_type: str,
        start_date: date,
        end_date: date,
    ) -> List[date]:
        """
        When a leave is approved, overlay leave status onto existing shifts
        for the employee in the leave date range.  If no shift exists for a
        date, create one with the leave status.  Original shift data is
        preserved in original_status / original_start_time / original_end_time.

        Every calendar day in the leave range is overlaid — including weekends.
        A shift-based workforce (night/weekend workers) can legitimately be
        scheduled on Saturdays/Sundays, so skipping them here would leave those
        shifts showing "working" while the employee is on approved leave.

        Overlapping approved leaves: a shift already stamped with a *different*
        leave_application_id is left untouched so the first-approved leave keeps
        the day; the caller can detect this via the returned conflict list.
        """
        conflicts: List[date] = []
        current = start_date
        while current <= end_date:
            # Find existing shift(s) for this employee + date
            stmt = (
                select(Shift)
                .where(
                    Shift.tenant_id == tenant_id,
                    Shift.employee_id == employee_id,
                    Shift.date == current,
                )
                .order_by(Shift.sequence_number)
            )
            result = await db.execute(stmt)
            shifts = list(result.scalars().all())

            if shifts:
                for shift in shifts:
                    # A shift already claimed by a *different* approved leave is
                    # left as-is (first leave wins); flag the date as a conflict.
                    if (
                        shift.leave_application_id is not None
                        and shift.leave_application_id != leave_application_id
                    ):
                        conflicts.append(current)
                        continue
                    # Only snapshot original data if not already overlaid.
                    if shift.leave_application_id is None:
                        shift.original_status = shift.status
                        shift.original_start_time = shift.start_time
                        shift.original_end_time = shift.end_time
                    shift.status = leave_type
                    shift.start_time = None
                    shift.end_time = None
                    shift.leave_application_id = leave_application_id
            else:
                # Create a new shift record with the leave status
                seq = await ScheduleService._next_sequence_number(
                    db, tenant_id, employee_id, current
                )
                new_shift = Shift(
                    tenant_id=tenant_id,
                    employee_id=employee_id,
                    date=current,
                    start_time=None,
                    end_time=None,
                    sequence_number=seq,
                    status=leave_type,
                    leave_application_id=leave_application_id,
                )
                db.add(new_shift)

            current += timedelta(days=1)

        await db.flush()
        return conflicts

    # ── CSV Export ──────────────────────────────────────────────────────

    @staticmethod
    async def export_shifts_csv(
        db: AsyncSession,
        tenant_id: UUID,
        start_date: date,
        end_date: date,
    ) -> str:
        """
        Export all shifts for a tenant in a date range as a CSV string.
        Columns: Employee, Date, Start Time, End Time, Status,
        Work Arrangement, Notes.
        """
        stmt = (
            select(Shift)
            .where(
                Shift.tenant_id == tenant_id,
                Shift.date >= start_date,
                Shift.date <= end_date,
            )
            .order_by(Shift.date, Shift.employee_id, Shift.sequence_number)
        )
        result = await db.execute(stmt)
        shifts = result.scalars().all()

        # Collect unique employee ids to resolve names
        employee_ids = list({s.employee_id for s in shifts})
        employee_names: Dict[int, str] = {}

        if employee_ids:
            user_stmt = select(User).where(
                User.id.in_(employee_ids),
                User.tenant_id == tenant_id,
            )
            user_result = await db.execute(user_stmt)
            users = user_result.scalars().all()
            for u in users:
                employee_names[u.id] = f"{u.first_name} {u.last_name}"

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Employee",
            "Date",
            "Start Time",
            "End Time",
            "Status",
            "Work Arrangement",
            "Notes",
        ])

        for shift in shifts:
            writer.writerow([
                employee_names.get(shift.employee_id, str(shift.employee_id)),
                shift.date.isoformat(),
                shift.start_time.strftime("%H:%M") if shift.start_time else "",
                shift.end_time.strftime("%H:%M") if shift.end_time else "",
                shift.status,
                shift.work_arrangement or "",
                shift.notes or "",
            ])

        return output.getvalue()

    # ── Bulk Delete ────────────────────────────────────────────────────

    @staticmethod
    async def bulk_delete_shifts(
        db: AsyncSession,
        tenant_id: UUID,
        start_date: date,
        end_date: date,
        employee_ids: Optional[List[int]] = None,
    ) -> int:
        """Delete all shifts in a date range, optionally filtered by employee IDs.
        Returns count of deleted shifts."""
        conditions = [
            Shift.tenant_id == tenant_id,
            Shift.date >= start_date,
            Shift.date <= end_date,
        ]
        if employee_ids:
            conditions.append(Shift.employee_id.in_(employee_ids))

        # Count first
        count_stmt = select(func.count(Shift.id)).where(*conditions)
        count_result = await db.execute(count_stmt)
        total = count_result.scalar() or 0

        if total > 0:
            del_stmt = delete(Shift).where(*conditions)
            await db.execute(del_stmt)
            await db.flush()

        return total

    # ── Schedule Snapshots ─────────────────────────────────────────────

    @staticmethod
    async def create_snapshot(
        db: AsyncSession,
        tenant_id: UUID,
        name: str,
        description: Optional[str],
        start_date: date,
        end_date: date,
        range_type: str,
        created_by: Optional[int] = None,
    ) -> ScheduleSnapshot:
        """Capture all shifts in a date range as a reusable snapshot."""
        # Load all shifts in the range
        shift_stmt = (
            select(Shift)
            .where(
                Shift.tenant_id == tenant_id,
                Shift.date >= start_date,
                Shift.date <= end_date,
            )
            .order_by(Shift.employee_id, Shift.date, Shift.sequence_number)
        )
        result = await db.execute(shift_stmt)
        shifts = result.scalars().all()

        # Load employee names
        emp_ids = list({s.employee_id for s in shifts})
        emp_names: Dict[int, str] = {}
        if emp_ids:
            user_stmt = select(User).where(User.id.in_(emp_ids), User.tenant_id == tenant_id)
            user_result = await db.execute(user_stmt)
            for u in user_result.scalars().all():
                emp_names[u.id] = f"{u.first_name} {u.last_name}"

        # Group shifts by employee and convert to offset-based format
        from collections import defaultdict as dd
        shifts_by_emp: Dict[int, list] = dd(list)
        for s in shifts:
            shifts_by_emp[s.employee_id].append(s)

        snapshot_employees = []
        for emp_id in emp_ids:
            emp_shifts = shifts_by_emp.get(emp_id, [])
            shift_entries = []
            for s in emp_shifts:
                day_offset = (s.date - start_date).days
                shift_entries.append({
                    "day_offset": day_offset,
                    "status": s.status,
                    "start_time": s.start_time.strftime("%H:%M") if s.start_time else None,
                    "end_time": s.end_time.strftime("%H:%M") if s.end_time else None,
                    "work_arrangement": s.work_arrangement,
                    "role_name": s.role_name,
                    "color": s.color,
                    "notes": s.notes,
                    "remarks": s.remarks,
                })
            snapshot_employees.append({
                "employee_id": emp_id,
                "employee_name": emp_names.get(emp_id, str(emp_id)),
                "shifts": shift_entries,
            })

        snapshot = ScheduleSnapshot(
            tenant_id=tenant_id,
            name=name,
            description=description,
            source_start_date=start_date,
            source_end_date=end_date,
            range_type=range_type,
            snapshot_data=snapshot_employees,
            employee_count=len(emp_ids),
            shift_count=len(shifts),
            created_by=created_by,
        )
        db.add(snapshot)
        await db.flush()
        await db.refresh(snapshot)
        return snapshot

    @staticmethod
    async def get_snapshots(
        db: AsyncSession,
        tenant_id: UUID,
    ) -> List[ScheduleSnapshot]:
        """List active schedule snapshots for a tenant."""
        stmt = (
            select(ScheduleSnapshot)
            .where(
                ScheduleSnapshot.tenant_id == tenant_id,
                ScheduleSnapshot.is_active == True,
            )
            .order_by(ScheduleSnapshot.created_at.desc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    def _snapshot_span_days(snapshot: "ScheduleSnapshot") -> int:
        """Length of the captured window in days (the stride between repeats).

        A 7-day (week) snapshot strides every 7 days so copies are back-to-back;
        a 30/31-day month snapshot strides by its own length. Always >= 1."""
        span = (snapshot.source_end_date - snapshot.source_start_date).days + 1
        return max(span, 1)

    @staticmethod
    def _snapshot_targets(
        snapshot: "ScheduleSnapshot",
        target_start_date: date,
        repeat_until: Optional[date],
        employee_ids: Optional[List[int]],
    ) -> tuple:
        """Expand a snapshot into concrete (employee_id, shift_date, shift_entry)
        targets across one or more contiguous occurrences.

        Returns (occurrences, targets) where occurrences is a list of
        {index, start_date, end_date} describing each repeated copy, and targets
        is the flat list of (employee_id, shift_date, shift_entry). When
        repeat_until is None or before target_start_date, exactly one occurrence
        is produced (single apply — back-compat)."""
        data = snapshot.snapshot_data
        if not isinstance(data, list):
            return [], []

        stride = ScheduleService._snapshot_span_days(snapshot)

        occ_starts: List[date] = [target_start_date]
        if repeat_until and repeat_until >= target_start_date:
            k = 1
            while True:
                start = target_start_date + timedelta(days=k * stride)
                if start > repeat_until:
                    break
                occ_starts.append(start)
                k += 1

        occurrences: List[dict] = []
        targets: list = []
        for idx, occ_start in enumerate(occ_starts):
            occurrences.append({
                "index": idx,
                "start_date": occ_start,
                "end_date": occ_start + timedelta(days=stride - 1),
            })
            for emp_entry in data:
                emp_id = emp_entry.get("employee_id")
                if not emp_id:
                    continue
                if employee_ids and emp_id not in employee_ids:
                    continue
                for shift_entry in emp_entry.get("shifts", []):
                    day_offset = shift_entry.get("day_offset", 0)
                    shift_date = occ_start + timedelta(days=day_offset)
                    targets.append((emp_id, shift_date, shift_entry))
        return occurrences, targets

    @staticmethod
    async def _load_snapshot(
        db: AsyncSession, tenant_id: UUID, snapshot_id: int
    ):
        result = await db.execute(
            select(ScheduleSnapshot).where(
                ScheduleSnapshot.id == snapshot_id,
                ScheduleSnapshot.tenant_id == tenant_id,
                ScheduleSnapshot.is_active == True,  # noqa: E712
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def _existing_shift_dates(
        db: AsyncSession, tenant_id: UUID, employee_id: int, dates: List[date]
    ) -> set:
        """Subset of `dates` on which the employee already has a shift."""
        if not dates:
            return set()
        result = await db.execute(
            select(Shift.date).where(
                Shift.tenant_id == tenant_id,
                Shift.employee_id == employee_id,
                Shift.date.in_(dates),
            )
        )
        return {row[0] for row in result.all()}

    @staticmethod
    async def preview_snapshot_apply(
        db: AsyncSession,
        tenant_id: UUID,
        snapshot_id: int,
        target_start_date: date,
        repeat_until: Optional[date],
        employee_ids: Optional[List[int]],
    ) -> Optional[dict]:
        """Dry-run: compute occurrences + conflicts WITHOUT writing anything.

        Conflicts split into:
          - blocking: approved-leave overlaps — always skipped, never overwritable.
          - resolvable: an existing shift on the date, or a tenant guardrail breach
            (consecutive-days / rest-days) — the user chooses skip vs overwrite.
        """
        snapshot = await ScheduleService._load_snapshot(db, tenant_id, snapshot_id)
        if not snapshot:
            return None

        occurrences, targets = ScheduleService._snapshot_targets(
            snapshot, target_start_date, repeat_until, employee_ids
        )

        by_emp_status: Dict[int, list] = defaultdict(list)
        by_emp_dates: Dict[int, List[date]] = defaultdict(list)
        for emp_id, shift_date, entry in targets:
            by_emp_status[emp_id].append((shift_date, entry.get("status", "scheduled")))
            by_emp_dates[emp_id].append(shift_date)

        emp_ids = list(by_emp_status.keys())
        names: Dict[int, str] = {}
        if emp_ids:
            rows = await db.execute(
                select(User.id, User.first_name, User.last_name).where(User.id.in_(emp_ids))
            )
            for uid, fn, ln in rows.all():
                names[uid] = f"{fn} {ln}"

        blocking: List[dict] = []
        resolvable: List[dict] = []
        for emp_id in emp_ids:
            existing = await ScheduleService._existing_shift_dates(
                db, tenant_id, emp_id, by_emp_dates[emp_id]
            )
            # Batch the guardrail/leave check: one call per (employee, status) with
            # ALL that employee's dates for the status, instead of one call per
            # date. check_scheduling_conflicts accepts a target-date list, so this
            # turns O(shifts) round-trips into O(employees) — the difference
            # between a ~7s and a sub-second preview for a full-team repeat.
            dates_by_status: Dict[str, List[date]] = defaultdict(list)
            for shift_date, status in by_emp_status[emp_id]:
                dates_by_status[status].append(shift_date)

            leave_dates: set = set()
            for status, dts in dates_by_status.items():
                conflicts = await ScheduleService.check_scheduling_conflicts(
                    db, tenant_id, emp_id, dts, status, force=False
                )
                for c in conflicts:
                    row = {
                        "employee_id": emp_id,
                        "employee_name": names.get(emp_id, str(emp_id)),
                        "date": c["date"],
                        "type": c["type"],
                        "forceable": c["forceable"],
                        "message": c["message"],
                        "has_existing_shift": c["date"] in {d.isoformat() for d in existing},
                    }
                    if c["type"] == "approved_leave":
                        leave_dates.add(c["date"])
                        blocking.append(row)
                    else:
                        resolvable.append(row)

            # Existing-shift clashes on dates not already blocked by leave.
            for shift_date in by_emp_dates[emp_id]:
                if shift_date in existing and shift_date.isoformat() not in leave_dates:
                    resolvable.append({
                        "employee_id": emp_id,
                        "employee_name": names.get(emp_id, str(emp_id)),
                        "date": shift_date.isoformat(),
                        "type": "existing_shift",
                        "forceable": True,
                        "message": f"A shift already exists on {shift_date.isoformat()}.",
                        "has_existing_shift": True,
                    })

        blocking_keys = {(c["employee_id"], c["date"]) for c in blocking}
        create_count = sum(
            1 for emp_id, d, _ in targets
            if (emp_id, d.isoformat()) not in blocking_keys
        )
        return {
            "occurrences": occurrences,
            "stride_days": ScheduleService._snapshot_span_days(snapshot),
            "total_shifts": len(targets),
            "create_count": create_count,
            "blocking_conflicts": blocking,
            "resolvable_conflicts": resolvable,
        }

    @staticmethod
    async def apply_snapshot(
        db: AsyncSession,
        tenant_id: UUID,
        snapshot_id: int,
        target_start_date: date,
        employee_ids: Optional[List[int]],
        created_by: Optional[int] = None,
        *,
        repeat_until: Optional[date] = None,
        on_conflict: str = "skip",
    ) -> dict:
        """Apply a snapshot to one target date, optionally repeating it forward
        (contiguously) until ``repeat_until``.

        Conflict handling per ``on_conflict``:
          - Approved-leave dates are ALWAYS skipped (never scheduled over).
          - 'skip': dates with an existing shift or a guardrail breach are skipped.
          - 'overwrite': existing shifts on those dates are deleted and replaced;
            forceable guardrail breaches are forced through.

        Returns ``{created, skipped, overwritten}``."""
        snapshot = await ScheduleService._load_snapshot(db, tenant_id, snapshot_id)
        if not snapshot:
            return {"created": 0, "skipped": [], "overwritten": 0}

        occurrences, targets = ScheduleService._snapshot_targets(
            snapshot, target_start_date, repeat_until, employee_ids
        )
        category_map = await ScheduleService._get_category_map(db, tenant_id)

        from datetime import time as _time
        created = 0
        overwritten = 0
        skipped: List[dict] = []
        force = on_conflict == "overwrite"

        for emp_id, shift_date, shift_entry in targets:
            status = shift_entry.get("status", "scheduled")

            # 1. Leave/guardrail evaluation (force only when overwriting).
            conflicts = await ScheduleService.check_scheduling_conflicts(
                db, tenant_id, emp_id, [shift_date], status, force=force
            )
            if conflicts:
                # Remaining conflicts are non-forceable (approved leave) or a
                # guardrail we chose not to force (skip mode) — skip this date.
                skipped.append({
                    "employee_id": emp_id,
                    "date": shift_date.isoformat(),
                    "reason": conflicts[0]["type"],
                    "message": conflicts[0]["message"],
                })
                continue

            # 2. Existing shift(s) on the date.
            existing = (await db.execute(
                select(Shift).where(
                    Shift.tenant_id == tenant_id,
                    Shift.employee_id == emp_id,
                    Shift.date == shift_date,
                )
            )).scalars().all()
            if existing:
                if not force:
                    skipped.append({
                        "employee_id": emp_id,
                        "date": shift_date.isoformat(),
                        "reason": "existing_shift",
                        "message": f"A shift already exists on {shift_date.isoformat()}.",
                    })
                    continue
                for old in existing:
                    await db.delete(old)
                await db.flush()
                overwritten += 1

            # 3. Create the shift.
            start_time_str = shift_entry.get("start_time")
            end_time_str = shift_entry.get("end_time")
            start_time = _time.fromisoformat(start_time_str) if start_time_str else None
            end_time = _time.fromisoformat(end_time_str) if end_time_str else None
            if category_map.get(status, "leave") != "work":
                start_time = None
                end_time = None

            seq = await ScheduleService._next_sequence_number(
                db, tenant_id, emp_id, shift_date,
            )
            db.add(Shift(
                tenant_id=tenant_id,
                employee_id=emp_id,
                date=shift_date,
                start_time=start_time,
                end_time=end_time,
                sequence_number=seq,
                status=status,
                work_arrangement=shift_entry.get("work_arrangement"),
                role_name=shift_entry.get("role_name"),
                color=shift_entry.get("color"),
                notes=shift_entry.get("notes"),
                remarks=shift_entry.get("remarks"),
                created_by=created_by,
            ))
            await db.flush()
            created += 1

        return {"created": created, "skipped": skipped, "overwritten": overwritten}

    @staticmethod
    async def delete_snapshot(
        db: AsyncSession,
        snapshot_id: int,
        tenant_id: UUID,
    ) -> bool:
        """Soft-delete (deactivate) a snapshot."""
        stmt = select(ScheduleSnapshot).where(
            ScheduleSnapshot.id == snapshot_id,
            ScheduleSnapshot.tenant_id == tenant_id,
        )
        result = await db.execute(stmt)
        snapshot = result.scalar_one_or_none()
        if not snapshot:
            return False
        snapshot.is_active = False
        await db.flush()
        return True

    # ── Copy a week (or any range) forward ───────────────────────────────
    @staticmethod
    async def _week_copy_targets(
        db: AsyncSession,
        tenant_id: UUID,
        source_start: date,
        source_end: date,
        target_start: date,
        employee_ids: Optional[List[int]],
    ) -> tuple:
        """Read the live shifts in [source_start, source_end] and project them to
        a target window starting at target_start (same day-offset). Returns
        (occurrences, targets) with the same shape as _snapshot_targets so the
        preview/apply logic is identical."""
        stride = (source_end - source_start).days + 1
        stride = max(stride, 1)

        stmt = select(Shift).where(
            Shift.tenant_id == tenant_id,
            Shift.date >= source_start,
            Shift.date <= source_end,
        )
        if employee_ids:
            stmt = stmt.where(Shift.employee_id.in_(employee_ids))
        stmt = stmt.order_by(Shift.employee_id, Shift.date, Shift.sequence_number)
        shifts = (await db.execute(stmt)).scalars().all()

        targets: list = []
        for s in shifts:
            offset = (s.date - source_start).days
            shift_date = target_start + timedelta(days=offset)
            entry = {
                "status": s.status,
                "start_time": s.start_time.isoformat() if s.start_time else None,
                "end_time": s.end_time.isoformat() if s.end_time else None,
                "work_arrangement": s.work_arrangement,
                "role_name": s.role_name,
                "color": s.color,
                "notes": s.notes,
                "remarks": s.remarks,
            }
            targets.append((s.employee_id, shift_date, entry))

        occurrences = [{
            "index": 0,
            "start_date": target_start,
            "end_date": target_start + timedelta(days=stride - 1),
        }]
        return occurrences, targets

    @staticmethod
    async def preview_copy_week(
        db: AsyncSession,
        tenant_id: UUID,
        source_start: date,
        source_end: date,
        target_start: date,
        employee_ids: Optional[List[int]],
    ) -> dict:
        """Dry-run for copy-week: occurrences + blocking/resolvable conflicts,
        writing nothing. Mirrors preview_snapshot_apply's conflict split."""
        stride = (source_end - source_start).days + 1
        occurrences, targets = await ScheduleService._week_copy_targets(
            db, tenant_id, source_start, source_end, target_start, employee_ids
        )
        report = await ScheduleService._preview_targets(db, tenant_id, targets)
        report.update({
            "occurrences": occurrences,
            "stride_days": max(stride, 1),
            "total_shifts": len(targets),
        })
        return report

    @staticmethod
    async def copy_week(
        db: AsyncSession,
        tenant_id: UUID,
        source_start: date,
        source_end: date,
        target_start: date,
        employee_ids: Optional[List[int]],
        created_by: Optional[int] = None,
        *,
        on_conflict: str = "skip",
    ) -> dict:
        """Copy the shifts in [source_start, source_end] to a window starting at
        target_start. Approved-leave dates are always skipped; existing shifts /
        guardrail breaches are skipped or overwritten per on_conflict. Returns
        {created, overwritten, skipped}."""
        _, targets = await ScheduleService._week_copy_targets(
            db, tenant_id, source_start, source_end, target_start, employee_ids
        )
        return await ScheduleService._apply_targets(
            db, tenant_id, targets, on_conflict=on_conflict, created_by=created_by
        )

    # ── Shared target preview/apply (used by copy-week; mirrors snapshot) ──
    @staticmethod
    async def _preview_targets(
        db: AsyncSession, tenant_id: UUID, targets: list
    ) -> dict:
        """Split a target list into blocking (approved leave) vs resolvable
        (existing shift / guardrail) conflicts, plus a create_count. No writes."""
        by_emp_status: Dict[int, list] = defaultdict(list)
        by_emp_dates: Dict[int, List[date]] = defaultdict(list)
        for emp_id, shift_date, entry in targets:
            by_emp_status[emp_id].append((shift_date, entry.get("status", "scheduled")))
            by_emp_dates[emp_id].append(shift_date)

        emp_ids = list(by_emp_status.keys())
        names: Dict[int, str] = {}
        if emp_ids:
            rows = await db.execute(
                select(User.id, User.first_name, User.last_name).where(User.id.in_(emp_ids))
            )
            for uid, fn, ln in rows.all():
                names[uid] = f"{fn} {ln}"

        blocking: List[dict] = []
        resolvable: List[dict] = []
        for emp_id in emp_ids:
            existing = await ScheduleService._existing_shift_dates(
                db, tenant_id, emp_id, by_emp_dates[emp_id]
            )
            dates_by_status: Dict[str, List[date]] = defaultdict(list)
            for shift_date, status in by_emp_status[emp_id]:
                dates_by_status[status].append(shift_date)

            leave_dates: set = set()
            for status, dts in dates_by_status.items():
                conflicts = await ScheduleService.check_scheduling_conflicts(
                    db, tenant_id, emp_id, dts, status, force=False
                )
                for c in conflicts:
                    row = {
                        "employee_id": emp_id,
                        "employee_name": names.get(emp_id, str(emp_id)),
                        "date": c["date"],
                        "type": c["type"],
                        "forceable": c["forceable"],
                        "message": c["message"],
                        "has_existing_shift": c["date"] in {d.isoformat() for d in existing},
                    }
                    if c["type"] == "approved_leave":
                        leave_dates.add(c["date"])
                        blocking.append(row)
                    else:
                        resolvable.append(row)

            for shift_date in by_emp_dates[emp_id]:
                if shift_date in existing and shift_date.isoformat() not in leave_dates:
                    resolvable.append({
                        "employee_id": emp_id,
                        "employee_name": names.get(emp_id, str(emp_id)),
                        "date": shift_date.isoformat(),
                        "type": "existing_shift",
                        "forceable": True,
                        "message": f"A shift already exists on {shift_date.isoformat()}.",
                        "has_existing_shift": True,
                    })

        blocking_keys = {(c["employee_id"], c["date"]) for c in blocking}
        create_count = sum(
            1 for emp_id, d, _ in targets
            if (emp_id, d.isoformat()) not in blocking_keys
        )
        return {
            "create_count": create_count,
            "blocking_conflicts": blocking,
            "resolvable_conflicts": resolvable,
        }

    @staticmethod
    async def _apply_targets(
        db: AsyncSession,
        tenant_id: UUID,
        targets: list,
        *,
        on_conflict: str = "skip",
        created_by: Optional[int] = None,
    ) -> dict:
        """Create shifts for a target list. Approved-leave always skipped;
        existing/guardrail skipped or overwritten per on_conflict."""
        from datetime import time as _time

        category_map = await ScheduleService._get_category_map(db, tenant_id)
        created = 0
        overwritten = 0
        skipped: List[dict] = []
        force = on_conflict == "overwrite"

        for emp_id, shift_date, shift_entry in targets:
            status = shift_entry.get("status", "scheduled")

            conflicts = await ScheduleService.check_scheduling_conflicts(
                db, tenant_id, emp_id, [shift_date], status, force=force
            )
            if conflicts:
                skipped.append({
                    "employee_id": emp_id,
                    "date": shift_date.isoformat(),
                    "reason": conflicts[0]["type"],
                    "message": conflicts[0]["message"],
                })
                continue

            existing = (await db.execute(
                select(Shift).where(
                    Shift.tenant_id == tenant_id,
                    Shift.employee_id == emp_id,
                    Shift.date == shift_date,
                )
            )).scalars().all()
            if existing:
                if not force:
                    skipped.append({
                        "employee_id": emp_id,
                        "date": shift_date.isoformat(),
                        "reason": "existing_shift",
                        "message": f"A shift already exists on {shift_date.isoformat()}.",
                    })
                    continue
                for old in existing:
                    await db.delete(old)
                await db.flush()
                overwritten += 1

            start_time_str = shift_entry.get("start_time")
            end_time_str = shift_entry.get("end_time")
            start_time = _time.fromisoformat(start_time_str) if start_time_str else None
            end_time = _time.fromisoformat(end_time_str) if end_time_str else None
            if category_map.get(status, "leave") != "work":
                start_time = None
                end_time = None

            seq = await ScheduleService._next_sequence_number(
                db, tenant_id, emp_id, shift_date,
            )
            db.add(Shift(
                tenant_id=tenant_id,
                employee_id=emp_id,
                date=shift_date,
                start_time=start_time,
                end_time=end_time,
                sequence_number=seq,
                status=status,
                work_arrangement=shift_entry.get("work_arrangement"),
                role_name=shift_entry.get("role_name"),
                color=shift_entry.get("color"),
                notes=shift_entry.get("notes"),
                remarks=shift_entry.get("remarks"),
                created_by=created_by,
            ))
            await db.flush()
            created += 1

        return {"created": created, "skipped": skipped, "overwritten": overwritten}

    # ── Guardrail lint (read-only) ───────────────────────────────────────
    @staticmethod
    async def lint_schedule(
        db: AsyncSession,
        tenant_id: UUID,
        start_date: date,
        end_date: date,
        employee_ids: Optional[List[int]] = None,
    ) -> List[dict]:
        """Report guardrail violations in the EXISTING shifts within
        [start_date, end_date], without changing anything. Flags, per (employee,
        date) inside the range:
          - max_consecutive_work_days: the date is in a work-day run longer than
            the tenant limit;
          - min_rest_days_per_week: the rolling 7-day window starting on the date
            has fewer than the required rest days;
          - approved_leave: a WORK shift sits on an approved-leave day.
        Returns [{employee_id, date, type, message}]."""
        settings = (await db.execute(
            select(AppSettings).where(AppSettings.tenant_id == tenant_id)
        )).scalar_one_or_none()
        max_consec = getattr(settings, "max_consecutive_work_days", 0) or 0
        min_rest = getattr(settings, "min_rest_days_per_week", 0) or 0

        category_map = await ScheduleService._get_category_map(db, tenant_id)

        # Pad the window so runs that straddle the range edges are counted.
        window_start = start_date - timedelta(days=7)
        window_end = end_date + timedelta(days=7)

        stmt = select(Shift.employee_id, Shift.date, Shift.status).where(
            Shift.tenant_id == tenant_id,
            Shift.date >= window_start,
            Shift.date <= window_end,
        )
        if employee_ids:
            stmt = stmt.where(Shift.employee_id.in_(employee_ids))
        rows = (await db.execute(stmt)).all()

        work_days_by_emp: Dict[int, set] = defaultdict(set)
        for emp_id, d, status in rows:
            if category_map.get(status, "leave") == "work":
                work_days_by_emp[emp_id].add(d)

        violations: List[dict] = []
        for emp_id, work_days in work_days_by_emp.items():
            in_range = sorted(d for d in work_days if start_date <= d <= end_date)

            if max_consec:
                for d in in_range:
                    run = 1
                    p = d - timedelta(days=1)
                    while p in work_days:
                        run += 1
                        p -= timedelta(days=1)
                    n = d + timedelta(days=1)
                    while n in work_days:
                        run += 1
                        n += timedelta(days=1)
                    if run > max_consec:
                        violations.append({
                            "employee_id": emp_id,
                            "date": d.isoformat(),
                            "type": "max_consecutive_work_days",
                            "message": f"{run} consecutive work days (limit {max_consec}).",
                        })

            if min_rest:
                max_work_per_week = 7 - min_rest
                for d in in_range:
                    work_in_window = sum(
                        1 for i in range(7) if (d + timedelta(days=i)) in work_days
                    )
                    if work_in_window > max_work_per_week:
                        violations.append({
                            "employee_id": emp_id,
                            "date": d.isoformat(),
                            "type": "min_rest_days_per_week",
                            "message": f"{work_in_window} work days in the next 7 (min {min_rest} rest).",
                        })

            leave_dates = await ScheduleService._approved_leave_dates(
                db, tenant_id, emp_id, start_date, end_date
            )
            for d in in_range:
                if d in leave_dates:
                    violations.append({
                        "employee_id": emp_id,
                        "date": d.isoformat(),
                        "type": "approved_leave",
                        "message": "Work shift on an approved-leave day.",
                    })

        return violations

    # ── Draft / publish ──────────────────────────────────────────────────
    @staticmethod
    async def publish_range(
        db: AsyncSession,
        tenant_id: UUID,
        start_date: date,
        end_date: date,
        employee_ids: Optional[List[int]],
        published_by: Optional[int] = None,
    ) -> dict:
        """Publish (release) the DRAFT shifts in [start_date, end_date] for the
        given employees. Returns {published_count, employee_ids} where the id
        list is the DISTINCT employees who had something published (for
        notifications)."""
        from datetime import datetime as _dt

        stmt = select(Shift).where(
            Shift.tenant_id == tenant_id,
            Shift.date >= start_date,
            Shift.date <= end_date,
            Shift.is_published == False,  # noqa: E712
        )
        if employee_ids:
            stmt = stmt.where(Shift.employee_id.in_(employee_ids))
        shifts = (await db.execute(stmt)).scalars().all()

        now = _dt.utcnow()
        affected: set = set()
        for s in shifts:
            s.is_published = True
            s.published_at = now
            s.published_by = published_by
            affected.add(s.employee_id)
        await db.flush()
        return {"published_count": len(shifts), "employee_ids": sorted(affected)}

    @staticmethod
    async def unpublish_range(
        db: AsyncSession,
        tenant_id: UUID,
        start_date: date,
        end_date: date,
        employee_ids: Optional[List[int]],
    ) -> dict:
        """Return published shifts in the range to DRAFT (hidden from employees)
        so they can be reworked. Returns {unpublished_count}."""
        stmt = select(Shift).where(
            Shift.tenant_id == tenant_id,
            Shift.date >= start_date,
            Shift.date <= end_date,
            Shift.is_published == True,  # noqa: E712
        )
        if employee_ids:
            stmt = stmt.where(Shift.employee_id.in_(employee_ids))
        shifts = (await db.execute(stmt)).scalars().all()
        for s in shifts:
            s.is_published = False
            s.published_at = None
            s.published_by = None
        await db.flush()
        return {"unpublished_count": len(shifts)}
