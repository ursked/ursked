from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import get_current_user, require_permission
from app.models.attendance import TimePunch
from app.models.settings import AppSettings
from app.models.user import User
from app.models.work_site import WorkSite
from app.schemas.attendance import (
    AttendanceRecordCreate,
    AttendanceRecordResponse,
    AttendanceRecordUpdate,
    ConversionLeaveType,
    OvertimeLogResponse,
    OvertimeApproveRequest,
    OvertimeConvertRequest,
    PunchLocationRequest,
    PunchRequest,
    SelfTimeEntry,
    SuggestedDeduction,
    TardinessRecordResponse,
    TardinessResolveRequest,
    TimeclockShiftInfo,
    TimeclockTodayResponse,
    TimePunchResponse,
)
from app.services import audit_service
from app.services.access_scope import assert_manages, managed_employee_ids
from app.services.attendance_service import AttendanceService
from app.services.email_service import EmailService
from app.services.overtime_service import OvertimeService
from app.services.tardiness_service import TardinessService
from app.services.timeclock_service import TimeclockError, TimeclockService, _tenant_now

router = APIRouter(prefix="/attendance", tags=["attendance"])

# Attendance, overtime and tardiness sit under the schedules module of the
# permission matrix (view to see other people's, edit to record, correct and
# decide). Scope is separate: roles outside FULL_SCOPE_ROLES["schedules"] see
# and act on the teams they head only, so a manager records attendance for
# their own people and nobody else's.
MODULE = "schedules"


async def _scope(db: AsyncSession, user: User):
    """Employee ids the caller may see or act on here; None = everyone."""
    return await managed_employee_ids(db, user, MODULE)


async def _refuse_if_locked(db: AsyncSession, tenant_id, employee_id: int, d: date) -> None:
    """A day an approved or finalized payroll run has paid cannot change."""
    from app.services.payroll_service import PayrollService

    locked = await PayrollService.locked_periods_for(db, tenant_id, [(employee_id, d)])
    if locked:
        period = locked[(employee_id, d)]
        emp = await db.get(User, employee_id)
        name = f"{emp.first_name} {emp.last_name}".strip() if emp else "this employee"
        raise HTTPException(409, PayrollService.locked_message(period, name, d))


def _notify_overtime_decision(log, reviewer, decision: str, notes: str = "") -> None:
    """Fire-and-forget an overtime decision email to the employee. Looks the
    employee up in its own session so the request path stays fast."""
    from app.models.user import User as UserModel

    hours = f"{(log.overtime_minutes or 0) / 60:.2f}"
    ot_date = log.date.isoformat() if log.date else ""
    reviewer_name = f"{reviewer.first_name} {reviewer.last_name}"
    emp_id = log.employee_id

    async def _factory(db):
        emp = await db.get(UserModel, emp_id)
        if not emp or not emp.email:
            return
        await EmailService.send_overtime_decision_email(
            db,
            to_email=emp.email,
            employee_name=f"{emp.first_name} {emp.last_name}",
            decision=decision,
            ot_date=ot_date,
            hours=hours,
            reviewer_name=reviewer_name,
            notes=notes or "",
        )

    EmailService.fire_and_forget(_factory)


# ── Helper to build response with employee name ───────────────────

async def _attendance_response(record, db) -> dict:
    data = {
        "id": record.id,
        "tenant_id": str(record.tenant_id),
        "employee_id": record.employee_id,
        "shift_id": record.shift_id,
        "date": record.date,
        "actual_start_time": record.actual_start_time,
        "actual_end_time": record.actual_end_time,
        "scheduled_start_time": record.scheduled_start_time,
        "scheduled_end_time": record.scheduled_end_time,
        "hours_worked": record.hours_worked,
        "tardiness_minutes": record.tardiness_minutes,
        "overtime_minutes": record.overtime_minutes,
        "undertime_minutes": record.undertime_minutes,
        "status": record.status,
        "status_override": record.status_override,
        "notes": record.notes,
        "recorded_by": record.recorded_by,
        # Returned so the list can badge entries the employee typed in
        # themselves; the column existed but the response dropped it.
        "self_reported": bool(record.self_reported),
        "is_rest_day_work": bool(record.is_rest_day_work),
        "auto_marked": bool(record.auto_marked),
        "excused_by_leave_id": record.excused_by_leave_id,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }
    emp = await db.get(User, record.employee_id)
    if emp:
        data["employee_name"] = f"{emp.first_name} {emp.last_name}"
    if record.recorded_by:
        rec = await db.get(User, record.recorded_by)
        if rec:
            data["recorder_name"] = f"{rec.first_name} {rec.last_name}"
    return data


