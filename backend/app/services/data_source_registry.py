"""
Registry of data sources available for tenant data export.
Each source maps to one or more database models and defines
user-friendly column metadata + a query builder function.

Every query builder takes the same keyword arguments, so the pipeline can call
any of them the same way:

    name_format    how employee names are written
    date_from/to   ISO dates; the window is applied in SQL, not after loading
                   every row the tenant has ever had
    employee_ids   None = everyone, else only these employees. This is the
                   caller's reports scope (access_scope.managed_employee_ids):
                   a manager's report covers the people they manage, never the
                   whole company
    viewer         the person the report is for, which decides which custom
                   employee fields they may see. For a scheduled export it is
                   the schedule's owner
    ...            the source's own options (SOURCE_OPTIONS), e.g. whether to
                   include draft shifts
"""

from datetime import date, time
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import false, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.user import User
from app.models.schedule import Shift
from app.models.attendance import AttendanceRecord, OvertimeLog, TardinessRecord, LeaveCreditAdjustment
from app.models.leave import LeaveApplication, OvertimeCategory
from app.models.payroll import SalaryGrade, PayrollItem, PayrollPeriod
from app.models.org_hierarchy import OrgNode, OrgLevel
from app.models.configurable_types import ScheduleFormat
from app.services import schedule_semantics as semantics


def _fmt_time(t) -> str:
    if t is None:
        return ""
    if isinstance(t, time):
        return t.strftime("%H:%M")
    return str(t)


def _fmt_date(d) -> str:
    if d is None:
        return ""
    if isinstance(d, date):
        return d.isoformat()
    return str(d)


def _fmt_name(first_name: str, last_name: str, name_format: str = "first_last") -> str:
    """Format employee name based on the selected format."""
    if name_format == "last_first":
        return f"{last_name}, {first_name}"
    if name_format == "last_first_upper":
        return f"{last_name.upper()}, {first_name.upper()}"
    if name_format == "first_last_upper":
        return f"{first_name.upper()} {last_name.upper()}"
    # default: first_last
    return f"{first_name} {last_name}"


def _as_date(value: Any, which: str) -> Optional[date]:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise ValueError(f"The {which} date “{value}” is not a date. Use the date picker.")


def _window(stmt, column, kwargs: Dict[str, Any]):
    """Apply the report period in SQL."""
    d_from = _as_date(kwargs.get("date_from"), "start")
    d_to = _as_date(kwargs.get("date_to"), "end")
    if d_from:
        stmt = stmt.where(column >= d_from)
    if d_to:
        stmt = stmt.where(column <= d_to)
    return stmt


def _scoped(stmt, column, kwargs: Dict[str, Any]):
    """Limit to the caller's reports scope. An empty scope means nobody, never
    everybody."""
    ids = kwargs.get("employee_ids")
    if ids is None:
        return stmt
    ids = list(ids)
    return stmt.where(column.in_(ids)) if ids else stmt.where(false())


# ── Column definitions per source ────────────────────────────────

EMPLOYEES_COLUMNS = [
    {"key": "employee_id", "label": "Employee ID", "type": "number"},
    {"key": "full_name", "label": "Employee Name", "type": "string"},
    {"key": "first_name", "label": "First Name", "type": "string"},
    {"key": "last_name", "label": "Last Name", "type": "string"},
    {"key": "email", "label": "Email", "type": "string"},
    {"key": "username", "label": "Username", "type": "string"},
    {"key": "contact_number", "label": "Contact Number", "type": "string"},
    # Labelled with the company's own wording (AppSettings.employee_number_label)
    # when the columns are listed for a tenant.
    {"key": "personnel_number", "label": "Personnel Number", "type": "string"},
    {"key": "id_number", "label": "ID Number", "type": "string"},
    {"key": "job_title", "label": "Job Title", "type": "string"},
    {"key": "rank", "label": "Rank", "type": "string"},
    {"key": "employee_type", "label": "Employee Type", "type": "string"},
    {"key": "schedule_format", "label": "Schedule Format", "type": "string"},
    {"key": "hiring_date", "label": "Hiring Date", "type": "date"},
    {"key": "is_active", "label": "Active", "type": "string"},
    # Appended in 2026-09 (audit E-18), so existing reports keep their order.
    {"key": "middle_name", "label": "Middle Name", "type": "string"},
    {"key": "formal_name", "label": "Formal Name (LAST, First)", "type": "string"},
    {"key": "typecode", "label": "Typecode", "type": "string"},
    {"key": "div_department", "label": "Division / Department", "type": "string"},
    {"key": "org_unit", "label": "Org Unit", "type": "string"},
    {"key": "line_manager", "label": "Line Manager", "type": "string"},
    {"key": "separation_type", "label": "Separation Type", "type": "string"},
    {"key": "separation_date", "label": "Separation Date", "type": "date"},
]

# Custom employee fields are listed per tenant as "cf_<key>". The prefix keeps
# them apart from built-in columns added later.
CUSTOM_FIELD_PREFIX = "cf_"
_CUSTOM_FIELD_TYPES = {"number": "number", "date": "date"}

