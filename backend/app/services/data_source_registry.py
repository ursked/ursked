"""
Registry of data sources available for tenant data export.
Each source maps to one or more database models and defines
user-friendly column metadata + a query builder function.
"""

from datetime import date, time
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.user import User
from app.models.schedule import Shift
from app.models.attendance import AttendanceRecord, OvertimeLog, TardinessRecord, LeaveCreditAdjustment
from app.models.leave import LeaveApplication, OvertimeCategory
from app.models.payroll import SalaryGrade, PayrollItem, PayrollPeriod
from app.models.org_hierarchy import OrgNode, OrgLevel
from app.models.configurable_types import ScheduleFormat


def _fmt_time(t) -> str:
    if t is None:
        return ""
    if isinstance(t, time):
        return t.strftime("%H:%M")
    return str(t)


def _add_time(base_time: time, hours: float = 0, minutes: int = 0) -> time:
    """Add hours and minutes to a time value, wrapping around midnight."""
    total_minutes = base_time.hour * 60 + base_time.minute + int(hours * 60) + minutes
    total_minutes = total_minutes % (24 * 60)
    return time(total_minutes // 60, total_minutes % 60)


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


# ── Column definitions per source ────────────────────────────────

EMPLOYEES_COLUMNS = [
    {"key": "employee_id", "label": "Employee ID", "type": "number"},
    {"key": "full_name", "label": "Employee Name", "type": "string"},
    {"key": "first_name", "label": "First Name", "type": "string"},
    {"key": "last_name", "label": "Last Name", "type": "string"},
    {"key": "email", "label": "Email", "type": "string"},
    {"key": "username", "label": "Username", "type": "string"},
    {"key": "contact_number", "label": "Contact Number", "type": "string"},
    {"key": "personnel_number", "label": "Personnel Number", "type": "string"},
    {"key": "id_number", "label": "ID Number", "type": "string"},
    {"key": "job_title", "label": "Job Title", "type": "string"},
    {"key": "rank", "label": "Rank", "type": "string"},
    {"key": "employee_type", "label": "Employee Type", "type": "string"},
    {"key": "schedule_format", "label": "Schedule Format", "type": "string"},
    {"key": "hiring_date", "label": "Hiring Date", "type": "date"},
    {"key": "is_active", "label": "Active", "type": "string"},
]

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


# ── Query builders ───────────────────────────────────────────────

async def _query_employees(db: AsyncSession, tenant_id: UUID, **kwargs) -> List[Dict[str, Any]]:
    name_format = kwargs.get("name_format", "first_last")
    stmt = select(User).where(User.tenant_id == tenant_id, User.is_superadmin == False)
    result = await db.execute(stmt)
    rows = []
    for u in result.scalars().all():
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
        })
    return rows