async def _overtime_response(log, db, can_see_pay: bool) -> dict:
    data = {
        "id": log.id,
        "tenant_id": str(log.tenant_id),
        "employee_id": log.employee_id,
        "attendance_record_id": log.attendance_record_id,
        "date": log.date,
        "overtime_minutes": log.overtime_minutes,
        "overtime_category_id": log.overtime_category_id,
        "log_type": log.log_type,
        # The multiplier is the overtime policy (1.25x, 2x), the same for
        # everyone in a category, so it is structure. The amount is minutes x
        # this employee's rate x multiplier: a salary figure, viewers only.
        "pay_multiplier": log.pay_multiplier,
        "pay_amount": log.pay_amount if can_see_pay else None,
        "amount_hidden": (log.pay_amount is not None) and not can_see_pay,
        "leave_credits_earned": log.leave_credits_earned,
        "status": log.status,
        "approved_by": log.approved_by,
        "approved_at": log.approved_at,
        "payroll_period_id": log.payroll_period_id,
        "paid_at": log.paid_at,
        "notes": log.notes,
        "created_at": log.created_at,
        "updated_at": log.updated_at,
    }
    emp = await db.get(User, log.employee_id)
    if emp:
        data["employee_name"] = f"{emp.first_name} {emp.last_name}"
    if log.overtime_category_id:
        from app.models.leave import LeaveType, OvertimeCategory
        cat = await db.get(OvertimeCategory, log.overtime_category_id)
        if cat:
            data["overtime_category_name"] = cat.name
            if cat.leave_credit_type_id:
                lt = await db.get(LeaveType, cat.leave_credit_type_id)
                if lt:
                    data["default_leave_type"] = lt.code
    return data


async def _tardiness_response(record, db, can_see_pay: bool) -> dict:
    data = {
        "id": record.id,
        "tenant_id": str(record.tenant_id),
        "employee_id": record.employee_id,
        "attendance_record_id": record.attendance_record_id,
        "date": record.date,
        "tardiness_minutes": record.tardiness_minutes,
        "resolution_type": record.resolution_type,
        # A deduction amount is minutes x the employee's pay rate, so it is a
        # salary figure: shown only to salary viewers, like every other one.
        "deduction_amount": record.deduction_amount if can_see_pay else None,
        "amount_hidden": (record.deduction_amount is not None) and not can_see_pay,
        "leave_credits_deducted": record.leave_credits_deducted,
        "policy_rule_id": record.policy_rule_id,
        "recorded_by": record.recorded_by,
        "notes": record.notes,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }
    emp = await db.get(User, record.employee_id)
    if emp:
        data["employee_name"] = f"{emp.first_name} {emp.last_name}"
    return data


async def _is_salary_viewer(db, user: User) -> bool:
    from app.services.salary_enrollment_service import SalaryEnrollmentService

    return await SalaryEnrollmentService.is_viewer(db, user.tenant_id, user.id)


# ── Overtime Logs (must be before /{record_id} to avoid route conflict) ──

@router.get("/overtime", response_model=List[OvertimeLogResponse])
async def list_overtime_logs(
    employee_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(require_permission(MODULE, "view")),
    db: AsyncSession = Depends(get_db),
):
    logs, total = await OvertimeService.list_overtime_logs(
        db, current_user.tenant_id, employee_id, status, skip, limit,
        employee_ids=await _scope(db, current_user),
    )
    can_see_pay = await _is_salary_viewer(db, current_user)
    return [await _overtime_response(log, db, can_see_pay) for log in logs]


@router.get("/overtime/conversion-leave-types", response_model=List[ConversionLeaveType])
async def list_conversion_leave_types(
    current_user: User = Depends(require_permission(MODULE, "view")),
    db: AsyncSession = Depends(get_db),
):
    """Leave types overtime can be converted into (for the convert dialog)."""
    types = await OvertimeService.conversion_leave_types(db, current_user.tenant_id)
    return [{"code": t.code, "name": t.name} for t in types]


