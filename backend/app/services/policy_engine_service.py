"""
Policy Engine Service

Evaluates policy rules against an attendance context and executes matching actions.
Rules are evaluated per rule_type in priority order. For each rule_type,
the first matching rule's actions are executed (stop-on-first-match per type).
"""

import math
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Optional, Set
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attendance import AttendanceRecord, OvertimeLog, TardinessRecord, LeaveCreditAdjustment
from app.models.leave import OvertimeCategory
from app.models.policy import PolicyRule


OPERATORS = {
    "eq": lambda a, b: a == b,
    "neq": lambda a, b: a != b,
    "gt": lambda a, b: a > b,
    "gte": lambda a, b: a >= b,
    "lt": lambda a, b: a < b,
    "lte": lambda a, b: a <= b,
    "in": lambda a, b: a in b,
    "not_in": lambda a, b: a not in b,
}

# Canonical grammar the engine actually understands. Rule validation (create/
# update) checks conditions/actions against these so a rule that could never fire
# (unknown field/operator/action) is rejected at save time instead of silently
# no-op'ing at runtime. These are the single source of truth — the UI builder and
# the validator must stay in sync with them.
CONDITION_FIELDS = frozenset({
    "schedule_format", "overtime_minutes", "tardiness_minutes", "undertime_minutes",
    "is_holiday", "is_special", "day_of_week", "employee_type", "shift_hours",
    "hours_worked", "status",
    # Stateful aggregates (computed at evaluation from the employee's history).
    "late_count_month", "late_count_week", "absent_count_month",
})
ACTION_TYPES = frozenset({
    "apply_ot_category", "apply_night_diff", "apply_holiday_pay",
    "salary_deduction", "leave_deduction", "send_warning", "mark_excused",
})


def _time_to_min(t: time) -> int:
    """Convert a time to minutes since midnight."""
    return t.hour * 60 + t.minute


def compute_night_minutes(
    actual_start: time,
    actual_end: time,
    night_start_hour: int,
    night_end_hour: int,
) -> int:
    """
    Compute the number of minutes of overlap between a work period and
    a night window (e.g., 22:00–06:00).  Handles overnight shifts.
    Returns 0 if either time is None.
    """
    if not actual_start or not actual_end:
        return 0

    ws = _time_to_min(actual_start)
    we = _time_to_min(actual_end)
    # Handle overnight work shifts
    if we <= ws:
        we += 24 * 60

    ns = night_start_hour * 60
    ne = night_end_hour * 60
    # Night window crosses midnight (e.g. 22:00–06:00)
    if ne <= ns:
        ne += 24 * 60

    # The night window may repeat, e.g. for a shift from 06:00–22:00
    # we need to check two possible windows: [ns, ne] and [ns-1440, ne-1440]
    total = 0
    for offset in (0, -24 * 60, 24 * 60):
        w_ns = ns + offset
        w_ne = ne + offset
        overlap_start = max(ws, w_ns)
        overlap_end = min(we, w_ne)
        if overlap_end > overlap_start:
            total += overlap_end - overlap_start

    return total


def compute_holiday_minutes(
    actual_start: time,
    actual_end: time,
    attendance_date: date,
    holiday_dates: Set[date],
) -> int:
    """
    Compute the number of minutes of a work shift that fall on holiday dates.
    Handles overnight shifts by splitting at midnight.

    Example: shift 22:00 Jan 1 -> 06:00 Jan 2
      - If Jan 1 is holiday: returns 120 (22:00-00:00 = 2 hours)
      - If Jan 2 is holiday: returns 360 (00:00-06:00 = 6 hours)
      - If both: returns 480 (full 8 hours)
    """
    if not actual_start or not actual_end or not holiday_dates:
        return 0

    start_dt = datetime.combine(attendance_date, actual_start)
    end_dt = datetime.combine(attendance_date, actual_end)
    # Handle overnight shift
    if end_dt <= start_dt:
        end_dt += timedelta(days=1)

    total_holiday_mins = 0

    # Iterate each calendar day the shift spans
    current_date = attendance_date
    while current_date <= end_dt.date():
        if current_date in holiday_dates:
            day_start = datetime.combine(current_date, time(0, 0))
            day_end = datetime.combine(current_date + timedelta(days=1), time(0, 0))
            overlap_start = max(start_dt, day_start)
            overlap_end = min(end_dt, day_end)
            if overlap_end > overlap_start:
                total_holiday_mins += int((overlap_end - overlap_start).total_seconds() / 60)
        current_date += timedelta(days=1)

    return total_holiday_mins