SCHEDULES_COLUMNS = [
    {"key": "employee_id", "label": "Employee ID", "type": "number"},
    {"key": "employee_name", "label": "Employee Name", "type": "string"},
    {"key": "date", "label": "Date", "type": "date"},
    {"key": "start_time", "label": "Start Time", "type": "time"},
    {"key": "end_time", "label": "End Time", "type": "time"},
    {"key": "schedule", "label": "Schedule", "type": "string"},
    {"key": "day_work_status", "label": "Day Work Status (DWS)", "type": "string"},
    {"key": "status", "label": "Status", "type": "string"},
    {"key": "work_arrangement", "label": "Work Arrangement", "type": "string"},
    {"key": "paid_break_minutes", "label": "Paid Break (min)", "type": "number"},
    {"key": "paid_break_start", "label": "Paid Break Start", "type": "time"},
    {"key": "paid_break_end", "label": "Paid Break End", "type": "time"},
    {"key": "unpaid_break_minutes", "label": "Unpaid Break (min)", "type": "number"},
    {"key": "unpaid_break_start", "label": "Unpaid Break Start", "type": "time"},
    {"key": "unpaid_break_end", "label": "Unpaid Break End", "type": "time"},
    {"key": "schedule_format_name", "label": "Schedule Format", "type": "string"},
    {"key": "notes", "label": "Notes", "type": "string"},
    {"key": "remarks", "label": "Remarks", "type": "string"},
    # Appended for the formal work schedule (report layouts), so existing
    # reports keep their column order.
    {"key": "employee_formal_name", "label": "Employee (LAST, First)", "type": "string"},
    {"key": "export_remark", "label": "Remark (leave code / HOL OFF)", "type": "string"},
    {"key": "is_holiday", "label": "Holiday", "type": "string"},
]

ATTENDANCE_COLUMNS = [
    {"key": "employee_id", "label": "Employee ID", "type": "number"},
    {"key": "employee_name", "label": "Employee Name", "type": "string"},
    {"key": "date", "label": "Date", "type": "date"},
    {"key": "actual_start_time", "label": "Actual Start", "type": "time"},
    {"key": "actual_end_time", "label": "Actual End", "type": "time"},
    {"key": "scheduled_start_time", "label": "Scheduled Start", "type": "time"},
    {"key": "scheduled_end_time", "label": "Scheduled End", "type": "time"},
    {"key": "hours_worked", "label": "Hours Worked", "type": "number"},
    {"key": "tardiness_minutes", "label": "Tardiness (min)", "type": "number"},
    {"key": "overtime_minutes", "label": "Overtime (min)", "type": "number"},
    {"key": "undertime_minutes", "label": "Undertime (min)", "type": "number"},
    {"key": "status", "label": "Status", "type": "string"},
    {"key": "notes", "label": "Notes", "type": "string"},
]

LEAVE_COLUMNS = [
    {"key": "employee_id", "label": "Employee ID", "type": "number"},
    {"key": "employee_name", "label": "Employee Name", "type": "string"},
    {"key": "leave_type", "label": "Leave Type", "type": "string"},
    {"key": "start_date", "label": "Start Date", "type": "date"},
    {"key": "end_date", "label": "End Date", "type": "date"},
    {"key": "days_requested", "label": "Days Requested", "type": "number"},
    {"key": "reason", "label": "Reason", "type": "string"},
    {"key": "status", "label": "Status", "type": "string"},
    {"key": "created_at", "label": "Filed On", "type": "datetime"},
]

OVERTIME_COLUMNS = [
    {"key": "employee_id", "label": "Employee ID", "type": "number"},
    {"key": "employee_name", "label": "Employee Name", "type": "string"},
    {"key": "date", "label": "Date", "type": "date"},
    {"key": "overtime_minutes", "label": "OT Minutes", "type": "number"},
    {"key": "overtime_category_name", "label": "OT Category", "type": "string"},
    {"key": "pay_multiplier", "label": "Pay Multiplier", "type": "number"},
    {"key": "pay_amount", "label": "Pay Amount", "type": "number"},
    {"key": "leave_credits_earned", "label": "Leave Credits Earned", "type": "number"},
    {"key": "status", "label": "Status", "type": "string"},
    {"key": "notes", "label": "Notes", "type": "string"},
]

TARDINESS_COLUMNS = [
    {"key": "employee_id", "label": "Employee ID", "type": "number"},
    {"key": "employee_name", "label": "Employee Name", "type": "string"},
    {"key": "date", "label": "Date", "type": "date"},
    {"key": "tardiness_minutes", "label": "Minutes Late", "type": "number"},
    {"key": "resolution_type", "label": "Resolution", "type": "string"},
    {"key": "deduction_amount", "label": "Deduction Amount", "type": "number"},
    {"key": "leave_credits_deducted", "label": "Leave Credits Deducted", "type": "number"},
    {"key": "notes", "label": "Notes", "type": "string"},
]

PAYROLL_COLUMNS = [
    {"key": "employee_id", "label": "Employee ID", "type": "number"},
    {"key": "employee_name", "label": "Employee Name", "type": "string"},
    {"key": "period_name", "label": "Payroll Period", "type": "string"},
    {"key": "period_start", "label": "Period Start", "type": "date"},
    {"key": "period_end", "label": "Period End", "type": "date"},
    {"key": "grade_name", "label": "Salary Grade", "type": "string"},
    {"key": "base_pay", "label": "Base Pay", "type": "number"},
    {"key": "overtime_pay", "label": "Overtime Pay", "type": "number"},
    {"key": "gross_pay", "label": "Gross Pay", "type": "number"},
    {"key": "total_deductions", "label": "Total Deductions", "type": "number"},
    {"key": "total_contributions", "label": "Total Contributions", "type": "number"},
    {"key": "net_pay", "label": "Net Pay", "type": "number"},
]