async def _scoped_log(db, user, log_id):
    log = await OvertimeService.get_overtime_log(db, user.tenant_id, log_id)
    if log is not None:
        await assert_manages(db, user, [log.employee_id], MODULE, own="overtime")
    return log


@router.post("/overtime/{log_id}/approve", response_model=OvertimeLogResponse)
async def approve_overtime(
    log_id: int,
    data: OvertimeApproveRequest,
    current_user: User = Depends(require_permission(MODULE, "edit")),
    db: AsyncSession = Depends(get_db),
):
    await _scoped_log(db, current_user, log_id)
    log = await OvertimeService.approve_overtime(
        db, current_user.tenant_id, log_id, current_user.id, data.notes
    )
    if not log:
        raise HTTPException(400, "This overtime is no longer waiting for a decision.")
    await db.commit()
    _notify_overtime_decision(log, current_user, "approved", data.notes)
    return await _overtime_response(log, db, await _is_salary_viewer(db, current_user))


@router.post("/overtime/{log_id}/reject", response_model=OvertimeLogResponse)
async def reject_overtime(
    log_id: int,
    data: OvertimeApproveRequest,
    current_user: User = Depends(require_permission(MODULE, "edit")),
    db: AsyncSession = Depends(get_db),
):
    await _scoped_log(db, current_user, log_id)
    log = await OvertimeService.reject_overtime(
        db, current_user.tenant_id, log_id, current_user.id, data.notes
    )
    if not log:
        raise HTTPException(400, "This overtime is no longer waiting for a decision.")
    await db.commit()
    _notify_overtime_decision(log, current_user, "rejected", data.notes)
    return await _overtime_response(log, db, await _is_salary_viewer(db, current_user))


