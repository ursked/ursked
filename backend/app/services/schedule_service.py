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
from app.models.attendance import AttendanceRecord, OvertimeLog
from app.models.leave import LeaveApplication, LeaveApproverAssignment
from app.models.user import User
from app.utils.timeutil import utcnow


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


_HOUR_RULE_TYPES = {"max_hours_per_day", "max_hours_per_week", "min_rest_hours", "overlapping_shifts"}


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
        # The roles that schedule everyone (FULL_SCOPE_ROLES["schedules"]).
        # tenant_admin is not one: schedules are operations (permission_service).
        from app.services.permission_service import FULL_SCOPE_ROLES

        if FULL_SCOPE_ROLES["schedules"].intersection(set(user_roles)):
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
        include_actuals: bool = False,
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

        # 4. Date remarks, with recurring holidays on this range's dates.
        remark_dicts = await ScheduleService.get_calendar_remarks(
            db, tenant_id, start_date, end_date
        )

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
                    "leave_application_id": s.leave_application_id,
                    "work_site_id": s.work_site_id,
                })

            employees.append({
                "employee_id": user.id,
                "employee_name": f"{user.first_name} {user.last_name}",
                "section_name": user.section.name if user.section else None,
                "unit_name": user.unit.name if user.unit else None,
                "shifts": shift_dicts,
            })

        # 8. Actuals (opt-in). Left empty otherwise, so the planning payload is
        # unchanged for callers that do not ask for them.
        actuals: List[dict] = []
        if include_actuals and employee_ids:
            actuals = await ScheduleService._load_actuals(
                db, tenant_id, employee_ids, start_date, end_date
            )

        return {
            "employees": employees,
            "dates": dates,
            "date_remarks": remark_dicts,
            "stats": stats,
            "actuals": actuals,
        }

    @staticmethod
    async def _load_actuals(
        db: AsyncSession,
        tenant_id: UUID,
        employee_ids: List[int],
        start_date: date,
        end_date: date,
    ) -> List[dict]:
        """Attendance outcome and approved overtime per (employee, date).

        Only *approved* (or already converted) overtime is reported. A pending
        overtime log is a claim awaiting a decision; showing it on the schedule
        alongside approved hours would present the two as equally settled.
        """
        att_rows = (await db.execute(
            select(
                AttendanceRecord.employee_id,
                AttendanceRecord.date,
                AttendanceRecord.status,
                AttendanceRecord.tardiness_minutes,
            ).where(
                AttendanceRecord.tenant_id == tenant_id,
                AttendanceRecord.employee_id.in_(employee_ids),
                AttendanceRecord.date >= start_date,
                AttendanceRecord.date <= end_date,
            )
        )).all()

        ot_rows = (await db.execute(
            select(
                OvertimeLog.employee_id,
                OvertimeLog.date,
                func.sum(OvertimeLog.overtime_minutes),
            ).where(
                OvertimeLog.tenant_id == tenant_id,
                OvertimeLog.employee_id.in_(employee_ids),
                OvertimeLog.date >= start_date,
                OvertimeLog.date <= end_date,
                OvertimeLog.status.in_(["approved", "converted"]),
            ).group_by(OvertimeLog.employee_id, OvertimeLog.date)
        )).all()

        merged: Dict[tuple, dict] = {}
        for emp_id, d, status, tardiness in att_rows:
            merged[(emp_id, d)] = {
                "employee_id": emp_id,
                "date": d.isoformat(),
                "attendance_status": status,
                "tardiness_minutes": tardiness or 0,
                "overtime_minutes": 0,
            }
        for emp_id, d, minutes in ot_rows:
            entry = merged.get((emp_id, d))
            if entry is None:
                # Overtime can exist on a day with no attendance row.
                entry = {
                    "employee_id": emp_id,
                    "date": d.isoformat(),
                    "attendance_status": None,
                    "tardiness_minutes": 0,
                    "overtime_minutes": 0,
                }
                merged[(emp_id, d)] = entry
            entry["overtime_minutes"] = int(minutes or 0)

        return list(merged.values())

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

    # ── One validator for every write path ─────────────────────────────
    #
    # Until 2026-09 only "create" was checked. Editing a shift, dragging it to
    # another day or employee, swapping, approving a change request, applying
    # a template and copying all wrote straight past approved leave and the
    # guardrails, so the same roster could be refused through one button and
    # accepted through another. Every path now builds the shifts it is about
    # to write as "placements" and asks `validate_placements`, which answers
    # against the employee's schedule as it WILL be (the shifts being moved or
    # replaced are left out via ignore_shift_ids).
    #
    # Leave conflicts can never be overridden. Everything else is a guardrail
    # the editor may force, exactly as the consecutive-days rule always was.

    @staticmethod
    async def _load_app_settings(db: AsyncSession, tenant_id: UUID):
        return (await db.execute(
            select(AppSettings).where(AppSettings.tenant_id == tenant_id)
        )).scalar_one_or_none()

    @staticmethod
    def _as_time(v):
        """JSON-sourced times (snapshots, templates, copies) arrive as strings."""
        from datetime import time as _time
        if v is None or isinstance(v, _time):
            return v
        try:
            return _time.fromisoformat(str(v))
        except ValueError:
            return None

    @staticmethod
    def _interval(d: date, start, end):
        """A shift as a real datetime span. An end at or before the start runs
        past midnight (22:00-06:00 is eight hours, not minus sixteen)."""
        from datetime import datetime as _dt
        if start is None or end is None:
            return None
        s = _dt.combine(d, start)
        e = _dt.combine(d, end)
        if e <= s:
            e += timedelta(days=1)
        return (s, e)

    @staticmethod
    def _hours(v: float) -> str:
        return f"{v:.2f}".rstrip("0").rstrip(".")

    @staticmethod
    async def validate_placements(
        db: AsyncSession,
        tenant_id: UUID,
        placements: List[dict],
        *,
        force: bool = False,
        ignore_shift_ids=(),
        category_map: Optional[Dict[str, str]] = None,
        settings=None,
    ) -> List[dict]:
        """Check shifts that are about to be written.

        Each placement is {employee_id, date, status, start_time?, end_time?}.
        Returns [{employee_id, date, type, forceable, message}]:

          approved_leave             work on a day of approved leave (never forceable)
          max_consecutive_work_days  a run of work days longer than the limit
          min_rest_days_per_week     too few rest days in the 7 days from a date
          max_hours_per_day          more work hours on a date than the limit
          max_hours_per_week         more work hours in the tenant's week
          min_rest_hours             too little rest between two working days
          overlapping_shifts         two shifts (or split-shift segments) overlap

        Only non-work statuses (rest, leave) never conflict. A violation is
        reported only when it involves a placement, so a problem that already
        exists elsewhere in the calendar does not block unrelated edits.
        With force=True only the non-forceable conflicts are returned.
        """
        if not placements:
            return []
        if category_map is None:
            category_map = await ScheduleService._get_category_map(db, tenant_id)
        if settings is None:
            settings = await ScheduleService._load_app_settings(db, tenant_id)
        max_consec = getattr(settings, "max_consecutive_work_days", 0) or 0
        min_rest_days = getattr(settings, "min_rest_days_per_week", 0) or 0
        max_day_h = float(getattr(settings, "max_work_hours_per_day", 0) or 0)
        max_week_h = float(getattr(settings, "max_work_hours_per_week", 0) or 0)
        min_rest_h = float(getattr(settings, "min_rest_hours_between_shifts", 0) or 0)
        check_overlap = bool(getattr(settings, "check_overlapping_shifts", False))
        week_starts_on = getattr(settings, "week_starts_on", None) or "monday"
        ws = {"monday": 0, "sunday": 6, "saturday": 5}.get(week_starts_on, 0)
        ignore = set(ignore_shift_ids or ())
        H = ScheduleService._hours

        by_emp: Dict[int, List[dict]] = defaultdict(list)
        for p in placements:
            by_emp[p["employee_id"]].append(p)

        conflicts: List[dict] = []
        for emp_id, items in by_emp.items():
            work = [p for p in items if category_map.get(p.get("status") or "scheduled", "leave") == "work"]
            if not work:
                continue
            seen: set = set()

            def add(d: date, type_: str, forceable: bool, message: str):
                if (d, type_) in seen:
                    return
                seen.add((d, type_))
                conflicts.append({
                    "employee_id": emp_id,
                    "date": d.isoformat(),
                    "type": type_,
                    "forceable": forceable,
                    "message": message,
                })

            dates = sorted({p["date"] for p in work})
            span_start, span_end = dates[0], dates[-1]

            # 1. Approved leave (never forceable).
            leave = await ScheduleService._approved_leave_dates(
                db, tenant_id, emp_id, span_start, span_end
            )
            for d in dates:
                if d in leave:
                    add(d, "approved_leave", False,
                        f"Employee is on approved leave on {d.isoformat()}.")

            if not (max_consec or min_rest_days or max_day_h or max_week_h or min_rest_h or check_overlap):
                continue

            # The employee's schedule as it will be: existing work shifts
            # (minus the ones being moved/replaced) plus the placements.
            rows = (await db.execute(
                select(Shift.id, Shift.date, Shift.status, Shift.start_time, Shift.end_time).where(
                    Shift.tenant_id == tenant_id,
                    Shift.employee_id == emp_id,
                    Shift.date >= span_start - timedelta(days=8),
                    Shift.date <= span_end + timedelta(days=8),
                )
            )).all()
            existing = [
                r for r in rows
                if r.id not in ignore and category_map.get(r.status, "leave") == "work"
            ]
            work_days = {r.date for r in existing} | set(dates)

            # 2. Consecutive work days / rest days per week.
            if max_consec:
                for d in dates:
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
                        add(d, "max_consecutive_work_days", True,
                            f"Scheduling {d.isoformat()} makes a run of {run} "
                            f"consecutive work days (limit {max_consec}).")
                        break  # one guardrail hit per run is enough
            if min_rest_days:
                max_work_per_week = 7 - min_rest_days
                for d in dates:
                    work_in_window = sum(
                        1 for i in range(7) if (d + timedelta(days=i)) in work_days
                    )
                    if work_in_window > max_work_per_week:
                        add(d, "min_rest_days_per_week", True,
                            f"The 7 days from {d.isoformat()} contain "
                            f"{work_in_window} work days, leaving fewer than "
                            f"{min_rest_days} rest day(s).")
                        break

            # 3. Hours. Each shift counts on the date it starts.
            entries = []  # (date, (start, end) or None, is_new)
            for r in existing:
                entries.append((r.date, ScheduleService._interval(r.date, r.start_time, r.end_time), False))
            for p in work:
                entries.append((
                    p["date"],
                    ScheduleService._interval(
                        p["date"],
                        ScheduleService._as_time(p.get("start_time")),
                        ScheduleService._as_time(p.get("end_time")),
                    ),
                    True,
                ))

            def hours_of(iv):
                return (iv[1] - iv[0]).total_seconds() / 3600 if iv else 0.0

            if max_day_h:
                for d in dates:
                    total = sum(hours_of(iv) for ed, iv, _ in entries if ed == d)
                    if total > max_day_h + 1e-9:
                        add(d, "max_hours_per_day", True,
                            f"{H(total)} hours of work on {d.isoformat()} "
                            f"(limit {H(max_day_h)}).")

            if max_week_h:
                def week_of(d: date) -> date:
                    return d - timedelta(days=(d.weekday() - ws) % 7)

                weeks = {week_of(d) for d in dates}
                for wk in weeks:
                    base = sum(hours_of(iv) for ed, iv, new in entries if not new and week_of(ed) == wk)
                    running = base
                    news = sorted(
                        ((ed, iv) for ed, iv, new in entries if new and week_of(ed) == wk),
                        key=lambda x: (x[0], x[1][0] if x[1] else x[0]),
                    )
                    for ed, iv in news:
                        running += hours_of(iv)
                        if running > max_week_h + 1e-9:
                            add(ed, "max_hours_per_week", True,
                                f"{H(running)} hours of work in the week of "
                                f"{wk.isoformat()} (limit {H(max_week_h)}).")

            timed = sorted((e for e in entries if e[1]), key=lambda e: e[1][0])
            if check_overlap:
                for i, (d_i, iv_i, new_i) in enumerate(timed):
                    for d_j, iv_j, new_j in timed[:i]:
                        if iv_j[1] > iv_i[0] and (new_i or new_j):
                            add(d_i if new_i else d_j, "overlapping_shifts", True,
                                f"Two shifts overlap on {(d_i if new_i else d_j).isoformat()} "
                                f"({iv_j[0]:%H:%M}-{iv_j[1]:%H:%M} and "
                                f"{iv_i[0]:%H:%M}-{iv_i[1]:%H:%M}).")
            if min_rest_h:
                # Rest is between working DAYS: the segments of one day's split
                # shift are not rest periods.
                days: Dict[date, list] = {}
                for d, iv, new in timed:
                    w = days.setdefault(d, [iv[0], iv[1], False])
                    w[0] = min(w[0], iv[0])
                    w[1] = max(w[1], iv[1])
                    w[2] = w[2] or new
                ordered = sorted(days.items(), key=lambda kv: kv[1][0])
                for (d_a, a), (d_b, b) in zip(ordered, ordered[1:]):
                    if not (a[2] or b[2]):
                        continue
                    gap = (b[0] - a[1]).total_seconds() / 3600
                    if 0 <= gap < min_rest_h:
                        flagged = d_b if b[2] else d_a
                        add(flagged, "min_rest_hours", True,
                            f"Only {H(gap)} hours of rest between the shifts on "
                            f"{d_a.isoformat()} and {d_b.isoformat()} "
                            f"(minimum {H(min_rest_h)}).")

        if force:
            conflicts = [c for c in conflicts if not c["forceable"]]
        return conflicts

    @staticmethod
    async def check_scheduling_conflicts(
        db: AsyncSession,
        tenant_id: UUID,
        employee_id: int,
        target_dates: List[date],
        status: str,
        *,
        force: bool = False,
        start_time=None,
        end_time=None,
    ) -> List[dict]:
        """`validate_placements` for one employee, one status, many dates."""
        return await ScheduleService.validate_placements(
            db, tenant_id,
            [
                {"employee_id": employee_id, "date": d, "status": status,
                 "start_time": start_time, "end_time": end_time}
                for d in target_dates
            ],
            force=force,
        )

    # ── Domain events ──────────────────────────────────────────────────
    #
    # Every write to shifts, including the system's own (leave overlay and
    # revert, automatic holiday-off), announces itself through
    # domain_events: shift.before_write before anything is persisted, so a
    # handler can veto by raising (e.g. "that payroll period is finalized"),
    # and shift.after_write once flushed, so attendance and the like can be
    # re-derived. `changes` lists every (employee_id, date) touched, both the
    # old and the new key of a move.

    @staticmethod
    async def _emit(event: str, db: AsyncSession, tenant_id: UUID, actor, changes) -> None:
        from app.services import domain_events

        keys = sorted({(e, d) for e, d in changes if e is not None and d is not None})
        if keys:
            await domain_events.emit(
                event, db=db, tenant_id=tenant_id, actor=actor, changes=keys,
            )

    @staticmethod
    async def _before(db, tenant_id, actor, changes) -> None:
        await ScheduleService._emit("shift.before_write", db, tenant_id, actor, changes)

    @staticmethod
    async def _after(db, tenant_id, actor, changes) -> None:
        await ScheduleService._emit("shift.after_write", db, tenant_id, actor, changes)

    @staticmethod
    def _leave_locked(shift: Shift) -> ScheduleConflictError:
        return ScheduleConflictError([{
            "employee_id": shift.employee_id,
            "date": shift.date.isoformat(),
            "type": "approved_leave_locked",
            "forceable": False,
            "message": (
                f"{shift.date.isoformat()} is an approved leave day. Change it "
                "through the leave request (unapprove or cancel it), not on the "
                "schedule."
            ),
        }])

    # Fields an edit may set. Everything but employee, date and status may be
    # cleared with an explicit null.
    _EDITABLE = {
        "employee_id", "date", "start_time", "end_time", "status",
        "work_arrangement", "role_name", "color", "notes", "remarks", "work_site_id",
    }
    _NOT_NULL = {"employee_id", "date", "status"}
    _PLACEMENT_FIELDS = {"employee_id", "date", "status", "start_time", "end_time"}

    @staticmethod
    async def create_shift(
        db: AsyncSession,
        tenant_id: UUID,
        data: dict,
        created_by: Optional[int] = None,
        *,
        force: bool = False,
        actor: Optional[User] = None,
    ) -> Shift:
        """Create a new shift. Auto-calculates sequence_number.

        Raises ScheduleConflictError if the shift lands on approved leave or
        breaches a tenant guardrail (unless force=True for guardrails).
        """
        status = data.get("status") or "scheduled"
        category_map = await ScheduleService._get_category_map(db, tenant_id)
        is_work = category_map.get(status, "leave") == "work"
        # If status is not a "work" category, clear time fields
        start_time = data.get("start_time") if is_work else None
        end_time = data.get("end_time") if is_work else None

        conflicts = await ScheduleService.validate_placements(
            db, tenant_id,
            [{"employee_id": data["employee_id"], "date": data["date"], "status": status,
              "start_time": start_time, "end_time": end_time}],
            force=force, category_map=category_map,
        )
        if conflicts:
            raise ScheduleConflictError(conflicts)

        key = [(data["employee_id"], data["date"])]
        await ScheduleService._before(db, tenant_id, actor, key)
        sequence_number = await ScheduleService._next_sequence_number(
            db, tenant_id, data["employee_id"], data["date"]
        )
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
            work_site_id=data.get("work_site_id"),
            created_by=created_by,
        )
        db.add(shift)
        await db.flush()
        await db.refresh(shift)
        await ScheduleService._after(db, tenant_id, actor, key)
        return shift

    @staticmethod
    async def bulk_create_shifts(
        db: AsyncSession,
        tenant_id: UUID,
        data: dict,
        created_by: Optional[int] = None,
        *,
        force: bool = False,
        actor: Optional[User] = None,
    ) -> tuple:
        """
        Create shifts for multiple employees across a date range.
        Optionally skip weekends and/or holidays.

        Returns ``(created_shifts, skipped_conflicts)``. Dates that would land
        on approved leave (or breach a guardrail when force=False) are skipped
        rather than failing the whole batch, and reported back to the caller.
        """
        from app.services.holiday_calendar import holidays_between

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

        # Recurring holidays count too (they used to be missed here).
        holiday_dates: set = set()
        if skip_holidays:
            holiday_dates = set(await holidays_between(db, tenant_id, start_date, end_date))

        status = data.get("status") or "scheduled"
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

        settings = await ScheduleService._load_app_settings(db, tenant_id)
        skipped_conflicts: List[dict] = []
        to_create: List[tuple] = []
        for employee_id in employee_ids:
            conflicts = await ScheduleService.validate_placements(
                db, tenant_id,
                [{"employee_id": employee_id, "date": d, "status": status,
                  "start_time": start_time, "end_time": end_time} for d in eligible_dates],
                force=force, category_map=category_map, settings=settings,
            )
            blocked_dates = {c["date"] for c in conflicts}
            skipped_conflicts.extend(conflicts)
            to_create.extend(
                (employee_id, d) for d in eligible_dates if d.isoformat() not in blocked_dates
            )

        await ScheduleService._before(db, tenant_id, actor, to_create)
        created_shifts: List[Shift] = []
        for employee_id, d in to_create:
            seq = await ScheduleService._next_sequence_number(db, tenant_id, employee_id, d)
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
                work_site_id=data.get("work_site_id"),
                created_by=created_by,
            )
            db.add(shift)
            created_shifts.append(shift)

        await db.flush()
        for shift in created_shifts:
            await db.refresh(shift)
        await ScheduleService._after(db, tenant_id, actor, to_create)

        return created_shifts, skipped_conflicts

    @staticmethod
    async def update_shift(
        db: AsyncSession,
        shift_id: int,
        tenant_id: UUID,
        data: dict,
        *,
        force: bool = False,
        actor: Optional[User] = None,
    ) -> Optional[Shift]:
        """Update a shift with PATCH semantics: only the keys given change, and
        an explicit null clears an optional field (notes, remarks, colour, role,
        times, work arrangement, work site). It used to skip every None, so a
        note once written could never be removed.

        Editing, dragging to another day and moving to another employee all go
        through the same validator as create. A shift that belongs to an
        approved leave cannot be moved or have its status/times changed (its
        notes can): leave changes go through the leave request.
        """
        stmt = select(Shift).where(Shift.id == shift_id, Shift.tenant_id == tenant_id)
        shift = (await db.execute(stmt)).scalar_one_or_none()
        if not shift:
            return None

        changed = {}
        for key, value in data.items():
            if key not in ScheduleService._EDITABLE:
                continue
            if value is None and key in ScheduleService._NOT_NULL:
                continue
            if getattr(shift, key) != value:
                changed[key] = value
        if not changed:
            return shift

        placement_change = bool(changed.keys() & ScheduleService._PLACEMENT_FIELDS)
        if shift.leave_application_id is not None and placement_change:
            raise ScheduleService._leave_locked(shift)

        category_map = await ScheduleService._get_category_map(db, tenant_id)
        target_emp = changed.get("employee_id", shift.employee_id)
        target_date = changed.get("date", shift.date)
        status = changed.get("status", shift.status)
        is_work = category_map.get(status, "leave") == "work"
        start_time = changed.get("start_time", shift.start_time) if is_work else None
        end_time = changed.get("end_time", shift.end_time) if is_work else None

        if placement_change:
            conflicts = await ScheduleService.validate_placements(
                db, tenant_id,
                [{"employee_id": target_emp, "date": target_date, "status": status,
                  "start_time": start_time, "end_time": end_time}],
                force=force, ignore_shift_ids={shift.id}, category_map=category_map,
            )
            if conflicts:
                raise ScheduleConflictError(conflicts)

        keys = [(shift.employee_id, shift.date), (target_emp, target_date)]
        await ScheduleService._before(db, tenant_id, actor, keys)

        # Pre-compute the new sequence_number BEFORE applying changes (to avoid
        # an autoflush unique-constraint violation).
        new_sequence_number = None
        if target_emp != shift.employee_id or target_date != shift.date:
            new_sequence_number = await ScheduleService._next_sequence_number(
                db, tenant_id, target_emp, target_date
            )

        for key, value in changed.items():
            setattr(shift, key, value)
        if new_sequence_number is not None:
            shift.sequence_number = new_sequence_number
        if not is_work:
            shift.start_time = None
            shift.end_time = None
        # An edited holiday-off shift is the editor's now; deleting or moving
        # the holiday must leave it alone.
        shift.holiday_remark_id = None

        await db.flush()
        await db.refresh(shift)
        await ScheduleService._after(db, tenant_id, actor, keys)
        return shift

    @staticmethod
    async def delete_shift(
        db: AsyncSession,
        shift_id: int,
        tenant_id: UUID,
        *,
        actor: Optional[User] = None,
    ) -> bool:
        """Delete a shift by id and tenant_id. Returns True if deleted.

        An approved-leave day is refused: deleting it would silently undo a
        leave decision that still stands."""
        stmt = select(Shift).where(Shift.id == shift_id, Shift.tenant_id == tenant_id)
        shift = (await db.execute(stmt)).scalar_one_or_none()
        if not shift:
            return False
        if shift.leave_application_id is not None:
            raise ScheduleService._leave_locked(shift)

        keys = [(shift.employee_id, shift.date)]
        await ScheduleService._before(db, tenant_id, actor, keys)
        await db.delete(shift)
        await db.flush()
        await ScheduleService._after(db, tenant_id, actor, keys)
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
        *,
        actor: Optional[User] = None,
        skipped: Optional[list] = None,
    ) -> List[Shift]:
        """
        Copy shifts from a source employee in a date range to one or more
        target employees, offsetting dates so that source_start_date maps
        to target_start_date. Days that conflict for a target (approved leave,
        guardrails) are skipped and appended to `skipped`; the source's own
        leave days are not copied (they are that person's leave, not a
        pattern).
        """
        day_offset = (target_start_date - source_start_date).days

        stmt = (
            select(Shift)
            .where(
                Shift.tenant_id == tenant_id,
                Shift.employee_id == source_employee_id,
                Shift.date >= source_start_date,
                Shift.date <= source_end_date,
                Shift.leave_application_id.is_(None),
            )
            .order_by(Shift.date, Shift.sequence_number)
        )
        source_shifts = (await db.execute(stmt)).scalars().all()

        category_map = await ScheduleService._get_category_map(db, tenant_id)
        settings = await ScheduleService._load_app_settings(db, tenant_id)
        plan: List[tuple] = []
        for target_employee_id in target_employee_ids:
            placements = [
                {"employee_id": target_employee_id,
                 "date": src.date + timedelta(days=day_offset),
                 "status": src.status, "start_time": src.start_time, "end_time": src.end_time}
                for src in source_shifts
            ]
            conflicts = await ScheduleService.validate_placements(
                db, tenant_id, placements, category_map=category_map, settings=settings,
            )
            if skipped is not None:
                skipped.extend(conflicts)
            blocked = {c["date"] for c in conflicts}
            plan.extend(
                (target_employee_id, src) for src in source_shifts
                if (src.date + timedelta(days=day_offset)).isoformat() not in blocked
            )

        keys = [(e, src.date + timedelta(days=day_offset)) for e, src in plan]
        await ScheduleService._before(db, tenant_id, actor, keys)
        created_shifts: List[Shift] = []
        for target_employee_id, src in plan:
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
                work_site_id=src.work_site_id,
                created_by=created_by,
            )
            db.add(new_shift)
            created_shifts.append(new_shift)

        await db.flush()
        for shift in created_shifts:
            await db.refresh(shift)
        await ScheduleService._after(db, tenant_id, actor, keys)
        return created_shifts

    # ── Date Remarks ────────────────────────────────────────────────────
    #
    # Holidays are DateRemark rows with is_holiday=True. Which days ARE
    # holidays is always answered by holiday_calendar.holidays_between (it
    # expands recurring ones); this section only manages the rows and the
    # consequences of changing them.

    @staticmethod
    async def get_date_remarks(
        db: AsyncSession,
        tenant_id: UUID,
        start_date: date,
        end_date: date,
    ) -> List[DateRemark]:
        """Date remark rows stored for a date range (tombstones excluded)."""
        stmt = (
            select(DateRemark)
            .where(
                DateRemark.tenant_id == tenant_id,
                DateRemark.date >= start_date,
                DateRemark.date <= end_date,
                DateRemark.is_suppressed == False,  # noqa: E712
            )
            .order_by(DateRemark.date)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    def remark_view(r: DateRemark, on_date: Optional[date] = None) -> dict:
        """A remark as the API shows it. For a recurring holiday shown in
        another year, `date` is that year's occurrence and `stored_date` the
        row's own date, which is what an edit must change."""
        return {
            "id": r.id,
            "date": on_date or r.date,
            "stored_date": r.date,
            "title": r.title,
            "description": r.description,
            "is_holiday": bool(r.is_holiday),
            "is_special": bool(r.is_special),
            "is_recurring": bool(r.is_recurring),
            "source": r.source or "manual",
            "is_tentative": bool(r.is_tentative),
            "region": r.region,
            "needs_review": bool(r.needs_review),
            "locally_modified": bool(r.locally_modified),
        }

    @staticmethod
    async def get_calendar_remarks(
        db: AsyncSession, tenant_id: UUID, start_date: date, end_date: date
    ) -> List[dict]:
        """Everything the grid marks on its date headers: plain notes stored
        in the range, plus every holiday in the range including recurring ones
        stored in another year (the grid used to miss those)."""
        from app.services.holiday_calendar import holidays_between

        rows = await ScheduleService.get_date_remarks(db, tenant_id, start_date, end_date)
        by_date: Dict[date, dict] = {
            r.date: ScheduleService.remark_view(r) for r in rows if not r.is_holiday
        }
        holidays = await holidays_between(db, tenant_id, start_date, end_date)
        if holidays:
            ids = {h.remark_id for h in holidays.values()}
            remark_rows = {
                r.id: r for r in (await db.execute(
                    select(DateRemark).where(DateRemark.id.in_(ids))
                )).scalars().all()
            }
            for d, h in holidays.items():
                r = remark_rows.get(h.remark_id)
                if r is not None:
                    by_date[d] = ScheduleService.remark_view(r, on_date=d)
        return [by_date[d] for d in sorted(by_date)]

    @staticmethod
    def _holiday_dates(r: DateRemark, start: date, end: date) -> set:
        """The dates `r` makes a holiday within [start, end]."""
        if not r.is_holiday or r.is_suppressed:
            return set()
        if not r.is_recurring:
            return {r.date} if start <= r.date <= end else set()
        out = set()
        for year in range(start.year, end.year + 1):
            try:
                d = r.date.replace(year=year)
            except ValueError:  # 29 February
                continue
            if start <= d <= end and d >= r.date:
                out.add(d)
        return out

    @staticmethod
    def _generation_dates(r: DateRemark) -> set:
        """Where automatic holiday-off applies: a one-off holiday on its own
        date; a recurring one on its occurrences over the next year (from
        today, never before the date it was first stored)."""
        if not r.is_holiday or r.is_suppressed:
            return set()
        if not r.is_recurring:
            return {r.date}
        # A year-long window: UTC's date is as good as the company's here,
        # and unlike date.today() it does not follow the container clock.
        today = utcnow().date()
        return ScheduleService._holiday_dates(r, max(today, r.date), today + timedelta(days=365))

    @staticmethod
    def _event_dates(r: DateRemark) -> set:
        """The dates to announce in holiday.changed: the stored date and, for
        a recurring holiday, its occurrences from last year to next year (the
        span a payroll or attendance handler could still act on)."""
        if r.is_recurring:
            today = utcnow().date()
            return {r.date} | ScheduleService._holiday_dates(
                r, today - timedelta(days=400), today + timedelta(days=365)
            )
        return {r.date}

    @staticmethod
    async def _emit_holiday_changed(db, tenant_id, actor, dates) -> None:
        from app.services import domain_events

        dates = {d for d in dates if d is not None}
        if dates:
            await domain_events.emit(
                "holiday.changed", db=db, tenant_id=tenant_id, actor=actor, dates=dates,
            )

    @staticmethod
    async def _auto_holiday_off_enabled(db: AsyncSession, tenant_id: UUID) -> bool:
        settings = await ScheduleService._load_app_settings(db, tenant_id)
        return bool(getattr(settings, "auto_create_holiday_off", False))

    @staticmethod
    async def apply_holiday_off(
        db: AsyncSession, tenant_id: UUID, remark: DateRemark, dates, actor=None
    ) -> int:
        """Generate holiday-off shifts for `remark` on `dates` if the tenant
        has the setting on. Returns how many were created."""
        if not dates or not await ScheduleService._auto_holiday_off_enabled(db, tenant_id):
            return 0
        created = 0
        for d in sorted(dates):
            created += await ScheduleService._generate_holiday_off_shifts(
                db, tenant_id, d, remark_id=remark.id, actor=actor,
            )
        return created

    @staticmethod
    async def create_date_remark(
        db: AsyncSession,
        tenant_id: UUID,
        data: dict,
        actor: Optional[User] = None,
    ) -> DateRemark:
        """Create a new date remark.

        If it is a holiday and the tenant has `auto_create_holiday_off` enabled,
        also generate 'holiday_off' shifts for employees with nothing scheduled
        that day (see `_generate_holiday_off_shifts`).

        A date can hold one remark. If the only row there is the tombstone of a
        feed holiday someone deleted, the tombstone becomes this remark: the
        admin is now deliberately putting something on that date.
        """
        tomb = (await db.execute(
            select(DateRemark).where(
                DateRemark.tenant_id == tenant_id,
                DateRemark.date == data["date"],
                DateRemark.is_suppressed == True,  # noqa: E712
            )
        )).scalar_one_or_none()
        fields = dict(
            date=data["date"],
            title=data["title"],
            description=data.get("description"),
            is_holiday=data.get("is_holiday", False),
            is_special=data.get("is_special", False),
            is_recurring=data.get("is_recurring", False),
        )
        if tomb is not None:
            remark = tomb
            for k, v in fields.items():
                setattr(remark, k, v)
            remark.source = "manual"
            remark.is_suppressed = False
            remark.is_tentative = False
            remark.needs_review = False
            remark.locally_modified = False
            remark.region = None
        else:
            remark = DateRemark(tenant_id=tenant_id, **fields)
            db.add(remark)
        await db.flush()

        if remark.is_holiday:
            await ScheduleService.apply_holiday_off(
                db, tenant_id, remark, ScheduleService._generation_dates(remark), actor
            )
            await ScheduleService._emit_holiday_changed(
                db, tenant_id, actor, ScheduleService._event_dates(remark)
            )

        await db.refresh(remark)
        return remark

    @staticmethod
    async def _generate_holiday_off_shifts(
        db: AsyncSession,
        tenant_id: UUID,
        on_date: date,
        *,
        remark_id: Optional[int] = None,
        actor: Optional[User] = None,
    ) -> int:
        """Give employees with an empty calendar on `on_date` a 'holiday_off' shift.

        Deliberately additive only. An employee who already has *any* shift that
        day is skipped entirely, so this can never overwrite a planned working
        shift, a rest day, or a day already claimed by approved leave. That makes
        it safe to re-run, and undoing it is just deleting the generated rows.

        The shifts are published: they are the consequence of a holiday the
        company has declared, not a draft plan, and as drafts nobody could see
        them. They carry `holiday_remark_id` so the holiday can take them back.

        Returns the number of shifts created.
        """
        from datetime import datetime as _dt

        employee_rows = (await db.execute(
            select(User.id).where(
                User.tenant_id == tenant_id,
                User.is_active == True,  # noqa: E712
            )
        )).all()
        employee_ids = [r[0] for r in employee_rows]
        if not employee_ids:
            return 0

        busy_rows = (await db.execute(
            select(Shift.employee_id).where(
                Shift.tenant_id == tenant_id,
                Shift.date == on_date,
                Shift.employee_id.in_(employee_ids),
            )
        )).all()
        busy = {r[0] for r in busy_rows}
        free = [e for e in employee_ids if e not in busy]
        if not free:
            return 0

        keys = [(e, on_date) for e in free]
        await ScheduleService._before(db, tenant_id, actor, keys)
        now = utcnow()
        for emp_id in free:
            db.add(Shift(
                tenant_id=tenant_id,
                employee_id=emp_id,
                date=on_date,
                start_time=None,
                end_time=None,
                sequence_number=1,
                status="holiday_off",
                is_published=True,
                published_at=now,
                holiday_remark_id=remark_id,
            ))
        await db.flush()
        await ScheduleService._after(db, tenant_id, actor, keys)
        return len(free)

    @staticmethod
    async def remove_generated_holiday_off(
        db: AsyncSession,
        tenant_id: UUID,
        remark_id: int,
        dates=None,
        actor: Optional[User] = None,
    ) -> int:
        """Delete the holiday-off shifts `remark_id` generated that nobody has
        touched since (optionally only on `dates`). Returns the count."""
        stmt = select(Shift).where(
            Shift.tenant_id == tenant_id,
            Shift.holiday_remark_id == remark_id,
            Shift.status == "holiday_off",
            Shift.leave_application_id.is_(None),
        )
        if dates is not None:
            if not dates:
                return 0
            stmt = stmt.where(Shift.date.in_(list(dates)))
        shifts = list((await db.execute(stmt)).scalars().all())
        if not shifts:
            return 0
        keys = [(s.employee_id, s.date) for s in shifts]
        await ScheduleService._before(db, tenant_id, actor, keys)
        for s in shifts:
            await db.delete(s)
        await db.flush()
        await ScheduleService._after(db, tenant_id, actor, keys)
        return len(shifts)

    @staticmethod
    async def update_date_remark(
        db: AsyncSession,
        tenant_id: UUID,
        remark_id: int,
        data: dict,
        actor: Optional[User] = None,
    ) -> Optional[DateRemark]:
        """Update an existing date remark (PATCH: only keys given).

        The description can be cleared with an explicit null (it used to be
        impossible). Moving, un-marking or deleting a holiday takes back the
        holiday-off shifts it generated that nobody has edited, and makes new
        ones for its new dates when the setting is on. Editing a holiday that
        came from the live feed marks it locally modified, so sync never
        overwrites the edit.

        Raises ValueError if the new date already has a remark.
        """
        remark = (await db.execute(
            select(DateRemark).where(
                DateRemark.id == remark_id,
                DateRemark.tenant_id == tenant_id,
                DateRemark.is_suppressed == False,  # noqa: E712
            )
        )).scalar_one_or_none()
        if not remark:
            return None

        changes = {}
        for key, value in data.items():
            if key not in {"date", "title", "description", "is_holiday", "is_special", "is_recurring"}:
                continue
            if value is None and key != "description":
                continue
            if getattr(remark, key) != value:
                changes[key] = value
        if not changes:
            return remark

        if "date" in changes:
            clash = (await db.execute(
                select(DateRemark).where(
                    DateRemark.tenant_id == tenant_id,
                    DateRemark.date == changes["date"],
                    DateRemark.id != remark.id,
                )
            )).scalar_one_or_none()
            if clash is not None and not clash.is_suppressed:
                raise ValueError(
                    f"{changes['date'].isoformat()} already has a remark "
                    f"(\"{clash.title}\"). Edit or delete it instead."
                )
            if clash is not None:
                await db.delete(clash)  # a tombstone; the admin chose this date
                await db.flush()

        old_gen = ScheduleService._generation_dates(remark)
        old_events = ScheduleService._event_dates(remark) if remark.is_holiday else set()

        for key, value in changes.items():
            setattr(remark, key, value)
        if remark.source == "feed":
            remark.locally_modified = True
            remark.needs_review = False
        await db.flush()

        new_gen = ScheduleService._generation_dates(remark)
        if old_gen != new_gen:
            await ScheduleService.remove_generated_holiday_off(
                db, tenant_id, remark.id, old_gen - new_gen, actor
            )
            await ScheduleService.apply_holiday_off(db, tenant_id, remark, new_gen - old_gen, actor)

        if changes.keys() & {"date", "is_holiday", "is_special", "is_recurring"}:
            new_events = ScheduleService._event_dates(remark) if remark.is_holiday else set()
            await ScheduleService._emit_holiday_changed(db, tenant_id, actor, old_events | new_events)

        await db.refresh(remark)
        return remark

    @staticmethod
    async def delete_date_remark(
        db: AsyncSession,
        tenant_id: UUID,
        remark_id: int,
        actor: Optional[User] = None,
    ) -> bool:
        """Delete a date remark, and the untouched holiday-off shifts it made.

        A holiday that came from the live feed is kept as a tombstone instead
        (not a holiday, not shown anywhere) so the next sync does not add it
        straight back."""
        remark = (await db.execute(
            select(DateRemark).where(
                DateRemark.id == remark_id,
                DateRemark.tenant_id == tenant_id,
                DateRemark.is_suppressed == False,  # noqa: E712
            )
        )).scalar_one_or_none()
        if not remark:
            return False
        events = ScheduleService._event_dates(remark) if remark.is_holiday else set()
        await ScheduleService.remove_generated_holiday_off(db, tenant_id, remark.id, None, actor)
        if remark.source == "feed":
            remark.is_suppressed = True
            remark.is_holiday = False
        else:
            await db.delete(remark)
        await db.flush()
        await ScheduleService._emit_holiday_changed(db, tenant_id, actor, events)
        return True

    @staticmethod
    async def get_holidays(
        db: AsyncSession,
        tenant_id: UUID,
        year: Optional[int] = None,
    ) -> List[dict]:
        """Holidays for a tenant. For a year, every holiday falling in it,
        recurring ones included on that year's date (they used to be listed
        only in the year they were stored); without one, every holiday row."""
        if year:
            from app.services.holiday_calendar import holidays_between

            found = await holidays_between(db, tenant_id, date(year, 1, 1), date(year, 12, 31))
            if not found:
                return []
            rows = {
                r.id: r for r in (await db.execute(
                    select(DateRemark).where(
                        DateRemark.id.in_({h.remark_id for h in found.values()})
                    )
                )).scalars().all()
            }
            return [
                ScheduleService.remark_view(rows[h.remark_id], on_date=d)
                for d, h in sorted(found.items()) if h.remark_id in rows
            ]
        stmt = (
            select(DateRemark)
            .where(
                DateRemark.tenant_id == tenant_id,
                DateRemark.is_holiday == True,  # noqa: E712
                DateRemark.is_suppressed == False,  # noqa: E712
            )
            .order_by(DateRemark.date)
        )
        return [ScheduleService.remark_view(r) for r in (await db.execute(stmt)).scalars().all()]

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
        *,
        end_date: Optional[date] = None,
        force: bool = False,
        skipped: Optional[list] = None,
        actor: Optional[User] = None,
    ) -> List[Shift]:
        """
        Apply a schedule template to a list of employees starting from a
        given date.  The template_data is expected to be a list of day
        entries (index 0 = day 0, etc.), each containing shift details. With
        `end_date` the pattern repeats back-to-back until that date.

        Days that conflict (approved leave, or a guardrail unless `force`) and
        days that already have a shift are skipped rather than written, and
        appended to `skipped` when given -- the same rule a bulk create
        follows. It used to write straight over approved leave and stack a
        second shift onto days that had one.
        """
        stmt = select(ScheduleTemplate).where(
            ScheduleTemplate.id == template_id,
            ScheduleTemplate.tenant_id == tenant_id,
            ScheduleTemplate.is_active == True,  # noqa: E712
        )
        template = (await db.execute(stmt)).scalar_one_or_none()
        if not template:
            return []

        template_data = template.template_data
        # template_data should be a list of day entries, e.g.:
        # [
        #   {"start_time": "08:00", "end_time": "16:00", "status": "scheduled", ...},
        #   {"status": "rest_day"},
        #   ...
        # ]
        if not isinstance(template_data, list) or not template_data:
            return []

        span = len(template_data)
        last = end_date if end_date and end_date >= start_date else start_date + timedelta(days=span - 1)
        category_map = await ScheduleService._get_category_map(db, tenant_id)
        settings = await ScheduleService._load_app_settings(db, tenant_id)

        plan: List[tuple] = []  # (employee_id, date, entry, start, end, status)
        for employee_id in employee_ids:
            placements = []
            d = start_date
            while d <= last:
                entry = template_data[(d - start_date).days % span]
                if entry:
                    status = entry.get("status") or "scheduled"
                    is_work = category_map.get(status, "leave") == "work"
                    # template_data is JSON, so times arrive as "HH:MM" strings.
                    st = ScheduleService._as_time(entry.get("start_time")) if is_work else None
                    et = ScheduleService._as_time(entry.get("end_time")) if is_work else None
                    placements.append((d, entry, st, et, status))
                d += timedelta(days=1)

            existing = await ScheduleService._existing_shift_dates(
                db, tenant_id, employee_id, [p[0] for p in placements]
            )
            conflicts = await ScheduleService.validate_placements(
                db, tenant_id,
                [{"employee_id": employee_id, "date": p[0], "status": p[4],
                  "start_time": p[2], "end_time": p[3]} for p in placements if p[0] not in existing],
                force=force, category_map=category_map, settings=settings,
            )
            blocked = {c["date"] for c in conflicts}
            if skipped is not None:
                skipped.extend(conflicts)
                skipped.extend(
                    {"employee_id": employee_id, "date": d.isoformat(), "type": "existing_shift",
                     "forceable": False, "message": f"A shift already exists on {d.isoformat()}."}
                    for d in sorted(existing)
                )
            plan.extend(
                (employee_id,) + p for p in placements
                if p[0] not in existing and p[0].isoformat() not in blocked
            )

        keys = [(e, d) for e, d, *_ in plan]
        await ScheduleService._before(db, tenant_id, actor, keys)
        created_shifts: List[Shift] = []
        for employee_id, shift_date, entry, st, et, status in plan:
            shift = Shift(
                tenant_id=tenant_id,
                employee_id=employee_id,
                date=shift_date,
                start_time=st,
                end_time=et,
                sequence_number=1,
                status=status,
                work_arrangement=entry.get("work_arrangement"),
                role_name=entry.get("role_name"),
                color=entry.get("color"),
                notes=entry.get("notes"),
                remarks=entry.get("remarks"),
                work_site_id=entry.get("work_site_id"),
                created_by=created_by,
            )
            db.add(shift)
            created_shifts.append(shift)

        await db.flush()
        for shift in created_shifts:
            await db.refresh(shift)
        await ScheduleService._after(db, tenant_id, actor, keys)
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
        *,
        actor: Optional[User] = None,
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

        Every overlaid day is published: it is the consequence of an approved
        decision, and as a draft the employee could not see their own leave.
        The previous publish state is kept in original_is_published for revert.
        """
        from datetime import datetime as _dt

        keys = []
        d = start_date
        while d <= end_date:
            keys.append((employee_id, d))
            d += timedelta(days=1)
        await ScheduleService._before(db, tenant_id, actor, keys)

        now = utcnow()
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
                        shift.original_is_published = bool(shift.is_published)
                    shift.status = leave_type
                    shift.start_time = None
                    shift.end_time = None
                    shift.leave_application_id = leave_application_id
                    if not shift.is_published:
                        shift.is_published = True
                        shift.published_at = now
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
                    is_published=True,
                    published_at=now,
                )
                db.add(new_shift)

            current += timedelta(days=1)

        await db.flush()
        await ScheduleService._after(db, tenant_id, actor, keys)
        return conflicts

    @staticmethod
    async def revert_leave_overlay(
        db: AsyncSession,
        tenant_id: UUID,
        leave_application_id: int,
        *,
        actor: Optional[User] = None,
    ) -> Dict[str, int]:
        """Undo `overlay_leave_on_shifts` for one leave application.

        The overlay did one of two things to each date, and which one is
        recoverable from the row itself:

        * It **modified** an existing shift, first snapshotting the previous
          values into `original_status` / `original_start_time` /
          `original_end_time`. Those rows are restored and the snapshot cleared.
        * It **created** a shift where the employee had none. Those rows carry no
          snapshot (`original_status IS NULL`) and are deleted — "restoring" them
          would invent a working shift that never existed.

        Then, on the days freed, any OTHER leave of the same employee that is
        still approved is re-applied. When two approved leaves overlapped, the
        first-approved one held the shared days; reverting it used to leave
        those days as plain work although the second leave still stands.

        Leave balances need no adjustment: `LeaveService` derives used/pending
        days by summing applications by status, so moving the application out of
        "approved" releases the days by itself.
        """
        stmt = select(Shift).where(
            Shift.tenant_id == tenant_id,
            Shift.leave_application_id == leave_application_id,
        )
        result = await db.execute(stmt)
        shifts = list(result.scalars().all())
        if not shifts:
            return {"restored": 0, "deleted": 0, "reapplied": 0}

        keys = [(s.employee_id, s.date) for s in shifts]
        await ScheduleService._before(db, tenant_id, actor, keys)

        restored = 0
        deleted = 0
        for shift in shifts:
            if shift.original_status is not None:
                shift.status = shift.original_status
                shift.start_time = shift.original_start_time
                shift.end_time = shift.original_end_time
                if shift.original_is_published is not None:
                    shift.is_published = shift.original_is_published
                    if not shift.is_published:
                        shift.published_at = None
                        shift.published_by = None
                shift.original_status = None
                shift.original_start_time = None
                shift.original_end_time = None
                shift.original_is_published = None
                shift.leave_application_id = None
                restored += 1
            else:
                await db.delete(shift)
                deleted += 1

        await db.flush()
        await ScheduleService._after(db, tenant_id, actor, keys)

        # Re-apply other approved leave on the freed days.
        reapplied = 0
        by_emp: Dict[int, set] = defaultdict(set)
        for emp_id, d in keys:
            by_emp[emp_id].add(d)
        for emp_id, days in by_emp.items():
            lo, hi = min(days), max(days)
            others = (await db.execute(
                select(LeaveApplication).where(
                    LeaveApplication.tenant_id == tenant_id,
                    LeaveApplication.employee_id == emp_id,
                    LeaveApplication.status == "approved",
                    LeaveApplication.id != leave_application_id,
                    LeaveApplication.start_date <= hi,
                    LeaveApplication.end_date >= lo,
                ).order_by(LeaveApplication.reviewed_at, LeaveApplication.id)
            )).scalars().all()
            for other in others:
                s = max(other.start_date, lo)
                e = min(other.end_date, hi)
                if s > e:
                    continue
                await ScheduleService.overlay_leave_on_shifts(
                    db, tenant_id, emp_id, other.id, other.leave_type, s, e, actor=actor,
                )
                reapplied += 1

        return {"restored": restored, "deleted": deleted, "reapplied": reapplied}

    # ── CSV Export ──────────────────────────────────────────────────────

    @staticmethod
    async def export_shifts_csv(
        db: AsyncSession,
        tenant_id: UUID,
        start_date: date,
        end_date: date,
        employee_ids: Optional[List[int]] = None,
    ) -> str:
        """
        Export the shifts of `employee_ids` (None = everyone) in a date range
        as a CSV string. Columns: Employee, Date, Start Time, End Time, Status,
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
        if employee_ids is not None:
            stmt = stmt.where(Shift.employee_id.in_(employee_ids or [-1]))
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
        employee_ids: Optional[List[int]],
        *,
        include_leave: bool = False,
        dry_run: bool = False,
        actor: Optional[User] = None,
    ) -> dict:
        """Delete the listed employees' shifts in a date range.

        `employee_ids` is the exact set to clear: an empty list clears nothing,
        and None (every employee) is only reachable from code that has already
        decided the caller manages everyone. Shifts that belong to an approved
        leave are kept unless `include_leave`, because deleting one undoes a
        leave decision that still stands. With `dry_run` nothing is deleted and
        the counts describe what would be.

        Returns {deleted_count, leave_kept_count, employee_count,
        published_removed: {employee_id: [dates]}} -- the last so the caller
        can tell employees about shifts they could already see.
        """
        empty = {
            "deleted_count": 0, "leave_kept_count": 0, "employee_count": 0,
            "dry_run": dry_run, "published_removed": {},
        }
        if employee_ids is not None and not employee_ids:
            return empty

        stmt = select(Shift).where(
            Shift.tenant_id == tenant_id,
            Shift.date >= start_date,
            Shift.date <= end_date,
        )
        if employee_ids is not None:
            stmt = stmt.where(Shift.employee_id.in_(employee_ids))
        rows = list((await db.execute(stmt)).scalars().all())

        doomed = [s for s in rows if include_leave or s.leave_application_id is None]
        kept = len(rows) - len(doomed)
        published_removed: Dict[int, list] = defaultdict(list)
        for s in doomed:
            if s.is_published:
                published_removed[s.employee_id].append(s.date)
        result = {
            "deleted_count": len(doomed),
            "leave_kept_count": kept,
            "employee_count": len({s.employee_id for s in doomed}),
            "dry_run": dry_run,
            "published_removed": dict(published_removed),
        }
        if dry_run or not doomed:
            return result

        keys = [(s.employee_id, s.date) for s in doomed]
        await ScheduleService._before(db, tenant_id, actor, keys)
        for s in doomed:
            await db.delete(s)
        await db.flush()
        await ScheduleService._after(db, tenant_id, actor, keys)
        return result

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
        employee_ids: Optional[List[int]] = None,
    ) -> ScheduleSnapshot:
        """Capture the listed employees' shifts in a date range as a reusable
        snapshot (None = every employee, [] = nobody)."""
        shift_stmt = (
            select(Shift)
            .where(
                Shift.tenant_id == tenant_id,
                Shift.date >= start_date,
                Shift.date <= end_date,
            )
            .order_by(Shift.employee_id, Shift.date, Shift.sequence_number)
        )
        if employee_ids is not None:
            shift_stmt = shift_stmt.where(Shift.employee_id.in_(employee_ids or [-1]))
        # Approved-leave days are that person's leave, not a pattern to repeat.
        shift_stmt = shift_stmt.where(Shift.leave_application_id.is_(None))
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
                    "work_site_id": s.work_site_id,
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

        A 7-day (week) snapshot strides every 7 days so copies are back-to-back.
        A month snapshot does not use this for repeats (see _snapshot_targets);
        it is still reported as the captured length. Always >= 1."""
        span = (snapshot.source_end_date - snapshot.source_start_date).days + 1
        return max(span, 1)

    @staticmethod
    def _add_months(d: date, months: int) -> date:
        """Same day-of-month `months` later, clamped to the month's last day."""
        import calendar

        y, m = divmod(d.month - 1 + months, 12)
        year, month = d.year + y, m + 1
        return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))

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
        is produced (single apply — back-compat).

        A MONTH snapshot repeats by calendar month: each copy starts on the same
        day of the next month, and days the shorter month does not have are
        dropped. It used to stride by the captured length, so a 31-day January
        repeated as Feb 1, Mar 4, Apr 4... drifting further every month."""
        data = snapshot.snapshot_data
        if not isinstance(data, list):
            return [], []

        monthly = snapshot.range_type == "month"
        stride = ScheduleService._snapshot_span_days(snapshot)

        def occ_start(k: int) -> date:
            if monthly:
                return ScheduleService._add_months(target_start_date, k)
            return target_start_date + timedelta(days=k * stride)

        occ_starts: List[date] = [target_start_date]
        if repeat_until and repeat_until >= target_start_date:
            k = 1
            while True:
                start = occ_start(k)
                if start > repeat_until:
                    break
                occ_starts.append(start)
                k += 1

        occurrences: List[dict] = []
        targets: list = []
        for idx, start in enumerate(occ_starts):
            end = occ_start(idx + 1) - timedelta(days=1) if monthly else start + timedelta(days=stride - 1)
            occurrences.append({"index": idx, "start_date": start, "end_date": end})
            for emp_entry in data:
                emp_id = emp_entry.get("employee_id")
                if not emp_id:
                    continue
                if employee_ids is not None and emp_id not in employee_ids:
                    continue
                for shift_entry in emp_entry.get("shifts", []):
                    shift_date = start + timedelta(days=shift_entry.get("day_offset", 0))
                    if shift_date > end:
                        continue  # e.g. the 31st copied into a 30-day month
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
            (consecutive-days / rest-days / hours) — the user chooses skip vs
            overwrite.
        """
        snapshot = await ScheduleService._load_snapshot(db, tenant_id, snapshot_id)
        if not snapshot:
            return None

        occurrences, targets = ScheduleService._snapshot_targets(
            snapshot, target_start_date, repeat_until, employee_ids
        )
        report = await ScheduleService._preview_targets(db, tenant_id, targets)
        report.update({
            "occurrences": occurrences,
            "stride_days": ScheduleService._snapshot_span_days(snapshot),
            "total_shifts": len(targets),
        })
        return report

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
        actor: Optional[User] = None,
    ) -> dict:
        """Apply a snapshot to one target date, optionally repeating it forward
        (contiguously, or by calendar month for a month snapshot) until
        ``repeat_until``.

        Conflict handling per ``on_conflict``:
          - Approved-leave dates are ALWAYS skipped (never scheduled over).
          - 'skip': dates with an existing shift or a guardrail breach are skipped.
          - 'overwrite': existing shifts on those dates are deleted and replaced;
            forceable guardrail breaches are forced through.

        Returns ``{created, skipped, overwritten, published_removed}``."""
        snapshot = await ScheduleService._load_snapshot(db, tenant_id, snapshot_id)
        if not snapshot:
            return {"created": 0, "skipped": [], "overwritten": 0, "published_removed": {}}

        _, targets = ScheduleService._snapshot_targets(
            snapshot, target_start_date, repeat_until, employee_ids
        )
        # Same path as copy-week, so both honour leave and guardrails alike.
        return await ScheduleService._apply_targets(
            db, tenant_id, targets, on_conflict=on_conflict,
            created_by=created_by, actor=actor,
        )

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
        preview/apply logic is identical. Approved-leave days are not copied:
        they are that person's leave, not next week's plan."""
        stride = (source_end - source_start).days + 1
        stride = max(stride, 1)

        stmt = select(Shift).where(
            Shift.tenant_id == tenant_id,
            Shift.date >= source_start,
            Shift.date <= source_end,
            Shift.leave_application_id.is_(None),
        )
        if employee_ids is not None:
            stmt = stmt.where(Shift.employee_id.in_(employee_ids or [-1]))
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
                "work_site_id": s.work_site_id,
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
        actor: Optional[User] = None,
    ) -> dict:
        """Copy the shifts in [source_start, source_end] to a window starting at
        target_start. Approved-leave dates are always skipped; existing shifts /
        guardrail breaches are skipped or overwritten per on_conflict. Returns
        {created, overwritten, skipped, published_removed}."""
        _, targets = await ScheduleService._week_copy_targets(
            db, tenant_id, source_start, source_end, target_start, employee_ids
        )
        return await ScheduleService._apply_targets(
            db, tenant_id, targets, on_conflict=on_conflict,
            created_by=created_by, actor=actor,
        )

    # ── Shared target preview/apply (snapshots and copy-week) ────────────

    @staticmethod
    def _target_placement(emp_id: int, shift_date: date, entry: dict, category_map) -> dict:
        status = entry.get("status") or "scheduled"
        is_work = category_map.get(status, "leave") == "work"
        return {
            "employee_id": emp_id,
            "date": shift_date,
            "status": status,
            "start_time": ScheduleService._as_time(entry.get("start_time")) if is_work else None,
            "end_time": ScheduleService._as_time(entry.get("end_time")) if is_work else None,
        }

    @staticmethod
    async def _existing_by_date(db, tenant_id, emp_id, dates) -> Dict[date, list]:
        if not dates:
            return {}
        rows = (await db.execute(
            select(Shift).where(
                Shift.tenant_id == tenant_id,
                Shift.employee_id == emp_id,
                Shift.date.in_(list(dates)),
            )
        )).scalars().all()
        out: Dict[date, list] = defaultdict(list)
        for r in rows:
            out[r.date].append(r)
        return out

    @staticmethod
    async def _preview_targets(
        db: AsyncSession, tenant_id: UUID, targets: list
    ) -> dict:
        """Split a target list into blocking (approved leave) vs resolvable
        (existing shift / guardrail) conflicts, plus a create_count. No writes."""
        category_map = await ScheduleService._get_category_map(db, tenant_id)
        settings = await ScheduleService._load_app_settings(db, tenant_id)
        by_emp: Dict[int, list] = defaultdict(list)
        for emp_id, shift_date, entry in targets:
            by_emp[emp_id].append((shift_date, entry))

        names: Dict[int, str] = {}
        if by_emp:
            rows = await db.execute(
                select(User.id, User.first_name, User.last_name).where(User.id.in_(list(by_emp)))
            )
            for uid, fn, ln in rows.all():
                names[uid] = f"{fn} {ln}"

        blocking: List[dict] = []
        resolvable: List[dict] = []
        for emp_id, items in by_emp.items():
            existing = await ScheduleService._existing_by_date(
                db, tenant_id, emp_id, {d for d, _ in items}
            )
            leave_locked = {d for d, rows in existing.items() if any(r.leave_application_id for r in rows)}
            conflicts = await ScheduleService.validate_placements(
                db, tenant_id,
                [ScheduleService._target_placement(emp_id, d, e, category_map) for d, e in items],
                category_map=category_map, settings=settings,
            )
            for d in sorted(leave_locked):
                conflicts.append({
                    "employee_id": emp_id, "date": d.isoformat(), "type": "approved_leave",
                    "forceable": False,
                    "message": f"Employee is on approved leave on {d.isoformat()}.",
                })
            leave_dates: set = set()
            for c in conflicts:
                row = {
                    "employee_id": emp_id,
                    "employee_name": names.get(emp_id, str(emp_id)),
                    "date": c["date"],
                    "type": c["type"],
                    "forceable": c["forceable"],
                    "message": c["message"],
                    "has_existing_shift": date.fromisoformat(c["date"]) in existing,
                }
                if c["type"] == "approved_leave":
                    if c["date"] in leave_dates:
                        continue
                    leave_dates.add(c["date"])
                    blocking.append(row)
                else:
                    resolvable.append(row)

            for d in sorted(existing):
                if d.isoformat() not in leave_dates:
                    resolvable.append({
                        "employee_id": emp_id,
                        "employee_name": names.get(emp_id, str(emp_id)),
                        "date": d.isoformat(),
                        "type": "existing_shift",
                        "forceable": True,
                        "message": f"A shift already exists on {d.isoformat()}.",
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
        actor: Optional[User] = None,
    ) -> dict:
        """Create shifts for a target list. Approved-leave always skipped;
        existing/guardrail skipped or overwritten per on_conflict. A shift
        that belongs to an approved leave is never overwritten, whatever the
        copied status: overwriting it with a rest day used to delete the leave
        day while the leave itself stayed approved.

        Validation is per employee over all their targets at once, so a run
        of copied days is judged as the schedule it will become."""
        category_map = await ScheduleService._get_category_map(db, tenant_id)
        settings = await ScheduleService._load_app_settings(db, tenant_id)
        force = on_conflict == "overwrite"
        skipped: List[dict] = []
        published_removed: Dict[int, list] = defaultdict(list)

        by_emp: Dict[int, list] = defaultdict(list)
        for emp_id, shift_date, entry in targets:
            by_emp[emp_id].append((shift_date, entry))

        plan: List[tuple] = []      # (emp_id, date, entry, placement)
        doomed: List[Shift] = []    # existing shifts being overwritten
        overwritten_dates: set = set()

        def skip(emp_id, d, reason, message):
            skipped.append({
                "employee_id": emp_id, "date": d.isoformat() if isinstance(d, date) else d,
                "reason": reason, "message": message,
            })

        for emp_id, items in by_emp.items():
            existing = await ScheduleService._existing_by_date(
                db, tenant_id, emp_id, {d for d, _ in items}
            )
            candidates = []
            for d, entry in items:
                rows = existing.get(d, [])
                if any(r.leave_application_id is not None for r in rows):
                    skip(emp_id, d, "approved_leave", f"Employee is on approved leave on {d.isoformat()}.")
                    continue
                if rows and not force:
                    skip(emp_id, d, "existing_shift", f"A shift already exists on {d.isoformat()}.")
                    continue
                candidates.append((d, entry))

            replace_ids = {r.id for d, _ in candidates for r in existing.get(d, [])}
            conflicts = await ScheduleService.validate_placements(
                db, tenant_id,
                [ScheduleService._target_placement(emp_id, d, e, category_map) for d, e in candidates],
                force=force, ignore_shift_ids=replace_ids,
                category_map=category_map, settings=settings,
            )
            blocked: Dict[str, dict] = {}
            for c in conflicts:
                blocked.setdefault(c["date"], c)
            for d, entry in candidates:
                c = blocked.get(d.isoformat())
                if c:
                    skip(emp_id, d, c["type"], c["message"])
                    continue
                plan.append((emp_id, d, entry))
                for r in existing.get(d, []):
                    if r not in doomed:
                        doomed.append(r)
                        overwritten_dates.add((emp_id, d))
                        if r.is_published:
                            published_removed[emp_id].append(d)

        keys = [(e, d) for e, d, _ in plan]
        await ScheduleService._before(db, tenant_id, actor, keys)
        for r in doomed:
            await db.delete(r)
        if doomed:
            await db.flush()

        seq_next: Dict[tuple, int] = {}
        for emp_id, shift_date, entry in plan:
            p = ScheduleService._target_placement(emp_id, shift_date, entry, category_map)
            k = (emp_id, shift_date)
            if k not in seq_next:
                seq_next[k] = await ScheduleService._next_sequence_number(db, tenant_id, emp_id, shift_date)
            db.add(Shift(
                tenant_id=tenant_id,
                employee_id=emp_id,
                date=shift_date,
                start_time=p["start_time"],
                end_time=p["end_time"],
                sequence_number=seq_next[k],
                status=p["status"],
                work_arrangement=entry.get("work_arrangement"),
                role_name=entry.get("role_name"),
                color=entry.get("color"),
                notes=entry.get("notes"),
                remarks=entry.get("remarks"),
                work_site_id=entry.get("work_site_id"),
                created_by=created_by,
            ))
            seq_next[k] += 1
        await db.flush()
        await ScheduleService._after(db, tenant_id, actor, keys)

        return {
            "created": len(plan), "skipped": skipped, "overwritten": len(overwritten_dates),
            "published_removed": {e: sorted(set(ds)) for e, ds in published_removed.items()},
        }

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
          - approved_leave: a WORK shift sits on an approved-leave day;
          - holiday: a WORK shift sits on a holiday. Advisory only — plenty of
            organisations legitimately operate on holidays, and holiday work is
            paid at a premium rather than forbidden. The point is that the
            scheduler should not do it without noticing.
        Returns [{employee_id, date, type, message}]."""
        settings = (await db.execute(
            select(AppSettings).where(AppSettings.tenant_id == tenant_id)
        )).scalar_one_or_none()
        max_consec = getattr(settings, "max_consecutive_work_days", 0) or 0
        min_rest = getattr(settings, "min_rest_days_per_week", 0) or 0

        category_map = await ScheduleService._get_category_map(db, tenant_id)

        # Holidays in range, loaded once for all employees rather than per
        # employee. is_special is carried through because the two kinds pay at
        # different multipliers (see AppSettings.holiday_worked_multiplier vs
        # special_holiday_worked_multiplier), so the message names which it is.
        # Recurring holidays count (they used to be missed here).
        from app.services.holiday_calendar import holidays_between

        holidays = {
            d: (h.title, h.is_special)
            for d, h in (await holidays_between(db, tenant_id, start_date, end_date)).items()
        }

        # Pad the window so runs that straddle the range edges are counted.
        window_start = start_date - timedelta(days=7)
        window_end = end_date + timedelta(days=7)

        if employee_ids is not None and not employee_ids:
            return []
        stmt = select(
            Shift.id, Shift.employee_id, Shift.date, Shift.status, Shift.start_time, Shift.end_time,
        ).where(
            Shift.tenant_id == tenant_id,
            Shift.date >= window_start,
            Shift.date <= window_end,
        )
        if employee_ids is not None:
            stmt = stmt.where(Shift.employee_id.in_(employee_ids))
        rows = (await db.execute(stmt)).all()

        work_days_by_emp: Dict[int, set] = defaultdict(set)
        in_range_by_emp: Dict[int, list] = defaultdict(list)
        for r in rows:
            if category_map.get(r.status, "leave") == "work":
                work_days_by_emp[r.employee_id].add(r.date)
                if start_date <= r.date <= end_date:
                    in_range_by_emp[r.employee_id].append(r)

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
                if d in holidays:
                    title, is_special = holidays[d]
                    kind = "special (non-working)" if is_special else "regular"
                    violations.append({
                        "employee_id": emp_id,
                        "date": d.isoformat(),
                        "type": "holiday",
                        "message": (
                            f"Work shift on a {kind} holiday ({title}). "
                            "Hours are paid at the holiday premium."
                        ),
                    })

            # The hour rules, from the same validator the write paths use:
            # the range's own shifts are replayed as placements over the rest.
            if any(getattr(settings, k, 0) for k in (
                "max_work_hours_per_day", "max_work_hours_per_week",
                "min_rest_hours_between_shifts", "check_overlapping_shifts",
            )):
                mine = in_range_by_emp.get(emp_id, [])
                hour_flags = await ScheduleService.validate_placements(
                    db, tenant_id,
                    [{"employee_id": emp_id, "date": r.date, "status": r.status,
                      "start_time": r.start_time, "end_time": r.end_time} for r in mine],
                    ignore_shift_ids={r.id for r in mine},
                    category_map=category_map, settings=settings,
                )
                for c in hour_flags:
                    if c["type"] in _HOUR_RULE_TYPES:
                        violations.append({
                            "employee_id": emp_id, "date": c["date"],
                            "type": c["type"], "message": c["message"],
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
        *,
        dry_run: bool = False,
        actor: Optional[User] = None,
    ) -> dict:
        """Publish (release) the DRAFT shifts in [start_date, end_date] for the
        given employees. Returns {published_count, employee_ids} where the id
        list is the DISTINCT employees who had something published (for
        notifications). An empty `employee_ids` publishes nothing; None means
        every employee and is for callers that already checked scope."""
        from datetime import datetime as _dt

        if employee_ids is not None and not employee_ids:
            return {"published_count": 0, "employee_ids": []}
        stmt = select(Shift).where(
            Shift.tenant_id == tenant_id,
            Shift.date >= start_date,
            Shift.date <= end_date,
            Shift.is_published == False,  # noqa: E712
        )
        if employee_ids is not None:
            stmt = stmt.where(Shift.employee_id.in_(employee_ids))
        shifts = (await db.execute(stmt)).scalars().all()

        affected = sorted({s.employee_id for s in shifts})
        if dry_run:
            return {"published_count": len(shifts), "employee_ids": affected}
        # Publishing changes what counts as the real schedule (drafts are not
        # clocked against or paid), so it is a shift write like any other.
        keys = [(s.employee_id, s.date) for s in shifts]
        await ScheduleService._before(db, tenant_id, actor, keys)
        now = utcnow()
        for s in shifts:
            s.is_published = True
            s.published_at = now
            s.published_by = published_by
        await db.flush()
        await ScheduleService._after(db, tenant_id, actor, keys)
        return {"published_count": len(shifts), "employee_ids": affected}

    @staticmethod
    async def unpublish_range(
        db: AsyncSession,
        tenant_id: UUID,
        start_date: date,
        end_date: date,
        employee_ids: Optional[List[int]],
        *,
        dry_run: bool = False,
        actor: Optional[User] = None,
    ) -> dict:
        """Return published shifts in the range to DRAFT (hidden from employees)
        so they can be reworked. Returns {unpublished_count, employee_ids}.

        Shifts that belong to an approved leave stay published: they are the
        consequence of a decision already made and announced, not part of the
        plan being reworked."""
        if employee_ids is not None and not employee_ids:
            return {"unpublished_count": 0, "employee_ids": []}
        stmt = select(Shift).where(
            Shift.tenant_id == tenant_id,
            Shift.date >= start_date,
            Shift.date <= end_date,
            Shift.is_published == True,  # noqa: E712
            Shift.leave_application_id.is_(None),
        )
        if employee_ids is not None:
            stmt = stmt.where(Shift.employee_id.in_(employee_ids))
        shifts = (await db.execute(stmt)).scalars().all()
        affected = sorted({s.employee_id for s in shifts})
        if dry_run:
            return {"unpublished_count": len(shifts), "employee_ids": affected}
        keys = [(s.employee_id, s.date) for s in shifts]
        await ScheduleService._before(db, tenant_id, actor, keys)
        for s in shifts:
            s.is_published = False
            s.published_at = None
            s.published_by = None
        await db.flush()
        await ScheduleService._after(db, tenant_id, actor, keys)
        return {"unpublished_count": len(shifts), "employee_ids": affected}