SALARY_GRADES_COLUMNS = [
    {"key": "code", "label": "Code", "type": "string"},
    {"key": "name", "label": "Name", "type": "string"},
    {"key": "description", "label": "Description", "type": "string"},
    {"key": "monthly_rate", "label": "Monthly Rate", "type": "number"},
    {"key": "daily_rate", "label": "Daily Rate", "type": "number"},
    {"key": "hourly_rate", "label": "Hourly Rate", "type": "number"},
    {"key": "is_active", "label": "Active", "type": "string"},
]

ORGANIZATION_COLUMNS = [
    {"key": "node_name", "label": "Name", "type": "string"},
    {"key": "node_code", "label": "Code", "type": "string"},
    {"key": "level_name", "label": "Level", "type": "string"},
    {"key": "head_name", "label": "Head", "type": "string"},
    {"key": "deputy_head_name", "label": "Deputy Head", "type": "string"},
    {"key": "is_active", "label": "Active", "type": "string"},
]

LEAVE_CREDITS_COLUMNS = [
    {"key": "employee_id", "label": "Employee ID", "type": "number"},
    {"key": "employee_name", "label": "Employee Name", "type": "string"},
    {"key": "adjustment_type", "label": "Adjustment Type", "type": "string"},
    {"key": "leave_type", "label": "Leave Type", "type": "string"},
    {"key": "credits", "label": "Credits", "type": "number"},
    {"key": "source_type", "label": "Source", "type": "string"},
    {"key": "notes", "label": "Notes", "type": "string"},
    {"key": "created_at", "label": "Date", "type": "datetime"},
]


# ── Source options ───────────────────────────────────────────────
#
# Per-source switches a report can set (DataExportConfig.source_options). They
# change which rows the source produces, so they are part of the report, not a
# display choice.

SOURCE_OPTIONS: Dict[str, List[Dict[str, Any]]] = {
    "schedules": [
        {
            "key": "include_drafts",
            "label": "Include draft shifts",
            "type": "boolean",
            "default": False,
            "help": "Drafts are shifts not yet published to employees. They are left out "
                    "unless you ask for them, because nobody has been told about them yet.",
        },
        {
            "key": "fill_calendar_days",
            "label": "Show every day in the period",
            "type": "boolean",
            "default": False,
            "help": "Adds a row for each day an employee has no shift, marked as a day off. "
                    "Needs a period with a start and an end.",
        },
        {
            "key": "rest_day_label",
            "label": "Word for a day off",
            "type": "string",
            "default": semantics.DEFAULT_REST_LABEL,
            "help": "What the Day Work Status column says on rest days and days with no shift.",
        },
        {
            "key": "include_employees",
            "label": "Which employees",
            "type": "choice",
            "default": "with_shifts",
            "choices": [
                {"value": "with_shifts", "label": "Only people with a shift in the period"},
                {"value": "all_active", "label": "Every active employee"},
            ],
            "help": "Only used when every day is shown.",
        },
    ],
}

# Showing every day of a period for every employee is employees x days rows.
MAX_FILL_DAYS = 366