@router.post("/overtime/{log_id}/convert", response_model=OvertimeLogResponse)
async def convert_overtime_to_leave(
    log_id: int,
    data: OvertimeConvertRequest,
    current_user: User = Depends(require_permission(MODULE, "edit")),
    db: AsyncSession = Depends(get_db),
):
    await _scoped_log(db, current_user, log_id)
    try:
        log = await OvertimeService.convert_to_leave(
            db, current_user.tenant_id, log_id, current_user.id, data.leave_type, data.notes
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not log:
        raise HTTPException(400, "Only approved overtime can be converted to leave.")
    await db.commit()
    _notify_overtime_decision(log, current_user, "converted", data.notes)
    return await _overtime_response(log, db, await _is_salary_viewer(db, current_user))


# ── Tardiness Records (must be before /{record_id} to avoid route conflict) ──

@router.get("/tardiness", response_model=List[TardinessRecordResponse])
async def list_tardiness_records(
    employee_id: Optional[int] = Query(None),
    resolution_type: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(require_permission(MODULE, "view")),
    db: AsyncSession = Depends(get_db),
):
    records, total = await TardinessService.list_tardiness_records(
        db, current_user.tenant_id, employee_id, resolution_type, skip, limit,
        employee_ids=await _scope(db, current_user),
    )
    can_see_pay = await _is_salary_viewer(db, current_user)
    return [await _tardiness_response(r, db, can_see_pay) for r in records]


@router.get("/tardiness/{record_id}/suggested-deduction", response_model=SuggestedDeduction)
async def suggested_tardiness_deduction(
    record_id: int,
    current_user: User = Depends(require_permission(MODULE, "edit")),
    db: AsyncSession = Depends(get_db),
):
    """The default "salary deduction" for a late arrival: minutes late x the
    employee's per-minute rate. Salary viewers see the figure (and may change
    it); anyone else is told it will be worked out when they save."""
    record = await TardinessService.get_tardiness_record(db, current_user.tenant_id, record_id)
    if not record:
        raise HTTPException(404, "Tardiness record not found")
    await assert_manages(db, current_user, [record.employee_id], MODULE)
    amount = await TardinessService.default_deduction(
        db, current_user.tenant_id, record.employee_id, record.tardiness_minutes, record.date
    )
    visible = await _is_salary_viewer(db, current_user)
    return {
        "minutes": record.tardiness_minutes,
        "amount": amount if visible else None,
        "amount_hidden": not visible,
        "has_salary": amount is not None,
    }


@router.post("/tardiness/{record_id}/resolve", response_model=TardinessRecordResponse)
async def resolve_tardiness(
    record_id: int,
    data: TardinessResolveRequest,
    current_user: User = Depends(require_permission(MODULE, "edit")),
    db: AsyncSession = Depends(get_db),
):
    existing = await TardinessService.get_tardiness_record(db, current_user.tenant_id, record_id)
    if not existing:
        raise HTTPException(404, "Tardiness record not found")
    await assert_manages(db, current_user, [existing.employee_id], MODULE, own="attendance")
    await _refuse_if_locked(db, current_user.tenant_id, existing.employee_id, existing.date)
    can_see_pay = await _is_salary_viewer(db, current_user)
    # Only a salary viewer may type an amount; for anyone else it is derived.
    amount = data.deduction_amount if can_see_pay else None
    record = await TardinessService.resolve_tardiness(
        db,
        current_user.tenant_id,
        record_id,
        data.resolution_type,
        current_user.id,
        amount,
        data.leave_type,
        data.notes,
    )
    if not record:
        raise HTTPException(404, "Tardiness record not found")
    if data.resolution_type == "salary_deduction" and record.deduction_amount is None:
        raise HTTPException(
            400,
            "This employee has no salary on that date, so there is nothing to deduct from. "
            "Assign a salary under Finances first, or choose another resolution.",
        )
    await db.commit()
    return await _tardiness_response(record, db, can_see_pay)


# ── Attendance Records ─────────────────────────────────────────────

@router.post("", response_model=AttendanceRecordResponse, status_code=201)
async def record_attendance(
    data: AttendanceRecordCreate,
    current_user: User = Depends(require_permission(MODULE, "edit")),
    db: AsyncSession = Depends(get_db),
):
    """Record attendance for an employee. Requires schedules:edit permission
    and, for a team manager, that the employee is in a team they manage.

    Upserts: one record per employee per day is a database constraint, so
    recording the same day twice is a correction, not an error.
    """
    await assert_manages(db, current_user, [data.employee_id], MODULE, own="attendance")
    await _refuse_if_locked(db, current_user.tenant_id, data.employee_id, data.date)
    try:
        record = await AttendanceService.upsert_attendance(
            db=db,
            tenant_id=current_user.tenant_id,
            employee_id=data.employee_id,
            attendance_date=data.date,
            actual_start=data.actual_start_time,
            actual_end=data.actual_end_time,
            notes=data.notes,
            recorded_by=current_user.id,
        )
        await db.commit()
        return await _attendance_response(record, db)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("", response_model=List[AttendanceRecordResponse])
async def list_attendance(
    employee_id: Optional[int] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    status: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(require_permission(MODULE, "view")),
    db: AsyncSession = Depends(get_db),
):
    records, total = await AttendanceService.list_attendance(
        db, current_user.tenant_id, employee_id, start_date, end_date, status, skip, limit,
        employee_ids=await _scope(db, current_user),
    )
    return [await _attendance_response(r, db) for r in records]


# NOTE: this must stay ABOVE GET /{record_id}. FastAPI matches routes in
# registration order, and "punches" is not an int, so a parameterised route
# declared first would swallow this path and 422.
@router.get("/punches", response_model=List[TimePunchResponse])
async def list_punches(
    employee_id: Optional[int] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    flagged_only: bool = Query(False, description="Only punches needing a look: no location, outside the geofence, a large clock skew, or closed automatically."),
    limit: int = Query(200, le=1000),
    current_user: User = Depends(require_permission(MODULE, "view")),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(TimePunch).where(TimePunch.tenant_id == current_user.tenant_id)
    scope = await _scope(db, current_user)
    if scope is not None:
        stmt = stmt.where(TimePunch.employee_id.in_(scope))
    if employee_id is not None:
        stmt = stmt.where(TimePunch.employee_id == employee_id)
    if start_date is not None:
        stmt = stmt.where(TimePunch.business_date >= start_date)
    if end_date is not None:
        stmt = stmt.where(TimePunch.business_date <= end_date)
    if flagged_only:
        stmt = stmt.where(
            ((TimePunch.latitude.is_(None)) & (TimePunch.location_status != "not_required"))
            | (TimePunch.geofence_status.in_(["outside", "unverified"]))
            | (TimePunch.clock_skew_seconds > 300)
            | (TimePunch.clock_skew_seconds < -300)
            | (TimePunch.auto_closed == True)  # noqa: E712
        )
    stmt = stmt.order_by(TimePunch.punched_at.desc()).limit(limit)
    punches = list((await db.execute(stmt)).scalars().all())

    names = {}
    emp_ids = {p.employee_id for p in punches}
    if emp_ids:
        for uid, fn, ln in (await db.execute(
            select(User.id, User.first_name, User.last_name).where(User.id.in_(emp_ids))
        )).all():
            names[uid] = f"{fn} {ln}"
    sites = {
        s.id: s.name for s in (await db.execute(
            select(WorkSite).where(WorkSite.tenant_id == current_user.tenant_id)
        )).scalars().all()
    }
    out = []
    for p in punches:
        row = TimePunchResponse.model_validate(p).model_dump()
        row["employee_name"] = names.get(p.employee_id)
        row["work_site_name"] = sites.get(p.work_site_id) if p.work_site_id else None
        out.append(row)
    return out


@router.get("/{record_id}", response_model=AttendanceRecordResponse)
async def get_attendance(
    record_id: int,
    current_user: User = Depends(require_permission(MODULE, "view")),
    db: AsyncSession = Depends(get_db),
):
    record = await AttendanceService.get_attendance(db, current_user.tenant_id, record_id)
    if not record:
        raise HTTPException(404, "Attendance record not found")
    scope = await _scope(db, current_user)
    if scope is not None and record.employee_id not in scope:
        raise HTTPException(404, "Attendance record not found")
    return await _attendance_response(record, db)


@router.put("/{record_id}", response_model=AttendanceRecordResponse)
async def update_attendance(
    record_id: int,
    data: AttendanceRecordUpdate,
    request: Request,
    current_user: User = Depends(require_permission(MODULE, "edit")),
    db: AsyncSession = Depends(get_db),
):
    """Correct an attendance record. A reason is required and the change is
    written to the audit log with what the day looked like before and after,
    because it changes what payroll pays."""
    record = await AttendanceService.get_attendance(db, current_user.tenant_id, record_id)
    if not record:
        raise HTTPException(404, "Attendance record not found")
    await assert_manages(db, current_user, [record.employee_id], MODULE, own="attendance")
    await _refuse_if_locked(db, current_user.tenant_id, record.employee_id, record.date)

    fields = ("actual_start_time", "actual_end_time", "status", "status_override", "notes",
              "hours_worked", "tardiness_minutes", "overtime_minutes", "undertime_minutes")
    before = {f: getattr(record, f) for f in fields}
    changes = data.model_dump(exclude_unset=True)
    reason = changes.pop("reason", None)
    record = await AttendanceService.update_attendance(
        db, current_user.tenant_id, record_id, changes
    )
    after = {f: getattr(record, f) for f in fields}
    audit_service.record(
        db, actor=current_user, action="attendance_corrected",
        resource_type="attendance_record", resource_id=record.id,
        details={
            "employee_id": record.employee_id,
            "date": record.date,
            "reason": reason,
            "changes": audit_service.diff(before, after),
        },
        request=request,
    )
    await db.commit()
    return await _attendance_response(record, db)


# ── Self-service time entry ──────────────────────────────────────────

@router.post("/my", response_model=AttendanceRecordResponse)
async def submit_own_time(
    data: SelfTimeEntry,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Employee submits their OWN start/end time for a date.

    CE subset: any authenticated employee can record their own hours. NOT a
    clock-in kiosk (no real-time punch, no biometric). The manager/admin can
    still override via the regular attendance endpoints.
    """
    await _refuse_if_locked(db, current_user.tenant_id, current_user.id, data.date)
    try:
        record = await AttendanceService.upsert_attendance(
            db,
            tenant_id=current_user.tenant_id,
            employee_id=current_user.id,
            attendance_date=data.date,
            actual_start=data.actual_start_time,
            actual_end=data.actual_end_time,
            notes=data.notes,
            recorded_by=current_user.id,
            self_reported=True,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    return await _attendance_response(record, db)


# ── Time clock ───────────────────────────────────────────────────────────────
#
# Employee self-service, so these sit behind get_current_user rather than
# require_permission("schedules", ...) — the `employee` role does not hold that
# permission, and an employee must be able to clock themselves in. Same gate as
# POST /attendance/my.


@router.post("/punch", response_model=TimePunchResponse, status_code=201)
async def punch_clock(
    data: PunchRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Clock in or out.

    Always records the punch when the state allows it. A missing or refused
    location is flagged, never a reason to refuse someone's time.
    """
    try:
        punch = await TimeclockService.punch(
            db,
            tenant_id=current_user.tenant_id,
            employee_id=current_user.id,
            punch_type=data.punch_type,
            latitude=data.latitude,
            longitude=data.longitude,
            accuracy_m=data.accuracy_m,
            location_error=data.location_error,
            client_time=data.client_time,
            notes=data.notes,
            source="web",
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            recorded_by=current_user.id,
        )
    except TimeclockError as e:
        # 409 rather than 400 when the client simply disagrees about the current
        # state, so a stale tab can resync instead of showing a hard error.
        raise HTTPException(409 if e.current_state else 400, e.message)
    await db.commit()
    await db.refresh(punch)
    return punch


@router.get("/my/today", response_model=TimeclockTodayResponse)
async def my_timeclock_today(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Everything the time-clock screen needs, in one call."""
    settings = (
        await db.execute(
            select(AppSettings).where(AppSettings.tenant_id == current_user.tenant_id)
        )
    ).scalar_one_or_none()
    enabled = bool(settings and settings.timeclock_enabled)

    open_punch = await TimeclockService.open_punch(db, current_user.tenant_id, current_user.id)
    # The tenant's clock, not the server's: "today" at 01:00 in Manila is not
    # today in UTC.
    utc_now, local_now = _tenant_now((settings.timezone if settings else None) or "UTC")
    if open_punch is not None:
        _, deadline = await TimeclockService.auto_close_times(db, open_punch, settings)
        if utc_now >= deadline:
            # Forgotten and past its grace: the next clock-in closes it at its
            # scheduled end, so offer a clock-in rather than a 20-hour clock-out.
            open_punch = None

    # The day being shown is the open punch's day when one is running — a night
    # shift worker at 01:00 is still on yesterday's shift and should see it.
    if open_punch is not None:
        business_date = open_punch.business_date
    else:
        business_date = await TimeclockService._resolve_business_date(
            db, current_user.tenant_id, current_user.id,
            local_now, "in", None,
        )

    punches = await TimeclockService.punches_for_day(
        db, current_user.tenant_id, current_user.id, business_date
    )
    shifts = await TimeclockService._day_shifts(
        db, current_user.tenant_id, current_user.id, business_date
    )
    shift_info = []
    for s in shifts:
        mode, pinned = await TimeclockService._expectation(db, current_user.tenant_id, s)
        shift_info.append(TimeclockShiftInfo(
            shift_id=s.id,
            sequence_number=s.sequence_number or 1,
            start_time=s.start_time,
            end_time=s.end_time,
            status=s.status,
            work_arrangement=s.work_arrangement,
            geofence_mode=mode,
            work_site_id=pinned,
        ))

    _, _, hours = TimeclockService._derive_times(punches)
    return TimeclockTodayResponse(
        timeclock_enabled=enabled,
        require_location=bool(settings and settings.timeclock_require_location),
        grace_minutes=(settings.timeclock_location_grace_minutes if settings else 0) or 0,
        business_date=business_date,
        server_time=utc_now,
        next_action="clock_out" if open_punch is not None else "clock_in",
        open_punch=open_punch,
        punches=punches,
        shifts=shift_info,
        hours_today=hours,
    )


@router.post("/punch/{punch_id}/location", response_model=TimePunchResponse)
async def attach_punch_location(
    punch_id: int,
    data: PunchLocationRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Attach a location to your own punch, within the grace window.

    Scoped to the caller's own punches: this is a correction to your record, not
    a way to annotate somebody else's.
    """
    try:
        punch = await TimeclockService.attach_location(
            db,
            tenant_id=current_user.tenant_id,
            employee_id=current_user.id,
            punch_id=punch_id,
            latitude=data.latitude,
            longitude=data.longitude,
            accuracy_m=data.accuracy_m,
        )
    except TimeclockError as e:
        raise HTTPException(409, e.message)
    await db.commit()
    await db.refresh(punch)
    return punch