async def _query_schedules(db: AsyncSession, tenant_id: UUID, **kwargs) -> List[Dict[str, Any]]:
    name_format = kwargs.get("name_format", "first_last")

    # Load schedule formats for break time lookup
    sf_stmt = select(ScheduleFormat).where(ScheduleFormat.tenant_id == tenant_id)
    sf_result = await db.execute(sf_stmt)
    sf_map: Dict[str, Dict[str, Any]] = {}
    for sf in sf_result.scalars().all():
        sf_map[sf.code] = {
            "name": sf.name,
            "paid_break_minutes": sf.paid_break_minutes or 0,
            "unpaid_break_minutes": sf.unpaid_break_minutes or 0,
            "paid_break_after_hours": sf.paid_break_after_hours or 0,
            "unpaid_break_after_hours": sf.unpaid_break_after_hours or 0,
        }

    stmt = (
        select(Shift, User.first_name, User.last_name, User.schedule_format)
        .join(User, Shift.employee_id == User.id)
        .where(Shift.tenant_id == tenant_id)
        .order_by(Shift.date, User.last_name)
    )
    result = await db.execute(stmt)
    rows = []
    REST_STATUSES = {"rest_day", "rest day", "restday", "day_off", "day off"}
    for shift, first_name, last_name, user_sched_fmt in result.all():
        st = _fmt_time(shift.start_time)
        et = _fmt_time(shift.end_time)
        schedule = f"{st}-{et}" if st and et else ""
        status_lower = (shift.status or "").lower().strip()

        # DWS: "FREE" if rest day, otherwise blank (indicates working day)
        dws = "FREE" if status_lower in REST_STATUSES else ""

        # Break times from schedule format
        sf_info = sf_map.get(user_sched_fmt or "", {})
        paid_break = sf_info.get("paid_break_minutes", 0)
        unpaid_break = sf_info.get("unpaid_break_minutes", 0)
        paid_after = sf_info.get("paid_break_after_hours", 0)
        unpaid_after = sf_info.get("unpaid_break_after_hours", 0)
        sf_name = sf_info.get("name", user_sched_fmt or "")

        # Compute break start/end from shift start_time + offset
        is_working = status_lower not in REST_STATUSES and status_lower not in {"leave", "free"}
        paid_break_start = ""
        paid_break_end = ""
        unpaid_break_start = ""
        unpaid_break_end = ""
        if is_working and shift.start_time and isinstance(shift.start_time, time):
            if paid_break > 0 and paid_after > 0:
                pb_start = _add_time(shift.start_time, hours=paid_after)
                pb_end = _add_time(pb_start, minutes=paid_break)
                paid_break_start = _fmt_time(pb_start)
                paid_break_end = _fmt_time(pb_end)
            if unpaid_break > 0 and unpaid_after > 0:
                ub_start = _add_time(shift.start_time, hours=unpaid_after)
                ub_end = _add_time(ub_start, minutes=unpaid_break)
                unpaid_break_start = _fmt_time(ub_start)
                unpaid_break_end = _fmt_time(ub_end)

        rows.append({
            "employee_id": shift.employee_id,
            "employee_name": _fmt_name(first_name, last_name, name_format),
            "date": _fmt_date(shift.date),
            "start_time": st,
            "end_time": et,
            "schedule": schedule,
            "day_work_status": dws,
            "status": shift.status or "",
            "work_arrangement": shift.work_arrangement or "",
            "paid_break_minutes": paid_break,
            "paid_break_start": paid_break_start,
            "paid_break_end": paid_break_end,
            "unpaid_break_minutes": unpaid_break,
            "unpaid_break_start": unpaid_break_start,
            "unpaid_break_end": unpaid_break_end,
            "schedule_format_name": sf_name,
            "notes": shift.notes or "",
            "remarks": shift.remarks or "",
        })
    return rows


async def _query_attendance(db: AsyncSession, tenant_id: UUID, **kwargs) -> List[Dict[str, Any]]:
    name_format = kwargs.get("name_format", "first_last")
    stmt = (
        select(AttendanceRecord, User.first_name, User.last_name)
        .join(User, AttendanceRecord.employee_id == User.id)
        .where(AttendanceRecord.tenant_id == tenant_id)
        .order_by(AttendanceRecord.date.desc())
    )
    result = await db.execute(stmt)
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
    name_format = kwargs.get("name_format", "first_last")
    stmt = (
        select(LeaveApplication, User.first_name, User.last_name)
        .join(User, LeaveApplication.employee_id == User.id)
        .where(LeaveApplication.tenant_id == tenant_id)
        .order_by(LeaveApplication.created_at.desc())
    )
    result = await db.execute(stmt)
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
    name_format = kwargs.get("name_format", "first_last")
    stmt = (
        select(OvertimeLog, User.first_name, User.last_name)
        .join(User, OvertimeLog.employee_id == User.id)
        .where(OvertimeLog.tenant_id == tenant_id)
        .order_by(OvertimeLog.date.desc())
    )
    result = await db.execute(stmt)
    rows = []
    for log, first_name, last_name in result.all():
        # Get category name if present
        cat_name = ""
        if log.overtime_category_id:
            cat_result = await db.get(OvertimeCategory, log.overtime_category_id)
            if cat_result:
                cat_name = cat_result.name
        rows.append({
            "employee_id": log.employee_id,
            "employee_name": _fmt_name(first_name, last_name, name_format),
            "date": _fmt_date(log.date),
            "overtime_minutes": log.overtime_minutes,
            "overtime_category_name": cat_name,
            "pay_multiplier": log.pay_multiplier or 0,
            "pay_amount": log.pay_amount or 0,
            "leave_credits_earned": log.leave_credits_earned or 0,
            "status": log.status,
            "notes": log.notes or "",
        })
    return rows