class PolicyEngineService:

    @staticmethod
    def build_context(
        attendance: AttendanceRecord,
        schedule_format: Optional[str],
        employee_type: Optional[str],
        is_holiday: bool,
        is_special: bool,
        shift_hours: Optional[float],
        actual_start_time: Optional[time] = None,
        actual_end_time: Optional[time] = None,
        holiday_dates: Optional[Set[date]] = None,
        attendance_date: Optional[date] = None,
    ) -> Dict[str, Any]:
        """Build evaluation context dict from attendance record and metadata."""
        return {
            "schedule_format": schedule_format,
            "overtime_minutes": attendance.overtime_minutes,
            "tardiness_minutes": attendance.tardiness_minutes,
            "undertime_minutes": attendance.undertime_minutes,
            "is_holiday": is_holiday,
            "is_special": is_special,
            "day_of_week": attendance.date.isoweekday(),  # 1=Mon, 7=Sun
            "employee_type": employee_type,
            "shift_hours": shift_hours,
            "hours_worked": attendance.hours_worked or 0,
            "status": attendance.status,
            "actual_start_time": actual_start_time,
            "actual_end_time": actual_end_time,
            "holiday_dates": holiday_dates or set(),
            "attendance_date": attendance_date or attendance.date,
        }

    @staticmethod
    def _eval_leaf(cond: Dict, context: Dict[str, Any]) -> bool:
        """Evaluate a single {field, operator, value} leaf. A missing context
        field or unknown operator is a non-match (never raises)."""
        actual = context.get(cond.get("field"))
        if actual is None:
            return False
        op_fn = OPERATORS.get(cond.get("operator"))
        if not op_fn:
            return False
        try:
            return bool(op_fn(actual, cond.get("value")))
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _eval_node(node: Any, context: Dict[str, Any]) -> bool:
        """Recursively evaluate a condition node:
          - leaf:      {"field","operator","value"}
          - ALL group: {"all": [node, ...]}  (AND — all children match)
          - ANY group: {"any": [node, ...]}  (OR — at least one matches)
          - NOT group: {"not": node}         (negation)
        Empty ALL/leaf-less nodes are non-matching so a rule can't fire on nothing.
        """
        if not isinstance(node, dict):
            return False
        if "all" in node:
            children = node.get("all") or []
            return bool(children) and all(
                PolicyEngineService._eval_node(c, context) for c in children
            )
        if "any" in node:
            children = node.get("any") or []
            return any(PolicyEngineService._eval_node(c, context) for c in children)
        if "not" in node:
            return not PolicyEngineService._eval_node(node.get("not"), context)
        return PolicyEngineService._eval_leaf(node, context)

    @staticmethod
    def evaluate_conditions(conditions: Any, context: Dict[str, Any]) -> bool:
        """Evaluate a rule's conditions against the context.

        Backward-compatible: a flat list ``[{field,operator,value}, ...]`` is
        treated as one ALL (AND) group — the historical behavior — while a group
        dict ``{"all"|"any"|"not": ...}`` is evaluated as a nested tree. An empty
        condition set never matches."""
        if not conditions:
            return False
        if isinstance(conditions, list):
            return PolicyEngineService._eval_node({"all": conditions}, context)
        return PolicyEngineService._eval_node(conditions, context)

    # Each action maps to one "effect slot". At most one action per slot is
    # applied per attendance record, so overlapping rules can't create duplicate
    # OT logs / tardiness rows. The FIRST matching rule (by priority) to request a
    # slot wins that slot; later rules requesting the same slot are ignored, but
    # rules requesting OTHER slots still apply. This replaces the old
    # first-match-per-rule_type behavior that silently shadowed unrelated rules
    # (e.g. a tardiness rule dropped because an overtime rule of the same
    # rule_type matched first).
    _ACTION_SLOT = {
        "apply_ot_category": "overtime",
        "apply_night_diff": "night_diff",
        "apply_holiday_pay": "holiday_pay",
        "salary_deduction": "attendance_resolution",
        "leave_deduction": "attendance_resolution",
        "send_warning": "attendance_resolution",
        "mark_excused": "attendance_resolution",
    }

    @staticmethod
    def _resolve_action(action: Dict, context: Dict[str, Any]) -> Optional[Dict]:
        """Resolve an action to the concrete action that should run.

        A plain action returns itself. A **banded** action
        ``{"type":"bands","field":F,"bands":[{"min","max","action":{...}}, ...]}``
        picks the first band whose ``[min, max]`` (either bound optional/inclusive)
        contains the context value of ``F`` and returns that band's inner action.
        Returns None when no band matches (no effect) or the field is missing."""
        if action.get("type") != "bands":
            return action
        value = context.get(action.get("field"))
        if value is None:
            return None
        for band in action.get("bands") or []:
            lo = band.get("min")
            hi = band.get("max")
            try:
                if lo is not None and value < lo:
                    continue
                if hi is not None and value > hi:
                    continue
            except TypeError:
                continue
            inner = band.get("action")
            if isinstance(inner, dict) and inner.get("type"):
                return inner
        return None

    @staticmethod
    async def evaluate(
        db: AsyncSession,
        attendance: AttendanceRecord,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Evaluate all active policy rules for the tenant against the attendance
        context and apply their actions.

        Semantics:
          - ALL matching rules are considered, in priority order (ties by id).
          - Each action fills an "effect slot" (overtime / night_diff /
            holiday_pay / attendance_resolution). A slot is filled at most once,
            by the first matching rule that requests it — so a tardy + overtime
            shift now triggers BOTH the overtime and the resolution, instead of
            the overtime rule shadowing the tardiness rule.
          - A rule may set ``stop_processing: true`` to halt evaluation after it
            matches (firewall-style terminal rule).

        Returns dict with created records.
        """
        results: Dict[str, Any] = {
            "overtime_log": None,
            "tardiness_record": None,
        }

        # Enrich the context with DB-derived facts shared by every rule:
        #  - the employee's org-node ancestor-chain (for org-node scoping), and
        #  - month/week offence counters (for 'Nth offense' stateful conditions).
        # Computed once here so record/update/simulate all get identical behavior.
        context = await PolicyEngineService._enrich_context(db, attendance, context)

        stmt = (
            select(PolicyRule)
            .where(
                PolicyRule.tenant_id == attendance.tenant_id,
                PolicyRule.is_active == True,  # noqa: E712
            )
            .order_by(PolicyRule.priority.asc(), PolicyRule.id.asc())
        )
        result = await db.execute(stmt)
        rules = list(result.scalars().all())

        filled_slots: set = set()

        for rule in rules:
            if not PolicyEngineService._rule_applies(rule, context):
                continue
            if not rule.conditions or not PolicyEngineService.evaluate_conditions(
                rule.conditions, context
            ):
                continue

            matched = False
            for action in rule.actions:
                # Resolve range-bands to the concrete action; None = no band hit.
                resolved = PolicyEngineService._resolve_action(action, context)
                if not resolved:
                    continue
                action_type = resolved.get("type")
                slot = PolicyEngineService._ACTION_SLOT.get(action_type)
                # Unknown action or its slot already filled by an earlier rule.
                if slot is None or slot in filled_slots:
                    continue

                applied = await PolicyEngineService._apply_action(
                    db, attendance, resolved, action_type, rule, context, results
                )
                if applied:
                    filled_slots.add(slot)
                    matched = True

            # Terminal rule (firewall-style): a matched rule can halt further
            # evaluation via a stop_processing flag on the rule's actions.
            if matched and any(a.get("stop_processing") for a in rule.actions):
                break

        return results

    @staticmethod
    def _rule_applies(rule: PolicyRule, context: Dict[str, Any]) -> bool:
        """Scope gate applied before conditions: employment type, effective-date
        window, and org-node scope. Missing scope = applies to everyone/always."""
        # Employment type.
        if rule.employment_types:
            if context.get("employee_type") not in rule.employment_types:
                return False
        # Effective-date window (inclusive; nulls = open-ended).
        att_date = context.get("attendance_date")
        eff_from = getattr(rule, "effective_from", None)
        eff_until = getattr(rule, "effective_until", None)
        if att_date is not None:
            if eff_from is not None and att_date < eff_from:
                return False
            if eff_until is not None and att_date > eff_until:
                return False
        # Org-node scope: a rule scoped to node X applies to an employee iff X is
        # the employee's node or an ancestor of it (i.e. the employee is somewhere
        # in X's subtree). evaluate() puts the employee's ancestor-chain (node +
        # all parents) in context as `employee_scope_nodes`, so this is a simple
        # set intersection with no per-rule descendant expansion required.
        scope = getattr(rule, "scope_org_node_ids", None)
        if scope:
            chain = context.get("employee_scope_nodes") or set()
            if not (set(scope) & chain):
                return False
        return True

    @staticmethod
    async def simulate_record(
        db: AsyncSession,
        attendance: AttendanceRecord,
        context: Dict[str, Any],
        rules: Optional[list] = None,
    ) -> List[Dict[str, Any]]:
        """Dry-run: return the list of effects the active rules WOULD apply to this
        attendance, WITHOUT writing anything. Mirrors evaluate()'s matching/slot/
        terminal semantics exactly, but records intent instead of creating rows."""
        context = await PolicyEngineService._enrich_context(db, attendance, context)
        if rules is None:
            rules = list((await db.execute(
                select(PolicyRule).where(
                    PolicyRule.tenant_id == attendance.tenant_id,
                    PolicyRule.is_active == True,  # noqa: E712
                ).order_by(PolicyRule.priority.asc(), PolicyRule.id.asc())
            )).scalars().all())

        effects: List[Dict[str, Any]] = []
        filled_slots: set = set()
        for rule in rules:
            if not PolicyEngineService._rule_applies(rule, context):
                continue
            if not rule.conditions or not PolicyEngineService.evaluate_conditions(
                rule.conditions, context
            ):
                continue
            matched = False
            for action in rule.actions:
                resolved = PolicyEngineService._resolve_action(action, context)
                if not resolved:
                    continue
                atype = resolved.get("type")
                slot = PolicyEngineService._ACTION_SLOT.get(atype)
                if slot is None or slot in filled_slots:
                    continue
                # Would this action actually produce an effect for this record?
                if not PolicyEngineService._would_apply(atype, attendance, context):
                    continue
                filled_slots.add(slot)
                matched = True
                effects.append({
                    "rule_id": rule.id,
                    "rule_name": rule.name,
                    "action": atype,
                    "detail": PolicyEngineService._effect_detail(atype, resolved, attendance),
                })
            if matched and any(a.get("stop_processing") for a in rule.actions):
                break
        return effects

    @staticmethod
    def _would_apply(action_type: str, attendance: AttendanceRecord, context: Dict[str, Any]) -> bool:
        """Whether an action would produce an effect (matches the guards inside the
        real apply_* methods) — so the simulator doesn't over-report."""
        if action_type == "apply_ot_category":
            return (attendance.overtime_minutes or 0) > 0
        if action_type in ("salary_deduction", "leave_deduction", "send_warning", "mark_excused"):
            # mark_excused always has an effect (sets status); others need tardiness.
            if action_type == "mark_excused":
                return True
            return (attendance.tardiness_minutes or 0) > 0
        if action_type == "apply_night_diff":
            return bool(context.get("actual_start_time") and context.get("actual_end_time"))
        if action_type == "apply_holiday_pay":
            return bool(context.get("holiday_dates"))
        return False

    @staticmethod
    def _effect_detail(action_type: str, action: Dict, attendance: AttendanceRecord) -> str:
        if action_type == "apply_ot_category":
            return f"{attendance.overtime_minutes}min OT → {action.get('category_code','(no category)')}"
        if action_type in ("salary_deduction", "leave_deduction", "send_warning", "mark_excused"):
            return f"{attendance.tardiness_minutes}min tardy → {action_type}"
        if action_type == "apply_night_diff":
            return "night differential"
        if action_type == "apply_holiday_pay":
            return "holiday pay"
        return action_type

    @staticmethod
    async def _enrich_context(
        db: AsyncSession, attendance: AttendanceRecord, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Return a copy of context augmented with the employee's org ancestor
        chain and month/week offence counters. Idempotent — safe to call twice."""
        enriched = dict(context)
        if "employee_scope_nodes" not in enriched:
            enriched["employee_scope_nodes"] = await PolicyEngineService._employee_scope_nodes(
                db, attendance.tenant_id, attendance.employee_id
            )
        if "late_count_month" not in enriched:
            enriched.update(await PolicyEngineService._stateful_counts(db, attendance))
        return enriched

    @staticmethod
    async def _employee_scope_nodes(db: AsyncSession, tenant_id, employee_id: int) -> Set[int]:
        """The employee's org node plus all ancestors (self→root). A rule scoped to
        any node in this set applies to the employee (they're in that subtree).
        Scoped to the tenant so the ancestor walk stays within its own org tree."""
        from app.models.org_hierarchy import OrgNode
        from app.models.user import User

        row = (await db.execute(
            select(User.org_node_id).where(
                User.id == employee_id, User.tenant_id == tenant_id
            )
        )).first()
        node_id = row[0] if row else None
        chain: Set[int] = set()
        current = node_id
        while current and current not in chain:
            chain.add(current)
            parent_row = (await db.execute(
                select(OrgNode.parent_id).where(
                    OrgNode.id == current, OrgNode.tenant_id == tenant_id
                )
            )).first()
            current = parent_row[0] if parent_row else None
        return chain

    @staticmethod
    async def _stateful_counts(db: AsyncSession, attendance: AttendanceRecord) -> Dict[str, Any]:
        """Offence counters for 'Nth offense' rules, from the employee's OTHER
        attendance in the current month/week plus this record's own contribution
        (so the count is stable across re-evaluation of the same record)."""
        from calendar import monthrange
        d = attendance.date
        month_start = d.replace(day=1)
        month_end = d.replace(day=monthrange(d.year, d.month)[1])
        week_start = d - timedelta(days=d.isoweekday() - 1)
        week_end = week_start + timedelta(days=6)
        self_id = attendance.id or -1

        async def _count(*conds) -> int:
            stmt = select(func.count()).select_from(AttendanceRecord).where(
                AttendanceRecord.tenant_id == attendance.tenant_id,
                AttendanceRecord.employee_id == attendance.employee_id,
                AttendanceRecord.id != self_id,
                *conds,
            )
            return (await db.execute(stmt)).scalar() or 0

        late_month = await _count(
            AttendanceRecord.date >= month_start, AttendanceRecord.date <= month_end,
            AttendanceRecord.tardiness_minutes > 0,
        )
        late_week = await _count(
            AttendanceRecord.date >= week_start, AttendanceRecord.date <= week_end,
            AttendanceRecord.tardiness_minutes > 0,
        )
        absent_month = await _count(
            AttendanceRecord.date >= month_start, AttendanceRecord.date <= month_end,
            AttendanceRecord.status == "absent",
        )
        self_late = 1 if (attendance.tardiness_minutes or 0) > 0 else 0
        self_absent = 1 if attendance.status == "absent" else 0
        return {
            "late_count_month": late_month + self_late,
            "late_count_week": late_week + self_late,
            "absent_count_month": absent_month + self_absent,
        }

    @staticmethod
    async def _apply_action(
        db: AsyncSession,
        attendance: AttendanceRecord,
        action: Dict,
        action_type: Optional[str],
        rule: PolicyRule,
        context: Dict[str, Any],
        results: Dict[str, Any],
    ) -> bool:
        """Apply a single action. Returns True if it produced an effect."""
        if action_type == "apply_ot_category":
            ot_log = await PolicyEngineService._apply_ot_category(
                db, attendance, action, rule, context
            )
            if ot_log:
                results["overtime_log"] = ot_log
                return True

        elif action_type == "salary_deduction":
            tard = await PolicyEngineService._create_tardiness_record(
                db, attendance, rule, "salary_deduction"
            )
            if tard:
                results["tardiness_record"] = tard
                return True

        elif action_type == "leave_deduction":
            tard = await PolicyEngineService._create_tardiness_record(
                db, attendance, rule, "leave_deduction",
                round_to_hours=action.get("round_to_hours"),
            )
            if tard:
                results["tardiness_record"] = tard
                return True

        elif action_type == "send_warning":
            tard = await PolicyEngineService._create_tardiness_record(
                db, attendance, rule, "warning"
            )
            if tard:
                results["tardiness_record"] = tard
                return True

        elif action_type == "mark_excused":
            attendance.status = "excused"
            tard = await PolicyEngineService._create_tardiness_record(
                db, attendance, rule, "excused"
            )
            if tard:
                results["tardiness_record"] = tard
                return True
            # mark_excused still counts as an effect even with no tardiness row.
            return True

        elif action_type == "apply_night_diff":
            nd_log = await PolicyEngineService._apply_night_diff(
                db, attendance, action, context
            )
            if nd_log:
                results["night_diff_log"] = nd_log
                return True

        elif action_type == "apply_holiday_pay":
            hp_log = await PolicyEngineService._apply_holiday_pay(
                db, attendance, action, context
            )
            if hp_log:
                results["holiday_pay_log"] = hp_log
                return True

        return False

    @staticmethod
    async def _apply_ot_category(
        db: AsyncSession,
        attendance: AttendanceRecord,
        action: Dict,
        rule: PolicyRule,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[OvertimeLog]:
        """Create an OvertimeLog based on category lookup.
        For holiday OT rules, only counts OT minutes proportional to holiday time."""
        if attendance.overtime_minutes <= 0:
            return None

        ot_minutes = attendance.overtime_minutes

        # For holiday OT rules, compute proportional holiday OT minutes
        if context:
            holiday_dates = context.get("holiday_dates", set())
            actual_start = context.get("actual_start_time")
            actual_end = context.get("actual_end_time")
            attendance_date = context.get("attendance_date")

            if holiday_dates and actual_start and actual_end and attendance_date:
                # Calculate total shift minutes
                start_dt = datetime.combine(attendance_date, actual_start)
                end_dt = datetime.combine(attendance_date, actual_end)
                if end_dt <= start_dt:
                    end_dt += timedelta(days=1)
                total_mins = int((end_dt - start_dt).total_seconds() / 60)

                holiday_mins = compute_holiday_minutes(
                    actual_start, actual_end, attendance_date, holiday_dates
                )

                if total_mins > 0 and holiday_mins < total_mins:
                    # Proportionally split OT minutes based on holiday time ratio
                    holiday_ratio = holiday_mins / total_mins
                    ot_minutes = max(1, int(round(attendance.overtime_minutes * holiday_ratio)))

        category_code = action.get("category_code")
        category = None
        if category_code:
            stmt = select(OvertimeCategory).where(
                OvertimeCategory.tenant_id == attendance.tenant_id,
                OvertimeCategory.code == category_code,
                OvertimeCategory.is_active == True,
            )
            result = await db.execute(stmt)
            category = result.scalar_one_or_none()

        ot_log = OvertimeLog(
            tenant_id=attendance.tenant_id,
            employee_id=attendance.employee_id,
            attendance_record_id=attendance.id,
            date=attendance.date,
            overtime_minutes=ot_minutes,
            overtime_category_id=category.id if category else None,
            pay_multiplier=category.multiplier_rate if category else None,
            status="pending",
        )
        db.add(ot_log)
        await db.flush()
        return ot_log

    @staticmethod
    async def _create_tardiness_record(
        db: AsyncSession,
        attendance: AttendanceRecord,
        rule: PolicyRule,
        resolution_type: str,
        round_to_hours: Optional[int] = None,
    ) -> Optional[TardinessRecord]:
        """Create a TardinessRecord for the attendance."""
        if attendance.tardiness_minutes <= 0:
            return None

        leave_credits_deducted = None
        if resolution_type == "leave_deduction" and round_to_hours:
            # Round up tardiness to nearest N hours, convert to day credits
            hours_late = math.ceil(attendance.tardiness_minutes / (round_to_hours * 60)) * round_to_hours
            leave_credits_deducted = hours_late / 8.0  # assume 8-hour day for credit calc

        tard = TardinessRecord(
            tenant_id=attendance.tenant_id,
            employee_id=attendance.employee_id,
            attendance_record_id=attendance.id,
            date=attendance.date,
            tardiness_minutes=attendance.tardiness_minutes,
            resolution_type=resolution_type,
            leave_credits_deducted=leave_credits_deducted,
            policy_rule_id=rule.id,
        )
        db.add(tard)
        await db.flush()

        # If leave deduction, create a LeaveCreditAdjustment
        if resolution_type == "leave_deduction" and leave_credits_deducted:
            adj = LeaveCreditAdjustment(
                tenant_id=attendance.tenant_id,
                employee_id=attendance.employee_id,
                adjustment_type="tardiness_deduction",
                credits=-leave_credits_deducted,
                source_id=tard.id,
                source_type="tardiness_record",
                notes=f"Auto-deducted for {attendance.tardiness_minutes}min tardiness on {attendance.date}",
            )
            db.add(adj)
            await db.flush()

        return tard

    @staticmethod
    async def _apply_night_diff(
        db: AsyncSession,
        attendance: AttendanceRecord,
        action: Dict,
        context: Dict[str, Any],
    ) -> Optional[OvertimeLog]:
        """Create an OvertimeLog for night differential hours."""
        actual_start = context.get("actual_start_time")
        actual_end = context.get("actual_end_time")
        if not actual_start or not actual_end:
            return None

        start_hour = int(action.get("start_hour", 22))
        end_hour = int(action.get("end_hour", 6))

        night_mins = compute_night_minutes(actual_start, actual_end, start_hour, end_hour)
        if night_mins <= 0:
            return None

        # Look up OT category for pay multiplier
        category_code = action.get("category_code")
        category = None
        if category_code:
            stmt = select(OvertimeCategory).where(
                OvertimeCategory.tenant_id == attendance.tenant_id,
                OvertimeCategory.code == category_code,
                OvertimeCategory.is_active == True,
            )
            result = await db.execute(stmt)
            category = result.scalar_one_or_none()

        nd_log = OvertimeLog(
            tenant_id=attendance.tenant_id,
            employee_id=attendance.employee_id,
            attendance_record_id=attendance.id,
            date=attendance.date,
            overtime_minutes=night_mins,
            log_type="night_differential",
            overtime_category_id=category.id if category else None,
            pay_multiplier=category.multiplier_rate if category else None,
            status="pending",
            notes=f"Night diff {start_hour}:00-{end_hour}:00 ({night_mins}min)",
        )
        db.add(nd_log)
        await db.flush()

        # Optional leave conversion
        if action.get("convert_to_leave") and category:
            rate = category.leave_credit_rate or 0
            if rate > 0:
                credits = (night_mins / 60.0) * rate
                adj = LeaveCreditAdjustment(
                    tenant_id=attendance.tenant_id,
                    employee_id=attendance.employee_id,
                    adjustment_type="ot_conversion",
                    credits=credits,
                    source_id=nd_log.id,
                    source_type="overtime_log",
                    notes=f"Night diff conversion: {night_mins}min at rate {rate}",
                )
                db.add(adj)
                nd_log.leave_credits_earned = credits
                nd_log.status = "converted"
                await db.flush()

        return nd_log

    @staticmethod
    async def _apply_holiday_pay(
        db: AsyncSession,
        attendance: AttendanceRecord,
        action: Dict,
        context: Dict[str, Any],
    ) -> Optional[OvertimeLog]:
        """Create an OvertimeLog for holiday shift pay (day-boundary-aware).
        Only counts the minutes that actually fall on holiday calendar dates."""
        actual_start = context.get("actual_start_time")
        actual_end = context.get("actual_end_time")
        holiday_dates = context.get("holiday_dates", set())
        attendance_date = context.get("attendance_date", attendance.date)

        if actual_start and actual_end and holiday_dates:
            # Day-boundary-aware: only count minutes on holiday dates
            worked_mins = compute_holiday_minutes(
                actual_start, actual_end, attendance_date, holiday_dates
            )
        else:
            # Fallback to legacy behavior if no time data
            total_hours = context.get("hours_worked", 0)
            if total_hours <= 0:
                return None
            worked_mins = int(total_hours * 60)

        if worked_mins <= 0:
            return None

        hours_worked = worked_mins / 60.0

        # Look up OT category for pay multiplier
        category_code = action.get("category_code")
        category = None
        if category_code:
            stmt = select(OvertimeCategory).where(
                OvertimeCategory.tenant_id == attendance.tenant_id,
                OvertimeCategory.code == category_code,
                OvertimeCategory.is_active == True,
            )
            result = await db.execute(stmt)
            category = result.scalar_one_or_none()

        hp_log = OvertimeLog(
            tenant_id=attendance.tenant_id,
            employee_id=attendance.employee_id,
            attendance_record_id=attendance.id,
            date=attendance.date,
            overtime_minutes=worked_mins,
            log_type="holiday_shift",
            overtime_category_id=category.id if category else None,
            pay_multiplier=category.multiplier_rate if category else None,
            status="pending",
            notes=f"Holiday shift: {hours_worked:.1f}hrs on holiday (of {context.get('hours_worked', 0):.1f}hrs total)",
        )
        db.add(hp_log)
        await db.flush()

        # Optional leave conversion
        if action.get("convert_to_leave") and category:
            rate = category.leave_credit_rate or 0
            if rate > 0:
                credits = hours_worked * rate
                adj = LeaveCreditAdjustment(
                    tenant_id=attendance.tenant_id,
                    employee_id=attendance.employee_id,
                    adjustment_type="ot_conversion",
                    credits=credits,
                    source_id=hp_log.id,
                    source_type="overtime_log",
                    notes=f"Holiday shift conversion: {hours_worked:.1f}hrs at rate {rate}",
                )
                db.add(adj)
                hp_log.leave_credits_earned = credits
                hp_log.status = "converted"
                await db.flush()

        return hp_log