def clean_source_options(data_source: str, options: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Validate a report's source options, dropping defaults.

    For a joined report a key may be namespaced ("schedules.include_drafts");
    a bare key applies to every source in the report that has that option.
    """
    out: Dict[str, Any] = {}
    for raw_key, value in (options or {}).items():
        if "." in raw_key:
            src, key = raw_key.split(".", 1)
        else:
            src, key = data_source, raw_key
        candidates = [src] if src != "multi" else list(SOURCE_OPTIONS)
        spec = None
        for c in candidates:
            spec = next((o for o in SOURCE_OPTIONS.get(c, []) if o["key"] == key), None)
            if spec:
                break
        if spec is None:
            raise ValueError(f"“{raw_key}” is not an option of this data.")
        if spec["type"] == "boolean":
            value = bool(value)
        elif spec["type"] == "choice":
            allowed = {c["value"] for c in spec["choices"]}
            if value not in allowed:
                raise ValueError(f"{spec['label']} must be one of: {', '.join(sorted(allowed))}.")
        else:
            value = ("" if value is None else str(value)).strip()[:30]
        out[raw_key] = value
    return out


def options_for(source_key: str, options: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The query kwargs a source gets from a report's options."""
    out: Dict[str, Any] = {}
    known = {o["key"] for o in SOURCE_OPTIONS.get(source_key, [])}
    for raw_key, value in (options or {}).items():
        if "." in raw_key:
            src, key = raw_key.split(".", 1)
            if src != source_key:
                continue
        else:
            key = raw_key
        if key in known:
            out[key] = value
    return out


# ── Query builders ───────────────────────────────────────────────

async def _query_employees(db: AsyncSession, tenant_id: UUID, **kwargs) -> List[Dict[str, Any]]:
    name_format = kwargs.get("name_format") or "first_last"
    Manager = aliased(User)
    stmt = (
        select(User, OrgNode.name, Manager.first_name, Manager.last_name)
        .outerjoin(OrgNode, User.org_node_id == OrgNode.id)
        .outerjoin(Manager, User.reports_to_id == Manager.id)
        .where(User.tenant_id == tenant_id, User.is_superadmin == False)  # noqa: E712
    )
    stmt = _scoped(stmt, User.id, kwargs)
    result = await db.execute(stmt)
    rows = []
    for u, org_unit, mgr_first, mgr_last in result.all():
        rows.append({
            "employee_id": u.id,
            "full_name": _fmt_name(u.first_name, u.last_name, name_format),
            "first_name": u.first_name,
            "last_name": u.last_name,
            "email": u.email,
            "username": u.username,
            "contact_number": u.contact_number or "",
            "personnel_number": u.personnel_number or "",
            "id_number": u.id_number or "",
            "job_title": u.job_title or "",
            "rank": u.rank or "",
            "employee_type": u.employee_type or "",
            "schedule_format": u.schedule_format or "",
            "hiring_date": _fmt_date(u.hiring_date),
            "is_active": "Yes" if u.is_active else "No",
            "middle_name": u.middle_name or "",
            "formal_name": semantics.formal_name(u.first_name, u.middle_name, u.last_name),
            "typecode": u.typecode or "",
            "div_department": u.div_department or "",
            "org_unit": org_unit or "",
            "line_manager": _fmt_name(mgr_first, mgr_last, name_format) if mgr_first is not None else "",
            "separation_type": (u.separation_type or "").replace("_", " ").capitalize(),
            "separation_date": _fmt_date(u.separation_date),
        })

    # Company-defined fields, only those the viewer may see. No viewer (a
    # report with no known audience) gets none, never all of them.
    viewer = kwargs.get("viewer")
    if rows and viewer is not None:
        from app.services.employee_field_service import custom_field_columns, custom_field_values

        defs = await custom_field_columns(db, tenant_id)
        if defs:
            values = await custom_field_values(db, tenant_id, [r["employee_id"] for r in rows], viewer)
            for r in rows:
                mine = values.get(r["employee_id"], {})
                for d in defs:
                    v = mine.get(d["key"])
                    if isinstance(v, bool):
                        v = "Yes" if v else "No"
                    r[CUSTOM_FIELD_PREFIX + d["key"]] = "" if v is None else v
    return rows


async def _query_schedules(db: AsyncSession, tenant_id: UUID, **kwargs) -> List[Dict[str, Any]]:
    """One row per shift segment, or with fill_calendar_days one row per
    employee per day of the period.

    Every segment of a split shift is its own row: the formal exporter kept only
    the first segment of the day (audit G-13). Draft shifts are left out unless
    include_drafts is set (G-7): until 2026-09 every report included them, so a
    schedule nobody had been told about went out to payroll as if it were real.
    """
    name_format = kwargs.get("name_format") or "first_last"
    include_drafts = bool(kwargs.get("include_drafts"))
    fill = bool(kwargs.get("fill_calendar_days"))
    rest_label = (kwargs.get("rest_day_label") or semantics.DEFAULT_REST_LABEL)
    include_employees = kwargs.get("include_employees") or "with_shifts"
    d_from = _as_date(kwargs.get("date_from"), "start")
    d_to = _as_date(kwargs.get("date_to"), "end")

    if fill:
        if not (d_from and d_to):
            raise ValueError(
                "Showing every day in the period needs a period with a start and an end. "
                "Choose a period, or turn off “Show every day in the period”."
            )
        if d_to < d_from:
            raise ValueError("The period ends before it starts.")
        if (d_to - d_from).days + 1 > MAX_FILL_DAYS:
            raise ValueError(
                f"Showing every day works for periods of up to {MAX_FILL_DAYS} days. "
                "Choose a shorter period."
            )

    # Schedule formats, for break times.
    sf_map: Dict[str, ScheduleFormat] = {
        sf.code: sf
        for sf in (
            await db.execute(select(ScheduleFormat).where(ScheduleFormat.tenant_id == tenant_id))
        ).scalars().all()
    }
    rest_set = await semantics.rest_statuses(db, tenant_id)
    leave_codes = await semantics.leave_export_codes(db, tenant_id)

    stmt = (
        select(Shift, User, LeaveApplication.leave_type)
        .join(User, Shift.employee_id == User.id)
        .outerjoin(LeaveApplication, Shift.leave_application_id == LeaveApplication.id)
        .where(Shift.tenant_id == tenant_id)
    )
    if not include_drafts:
        stmt = stmt.where(Shift.is_published == True)  # noqa: E712
    stmt = _window(stmt, Shift.date, kwargs)
    stmt = _scoped(stmt, Shift.employee_id, kwargs)
    stmt = stmt.order_by(
        Shift.date, User.last_name, User.first_name, User.id, Shift.sequence_number
    )
    loaded = (await db.execute(stmt)).all()

    # Holidays, including recurring ones, for the period the rows cover.
    if loaded or fill:
        h_from = d_from or min(s.date for s, _u, _lt in loaded)
        h_to = d_to or max(s.date for s, _u, _lt in loaded)
        from app.services.holiday_calendar import holidays_between

        holidays = await holidays_between(db, tenant_id, h_from, h_to)
    else:
        holidays = {}

    def employee_fields(u: User) -> Dict[str, Any]:
        return {
            "employee_id": u.id,
            "employee_name": _fmt_name(u.first_name, u.last_name, name_format),
            "employee_formal_name": semantics.formal_name(u.first_name, u.middle_name, u.last_name),
        }

    def shift_row(shift: Shift, u: User, leave_type: Optional[str]) -> Dict[str, Any]:
        st = _fmt_time(shift.start_time)
        et = _fmt_time(shift.end_time)
        off = semantics.is_rest(shift.status, rest_set)
        fmt = sf_map.get(u.schedule_format or "")
        paid_s = paid_e = unpaid_s = unpaid_e = None
        if not off:
            paid_s, paid_e, unpaid_s, unpaid_e = semantics.derive_breaks(fmt, shift.start_time)
        is_hol = shift.date in holidays
        leave_code = semantics.leave_code_for(leave_type, shift.status, leave_codes)
        return {
            **employee_fields(u),
            "date": _fmt_date(shift.date),
            "start_time": st,
            "end_time": et,
            "schedule": f"{st}-{et}" if st and et else "",
            "day_work_status": rest_label if off else "",
            "status": shift.status or "",
            "work_arrangement": shift.work_arrangement or "",
            "paid_break_minutes": (fmt.paid_break_minutes or 0) if fmt else 0,
            "paid_break_start": _fmt_time(paid_s),
            "paid_break_end": _fmt_time(paid_e),
            "unpaid_break_minutes": (fmt.unpaid_break_minutes or 0) if fmt else 0,
            "unpaid_break_start": _fmt_time(unpaid_s),
            "unpaid_break_end": _fmt_time(unpaid_e),
            "schedule_format_name": fmt.name if fmt else (u.schedule_format or ""),
            "notes": shift.notes or "",
            "remarks": shift.remarks or "",
            "export_remark": semantics.export_remark(
                leave_code=leave_code, off_day=off, is_holiday=is_hol,
                status=shift.status, shift_remarks=shift.remarks,
            ),
            "is_holiday": "Yes" if is_hol else "No",
        }

    if not fill:
        return [shift_row(s, u, lt) for s, u, lt in loaded]

    # Dense calendar: every employee, every day, in employee order.
    by_emp_day: Dict[tuple, List[tuple]] = {}
    people: Dict[int, User] = {}
    for s, u, lt in loaded:
        by_emp_day.setdefault((u.id, s.date), []).append((s, u, lt))
        people[u.id] = u
    if include_employees == "all_active":
        pstmt = select(User).where(
            User.tenant_id == tenant_id,
            User.is_active == True,  # noqa: E712
            User.is_superadmin == False,  # noqa: E712
        )
        pstmt = _scoped(pstmt, User.id, kwargs)
        for u in (await db.execute(pstmt)).scalars().all():
            people.setdefault(u.id, u)
    ordered = sorted(
        people.values(), key=lambda u: ((u.last_name or "").lower(), (u.first_name or "").lower(), u.id)
    )

    from datetime import timedelta

    days = [d_from + timedelta(days=i) for i in range((d_to - d_from).days + 1)]
    rows: List[Dict[str, Any]] = []
    for u in ordered:
        fmt = sf_map.get(u.schedule_format or "")
        for day in days:
            segments = by_emp_day.get((u.id, day))
            if segments:
                rows.extend(shift_row(s, uu, lt) for s, uu, lt in segments)
                continue
            is_hol = day in holidays
            rows.append({
                **employee_fields(u),
                "date": _fmt_date(day),
                "start_time": "",
                "end_time": "",
                "schedule": "",
                "day_work_status": rest_label,
                "status": "",
                "work_arrangement": "",
                "paid_break_minutes": (fmt.paid_break_minutes or 0) if fmt else 0,
                "paid_break_start": "",
                "paid_break_end": "",
                "unpaid_break_minutes": (fmt.unpaid_break_minutes or 0) if fmt else 0,
                "unpaid_break_start": "",
                "unpaid_break_end": "",
                "schedule_format_name": fmt.name if fmt else (u.schedule_format or ""),
                "notes": "",
                "remarks": "",
                "export_remark": semantics.export_remark(
                    leave_code="", off_day=True, is_holiday=is_hol
                ),
                "is_holiday": "Yes" if is_hol else "No",
            })
    return rows


async def _query_attendance(db: AsyncSession, tenant_id: UUID, **kwargs) -> List[Dict[str, Any]]:
    name_format = kwargs.get("name_format") or "first_last"
    stmt = (
        select(AttendanceRecord, User.first_name, User.last_name)
        .join(User, AttendanceRecord.employee_id == User.id)
        .where(AttendanceRecord.tenant_id == tenant_id)
    )
    stmt = _window(stmt, AttendanceRecord.date, kwargs)
    stmt = _scoped(stmt, AttendanceRecord.employee_id, kwargs)
    result = await db.execute(stmt.order_by(AttendanceRecord.date.desc()))
    rows = []
    for rec, first_name, last_name in result.all():
        rows.append({
            "employee_id": rec.employee_id,
            "employee_name": _fmt_name(first_name, last_name, name_format),
            "date": _fmt_date(rec.date),
            "actual_start_time": _fmt_time(rec.actual_start_time),
            "actual_end_time": _fmt_time(rec.actual_end_time),
            "scheduled_start_time": _fmt_time(rec.scheduled_start_time),
            "scheduled_end_time": _fmt_time(rec.scheduled_end_time),
            "hours_worked": rec.hours_worked or 0,
            "tardiness_minutes": rec.tardiness_minutes,
            "overtime_minutes": rec.overtime_minutes,
            "undertime_minutes": rec.undertime_minutes,
            "status": rec.status or "",
            "notes": rec.notes or "",
        })
    return rows


async def _query_leave(db: AsyncSession, tenant_id: UUID, **kwargs) -> List[Dict[str, Any]]:
    name_format = kwargs.get("name_format") or "first_last"
    stmt = (
        select(LeaveApplication, User.first_name, User.last_name)
        .join(User, LeaveApplication.employee_id == User.id)
        .where(LeaveApplication.tenant_id == tenant_id)
    )
    stmt = _scoped(stmt, LeaveApplication.employee_id, kwargs)
    result = await db.execute(stmt.order_by(LeaveApplication.created_at.desc()))
    rows = []
    for la, first_name, last_name in result.all():
        rows.append({
            "employee_id": la.employee_id,
            "employee_name": _fmt_name(first_name, last_name, name_format),
            "leave_type": la.leave_type,
            "start_date": _fmt_date(la.start_date),
            "end_date": _fmt_date(la.end_date),
            "days_requested": la.days_requested,
            "reason": la.reason or "",
            "status": la.status,
            "created_at": str(la.created_at) if la.created_at else "",
        })
    return rows


async def _query_overtime(db: AsyncSession, tenant_id: UUID, **kwargs) -> List[Dict[str, Any]]:
    name_format = kwargs.get("name_format") or "first_last"
    stmt = (
        select(OvertimeLog, User.first_name, User.last_name, OvertimeCategory.name)
        .join(User, OvertimeLog.employee_id == User.id)
        .outerjoin(OvertimeCategory, OvertimeLog.overtime_category_id == OvertimeCategory.id)
        .where(OvertimeLog.tenant_id == tenant_id)
    )
    stmt = _window(stmt, OvertimeLog.date, kwargs)
    stmt = _scoped(stmt, OvertimeLog.employee_id, kwargs)
    result = await db.execute(stmt.order_by(OvertimeLog.date.desc()))
    rows = []
    for log, first_name, last_name, cat_name in result.all():
        rows.append({
            "employee_id": log.employee_id,
            "employee_name": _fmt_name(first_name, last_name, name_format),
            "date": _fmt_date(log.date),
            "overtime_minutes": log.overtime_minutes,
            "overtime_category_name": cat_name or "",
            "pay_multiplier": log.pay_multiplier or 0,
            "pay_amount": log.pay_amount or 0,
            "leave_credits_earned": log.leave_credits_earned or 0,
            "status": log.status,
            "notes": log.notes or "",
        })
    return rows


async def _query_tardiness(db: AsyncSession, tenant_id: UUID, **kwargs) -> List[Dict[str, Any]]:
    name_format = kwargs.get("name_format") or "first_last"
    stmt = (
        select(TardinessRecord, User.first_name, User.last_name)
        .join(User, TardinessRecord.employee_id == User.id)
        .where(TardinessRecord.tenant_id == tenant_id)
    )
    stmt = _window(stmt, TardinessRecord.date, kwargs)
    stmt = _scoped(stmt, TardinessRecord.employee_id, kwargs)
    result = await db.execute(stmt.order_by(TardinessRecord.date.desc()))
    rows = []
    for rec, first_name, last_name in result.all():
        rows.append({
            "employee_id": rec.employee_id,
            "employee_name": _fmt_name(first_name, last_name, name_format),
            "date": _fmt_date(rec.date),
            "tardiness_minutes": rec.tardiness_minutes,
            "resolution_type": rec.resolution_type or "",
            "deduction_amount": rec.deduction_amount or 0,
            "leave_credits_deducted": rec.leave_credits_deducted or 0,
            "notes": rec.notes or "",
        })
    return rows


async def _query_payroll(db: AsyncSession, tenant_id: UUID, **kwargs) -> List[Dict[str, Any]]:
    name_format = kwargs.get("name_format") or "first_last"
    stmt = (
        select(PayrollItem, User.first_name, User.last_name, PayrollPeriod.name, PayrollPeriod.start_date, PayrollPeriod.end_date, SalaryGrade.name)
        .join(User, PayrollItem.employee_id == User.id)
        .join(PayrollPeriod, PayrollItem.payroll_period_id == PayrollPeriod.id)
        .outerjoin(SalaryGrade, PayrollItem.salary_grade_id == SalaryGrade.id)
        .where(PayrollItem.tenant_id == tenant_id)
    )
    stmt = _scoped(stmt, PayrollItem.employee_id, kwargs)
    result = await db.execute(stmt.order_by(PayrollPeriod.start_date.desc(), User.last_name))
    rows = []
    for pi, first_name, last_name, period_name, period_start, period_end, grade_name in result.all():
        rows.append({
            "employee_id": pi.employee_id,
            "employee_name": _fmt_name(first_name, last_name, name_format),
            "period_name": period_name,
            "period_start": _fmt_date(period_start),
            "period_end": _fmt_date(period_end),
            "grade_name": grade_name or "",
            "base_pay": pi.base_pay,
            "overtime_pay": pi.overtime_pay,
            "gross_pay": pi.gross_pay,
            "total_deductions": pi.total_deductions,
            "total_contributions": pi.total_contributions,
            "net_pay": pi.net_pay,
        })
    return rows


async def _query_salary_grades(db: AsyncSession, tenant_id: UUID, **kwargs) -> List[Dict[str, Any]]:
    stmt = select(SalaryGrade).where(SalaryGrade.tenant_id == tenant_id).order_by(SalaryGrade.sort_order)
    result = await db.execute(stmt)
    rows = []
    for sg in result.scalars().all():
        rows.append({
            "code": sg.code,
            "name": sg.name,
            "description": sg.description or "",
            "monthly_rate": sg.monthly_rate,
            "daily_rate": sg.daily_rate or 0,
            "hourly_rate": sg.hourly_rate or 0,
            "is_active": "Yes" if sg.is_active else "No",
        })
    return rows


async def _query_organization(db: AsyncSession, tenant_id: UUID, **kwargs) -> List[Dict[str, Any]]:
    name_format = kwargs.get("name_format") or "first_last"
    Head = aliased(User)
    Deputy = aliased(User)
    stmt = (
        select(OrgNode, OrgLevel.name, Head.first_name, Head.last_name, Deputy.first_name, Deputy.last_name)
        .join(OrgLevel, OrgNode.level_id == OrgLevel.id)
        .outerjoin(Head, OrgNode.head_user_id == Head.id)
        .outerjoin(Deputy, OrgNode.deputy_head_user_id == Deputy.id)
        .where(OrgNode.tenant_id == tenant_id)
        .order_by(OrgLevel.level_number, OrgNode.sort_order)
    )
    result = await db.execute(stmt)
    rows = []
    for node, level_name, h_first, h_last, d_first, d_last in result.all():
        rows.append({
            "node_name": node.name,
            "node_code": node.code or "",
            "level_name": level_name,
            "head_name": _fmt_name(h_first, h_last, name_format) if h_first is not None else "",
            "deputy_head_name": _fmt_name(d_first, d_last, name_format) if d_first is not None else "",
            "is_active": "Yes" if node.is_active else "No",
        })
    return rows


async def _query_leave_credits(db: AsyncSession, tenant_id: UUID, **kwargs) -> List[Dict[str, Any]]:
    name_format = kwargs.get("name_format") or "first_last"
    stmt = (
        select(LeaveCreditAdjustment, User.first_name, User.last_name)
        .join(User, LeaveCreditAdjustment.employee_id == User.id)
        .where(LeaveCreditAdjustment.tenant_id == tenant_id)
    )
    stmt = _scoped(stmt, LeaveCreditAdjustment.employee_id, kwargs)
    result = await db.execute(stmt.order_by(LeaveCreditAdjustment.created_at.desc()))
    rows = []
    for adj, first_name, last_name in result.all():
        rows.append({
            "employee_id": adj.employee_id,
            "employee_name": _fmt_name(first_name, last_name, name_format),
            "adjustment_type": adj.adjustment_type,
            "leave_type": adj.leave_type or "",
            "credits": adj.credits,
            "source_type": adj.source_type or "",
            "notes": adj.notes or "",
            "created_at": str(adj.created_at) if adj.created_at else "",
        })
    return rows


# ── Registry ─────────────────────────────────────────────────────

DATA_SOURCES: Dict[str, Dict[str, Any]] = {
    "employees": {
        "label": "Employees",
        "description": "Employee master list with profile details",
        "columns": EMPLOYEES_COLUMNS,
        "query": _query_employees,
    },
    "schedules": {
        "label": "Schedules",
        "description": "Employee shift schedules with times and status",
        "columns": SCHEDULES_COLUMNS,
        "query": _query_schedules,
    },
    "attendance": {
        "label": "Attendance Records",
        "description": "Daily attendance with tardiness and overtime tracking",
        "columns": ATTENDANCE_COLUMNS,
        "query": _query_attendance,
    },
    "leave_applications": {
        "label": "Leave Applications",
        "description": "Employee leave requests and their status",
        "columns": LEAVE_COLUMNS,
        "query": _query_leave,
    },
    "overtime_logs": {
        "label": "Overtime Logs",
        "description": "Overtime entries with pay and credit calculations",
        "columns": OVERTIME_COLUMNS,
        "query": _query_overtime,
    },
    "tardiness_records": {
        "label": "Tardiness Records",
        "description": "Late arrivals with resolutions and deductions",
        "columns": TARDINESS_COLUMNS,
        "query": _query_tardiness,
    },
    "payroll_items": {
        "label": "Payroll",
        "description": "Payroll computation results per employee per period",
        "columns": PAYROLL_COLUMNS,
        "query": _query_payroll,
    },
    "salary_grades": {
        "label": "Salary Grades",
        "description": "Salary grade definitions and rates",
        "columns": SALARY_GRADES_COLUMNS,
        "query": _query_salary_grades,
    },
    "organization": {
        "label": "Organization Structure",
        "description": "Organizational hierarchy nodes and leadership",
        "columns": ORGANIZATION_COLUMNS,
        "query": _query_organization,
    },
    "leave_credit_adjustments": {
        "label": "Leave Credit Adjustments",
        "description": "Leave credit additions and deductions from OT conversion, tardiness, etc.",
        "columns": LEAVE_CREDITS_COLUMNS,
        "query": _query_leave_credits,
    },
}


async def tenant_columns(db: AsyncSession, tenant_id: UUID, source_key: str) -> List[Dict[str, Any]]:
    """A source's columns as this tenant sees them.

    The employees source is the one that varies: Personnel Number carries the
    company's own name for it, and every company-defined employee field is a
    column. Whether a viewer may see a custom field's VALUES is decided when
    the report runs, per employee, not here.
    """
    source = DATA_SOURCES.get(source_key)
    if not source:
        return []
    cols = [dict(c) for c in source["columns"]]
    if source_key != "employees":
        return cols
    from app.services.employee_field_service import custom_field_columns
    from app.services.user_service import UserService

    label = await UserService.employee_number_label(db, tenant_id)
    for c in cols:
        if c["key"] == "personnel_number":
            c["label"] = label
    for d in await custom_field_columns(db, tenant_id):
        cols.append({
            "key": CUSTOM_FIELD_PREFIX + d["key"],
            "label": d["label"],
            "type": _CUSTOM_FIELD_TYPES.get(d["type"], "string"),
            "is_custom": True,
        })
    return cols


# ── Salary classification ────────────────────────────────────────
# Single source of truth for what counts as "salary/pay" data. Any export that
# touches these is gated behind an active salary-viewer enrollment (mirrors the
# require_salary_access() gate used everywhere else). Note this deliberately
# includes pay fields hidden inside otherwise-innocuous sources (overtime pay,
# tardiness deductions), not just the obvious Payroll / Salary Grades sources.

# Whole sources where every row is salary-sensitive.
SALARY_SOURCES = {"payroll_items", "salary_grades"}

# Individual columns that expose pay figures even though their source is not
# wholly salary. Keyed by source -> set of column keys.
SALARY_COLUMNS_BY_SOURCE: Dict[str, set] = {
    "overtime_logs": {"pay_multiplier", "pay_amount"},
    "tardiness_records": {"deduction_amount"},
}

# Columns that hold an actual monetary AMOUNT (denominated in the tenant
# currency). Used only for currency labelling in exports — a strict subset of
# the salary-gated columns, EXCLUDING ratios/counts like pay_multiplier and
# non-money fields in salary sources (code, name, is_active, dates).
MONETARY_COLUMNS_BY_SOURCE: Dict[str, set] = {
    "payroll_items": {
        "base_pay", "overtime_pay", "gross_pay",
        "total_deductions", "total_contributions", "net_pay",
    },
    "salary_grades": {"monthly_rate", "daily_rate", "hourly_rate"},
    "overtime_logs": {"pay_amount"},
    "tardiness_records": {"deduction_amount"},
}


def _field(key: str) -> str:
    from app.services.export_pipeline import field_of

    return field_of(key)


def is_salary_source(source_key: str) -> bool:
    return source_key in SALARY_SOURCES


def column_is_salary(source_key: str, column_key: str) -> bool:
    """True if (source, column) exposes pay data and must be enrollment-gated.

    `column_key` may be an instance id ('pay_amount::2'): showing a pay column
    twice is still showing pay."""
    if source_key in SALARY_SOURCES:
        return True
    return _field(column_key) in SALARY_COLUMNS_BY_SOURCE.get(source_key, set())


def column_is_monetary(source_key: str, column_key: str) -> bool:
    """True if (source, column) holds a currency-denominated amount. Narrower
    than column_is_salary — used for currency labelling, not access control."""
    return _field(column_key) in MONETARY_COLUMNS_BY_SOURCE.get(source_key, set())


def request_touches_salary(data_source: str, columns: List[str]) -> bool:
    """Whether a single-source export request references any salary data.

    `columns` are bare column keys or instance ids (namespace already stripped
    by the caller for single-source requests)."""
    if data_source in SALARY_SOURCES:
        return True
    salary_cols = SALARY_COLUMNS_BY_SOURCE.get(data_source, set())
    return any(_field(c) in salary_cols for c in columns)


def namespaced_columns_touch_salary(namespaced_columns: List[str]) -> bool:
    """Whether a multi-source request (columns like 'overtime_logs.pay_amount')
    references any salary data."""
    for nc in namespaced_columns:
        if "." not in nc:
            continue
        src, col = nc.split(".", 1)
        if column_is_salary(src, col):
            return True
    return False


def spec_touches_salary(spec: Dict[str, Any]) -> bool:
    """Whether a whole report touches pay data ANYWHERE, not just in its columns.

    Checking only the displayed columns let a report filter, sort, group or
    total on a pay column, or compute one into a formula column, and so reveal
    pay without ever showing the column itself.
    """
    import re

    data_source = spec.get("data_source") or ""
    refs: List[str] = list(spec.get("columns") or [])
    refs += [f.get("column", "") for f in (spec.get("filters") or []) if isinstance(f, dict)]
    refs += [s.get("column", "") for s in (spec.get("sorts") or []) if isinstance(s, dict)]
    if spec.get("sort_by"):
        refs.append(spec["sort_by"])
    refs += list(spec.get("group_by") or [])
    refs += [a.get("column", "") for a in (spec.get("aggregations") or []) if isinstance(a, dict)]
    for cc in spec.get("custom_columns") or []:
        formula = cc.get("formula", "") if isinstance(cc, dict) else getattr(cc, "formula", "")
        refs += re.findall(r"\{([^{}]*)\}", formula or "")
    refs = [r for r in refs if r]
    if data_source == "multi":
        return namespaced_columns_touch_salary(refs)
    if data_source in SALARY_SOURCES:
        return True
    return request_touches_salary(data_source, refs)


def get_sources_metadata() -> List[Dict[str, Any]]:
    """Return list of data sources with their column definitions (no query functions).

    Each source is annotated with `is_salary` and each salary column with
    `is_salary` so the UI can flag/gate them without duplicating the rules."""
    result = []
    for key, source in DATA_SOURCES.items():
        result.append(_source_meta(key, source, source["columns"]))
    return result


def _source_meta(key: str, source: Dict[str, Any], columns: List[Dict[str, Any]]) -> Dict[str, Any]:
    cols = []
    for c in columns:
        col = dict(c)
        col["is_salary"] = column_is_salary(key, c["key"])
        cols.append(col)
    return {
        "key": key,
        "label": source["label"],
        "description": source["description"],
        "is_salary": is_salary_source(key),
        "columns": cols,
        "options": SOURCE_OPTIONS.get(key, []),
    }


async def tenant_sources_metadata(db: AsyncSession, tenant_id: UUID) -> List[Dict[str, Any]]:
    """get_sources_metadata, with this tenant's own column names and fields."""
    out = []
    for key, source in DATA_SOURCES.items():
        out.append(_source_meta(key, source, await tenant_columns(db, tenant_id, key)))
    return out


def get_source(key: str) -> Optional[Dict[str, Any]]:
    """Get a single data source by key."""
    return DATA_SOURCES.get(key)