async def _query_tardiness(db: AsyncSession, tenant_id: UUID, **kwargs) -> List[Dict[str, Any]]:
    name_format = kwargs.get("name_format", "first_last")
    stmt = (
        select(TardinessRecord, User.first_name, User.last_name)
        .join(User, TardinessRecord.employee_id == User.id)
        .where(TardinessRecord.tenant_id == tenant_id)
        .order_by(TardinessRecord.date.desc())
    )
    result = await db.execute(stmt)
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
    name_format = kwargs.get("name_format", "first_last")
    stmt = (
        select(PayrollItem, User.first_name, User.last_name, PayrollPeriod.name, PayrollPeriod.start_date, PayrollPeriod.end_date, SalaryGrade.name)
        .join(User, PayrollItem.employee_id == User.id)
        .join(PayrollPeriod, PayrollItem.payroll_period_id == PayrollPeriod.id)
        .outerjoin(SalaryGrade, PayrollItem.salary_grade_id == SalaryGrade.id)
        .where(PayrollItem.tenant_id == tenant_id)
        .order_by(PayrollPeriod.start_date.desc(), User.last_name)
    )
    result = await db.execute(stmt)
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
    name_format = kwargs.get("name_format", "first_last")
    stmt = (
        select(OrgNode, OrgLevel.name)
        .join(OrgLevel, OrgNode.level_id == OrgLevel.id)
        .where(OrgNode.tenant_id == tenant_id)
        .order_by(OrgLevel.level_number, OrgNode.sort_order)
    )
    result = await db.execute(stmt)
    rows = []
    for node, level_name in result.all():
        head_name = ""
        if node.head_user_id:
            head = await db.get(User, node.head_user_id)
            if head:
                head_name = _fmt_name(head.first_name, head.last_name, name_format)
        deputy_name = ""
        if node.deputy_head_user_id:
            deputy = await db.get(User, node.deputy_head_user_id)
            if deputy:
                deputy_name = _fmt_name(deputy.first_name, deputy.last_name, name_format)
        rows.append({
            "node_name": node.name,
            "node_code": node.code or "",
            "level_name": level_name,
            "head_name": head_name,
            "deputy_head_name": deputy_name,
            "is_active": "Yes" if node.is_active else "No",
        })
    return rows


async def _query_leave_credits(db: AsyncSession, tenant_id: UUID, **kwargs) -> List[Dict[str, Any]]:
    name_format = kwargs.get("name_format", "first_last")
    stmt = (
        select(LeaveCreditAdjustment, User.first_name, User.last_name)
        .join(User, LeaveCreditAdjustment.employee_id == User.id)
        .where(LeaveCreditAdjustment.tenant_id == tenant_id)
        .order_by(LeaveCreditAdjustment.created_at.desc())
    )
    result = await db.execute(stmt)
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


def is_salary_source(source_key: str) -> bool:
    return source_key in SALARY_SOURCES


def column_is_salary(source_key: str, column_key: str) -> bool:
    """True if (source, column) exposes pay data and must be enrollment-gated."""
    if source_key in SALARY_SOURCES:
        return True
    return column_key in SALARY_COLUMNS_BY_SOURCE.get(source_key, set())


def column_is_monetary(source_key: str, column_key: str) -> bool:
    """True if (source, column) holds a currency-denominated amount. Narrower
    than column_is_salary — used for currency labelling, not access control."""
    return column_key in MONETARY_COLUMNS_BY_SOURCE.get(source_key, set())


def request_touches_salary(data_source: str, columns: List[str]) -> bool:
    """Whether a single-source export request references any salary data.

    `columns` are bare column keys (namespace already stripped by the caller for
    single-source requests)."""
    if data_source in SALARY_SOURCES:
        return True
    salary_cols = SALARY_COLUMNS_BY_SOURCE.get(data_source, set())
    return any(c in salary_cols for c in columns)


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


def get_sources_metadata() -> List[Dict[str, Any]]:
    """Return list of data sources with their column definitions (no query functions).

    Each source is annotated with `is_salary` and each salary column with
    `is_salary` so the UI can flag/gate them without duplicating the rules."""
    result = []
    for key, source in DATA_SOURCES.items():
        cols = []
        for c in source["columns"]:
            col = dict(c)
            col["is_salary"] = column_is_salary(key, c["key"])
            cols.append(col)
        result.append({
            "key": key,
            "label": source["label"],
            "description": source["description"],
            "is_salary": is_salary_source(key),
            "columns": cols,
        })
    return result


def get_source(key: str) -> Optional[Dict[str, Any]]:
    """Get a single data source by key."""
    return DATA_SOURCES.get(key)
