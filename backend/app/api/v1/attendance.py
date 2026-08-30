from datetime import date, datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import get_current_user, require_permission
from app.models.attendance import TimePunch
from app.models.settings import AppSettings
from app.models.user import User
from app.schemas.attendance import (
    AttendanceRecordCreate,
    AttendanceRecordResponse,
    AttendanceRecordUpdate,
    OvertimeLogResponse,
    OvertimeApproveRequest,
    OvertimeConvertRequest,
    PunchLocationRequest,
    PunchRequest,
    SelfTimeEntry,
    TardinessRecordResponse,
    TardinessResolveRequest,
    TimeclockShiftInfo,
    TimeclockTodayResponse,
    TimePunchResponse,
)
from app.services.attendance_service import AttendanceService
from app.services.email_service import EmailService
from app.services.overtime_service import OvertimeService
from app.services.tardiness_service import TardinessService
from app.services.timeclock_service import TimeclockError, TimeclockService

router = APIRouter(prefix="/attendance", tags=["attendance"])


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
        "notes": record.notes,
        "recorded_by": record.recorded_by,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }
    # Get employee name
    from app.models.user import User as UserModel
    emp = await db.get(UserModel, record.employee_id)
    if emp:
        data["employee_name"] = f"{emp.first_name} {emp.last_name}"
    if record.recorded_by:
        rec = await db.get(UserModel, record.recorded_by)
        if rec:
            data["recorder_name"] = f"{rec.first_name} {rec.last_name}"
    return data


async def _overtime_response(log, db) -> dict:
    data = {
        "id": log.id,
        "tenant_id": str(log.tenant_id),
        "employee_id": log.employee_id,
        "attendance_record_id": log.attendance_record_id,
        "date": log.date,
        "overtime_minutes": log.overtime_minutes,
        "overtime_category_id": log.overtime_category_id,
        "pay_multiplier": log.pay_multiplier,
        "pay_amount": log.pay_amount,
        "leave_credits_earned": log.leave_credits_earned,
        "status": log.status,
        "approved_by": log.approved_by,
        "approved_at": log.approved_at,
        "notes": log.notes,
        "created_at": log.created_at,
        "updated_at": log.updated_at,
    }
    from app.models.user import User as UserModel
    emp = await db.get(UserModel, log.employee_id)
    if emp:
        data["employee_name"] = f"{emp.first_name} {emp.last_name}"
    if log.overtime_category_id:
        from app.models.leave import OvertimeCategory
        cat = await db.get(OvertimeCategory, log.overtime_category_id)
        if cat:
            data["overtime_category_name"] = cat.name
    return data


async def _tardiness_response(record, db) -> dict:
    data = {
        "id": record.id,
        "tenant_id": str(record.tenant_id),
        "employee_id": record.employee_id,
        "attendance_record_id": record.attendance_record_id,
        "date": record.date,
        "tardiness_minutes": record.tardiness_minutes,
        "resolution_type": record.resolution_type,
        "deduction_amount": record.deduction_amount,
        "leave_credits_deducted": record.leave_credits_deducted,
        "policy_rule_id": record.policy_rule_id,
        "recorded_by": record.recorded_by,
        "notes": record.notes,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }
    from app.models.user import User as UserModel
    emp = await db.get(UserModel, record.employee_id)
    if emp:
        data["employee_name"] = f"{emp.first_name} {emp.last_name}"
    return data


# ── Overtime Logs (must be before /{record_id} to avoid route conflict) ──

@router.get("/overtime", response_model=List[OvertimeLogResponse])
async def list_overtime_logs(
    employee_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(require_permission("schedules", "view")),
    db: AsyncSession = Depends(get_db),
):
    logs, total = await OvertimeService.list_overtime_logs(
        db, current_user.tenant_id, employee_id, status, skip, limit
    )
    results = []
    for log in logs:
        results.append(await _overtime_response(log, db))
    return results


@router.post("/overtime/{log_id}/approve", response_model=OvertimeLogResponse)
async def approve_overtime(
    log_id: int,
    data: OvertimeApproveRequest,
    current_user: User = Depends(require_permission("schedules", "edit")),
    db: AsyncSession = Depends(get_db),
):
    log = await OvertimeService.approve_overtime(
        db, current_user.tenant_id, log_id, current_user.id, data.notes
    )
    if not log:
        raise HTTPException(400, "Cannot approve: log not found or not in pending status")
    await db.commit()
    _notify_overtime_decision(log, current_user, "approved", data.notes)
    return await _overtime_response(log, db)


@router.post("/overtime/{log_id}/reject", response_model=OvertimeLogResponse)
async def reject_overtime(
    log_id: int,
    data: OvertimeApproveRequest,
    current_user: User = Depends(require_permission("schedules", "edit")),
    db: AsyncSession = Depends(get_db),
):
    log = await OvertimeService.reject_overtime(
        db, current_user.tenant_id, log_id, current_user.id, data.notes
    )
    if not log:
        raise HTTPException(400, "Cannot reject: log not found or not in pending status")
    await db.commit()
    _notify_overtime_decision(log, current_user, "rejected", data.notes)
    return await _overtime_response(log, db)


@router.post("/overtime/{log_id}/convert", response_model=OvertimeLogResponse)
async def convert_overtime_to_leave(
    log_id: int,
    data: OvertimeConvertRequest,
    current_user: User = Depends(require_permission("schedules", "edit")),
    db: AsyncSession = Depends(get_db),
):
    log = await OvertimeService.convert_to_leave(
        db, current_user.tenant_id, log_id, current_user.id, data.leave_type, data.notes
    )
    if not log:
        raise HTTPException(400, "Cannot convert: log not found or not in approved status")
    await db.commit()
    _notify_overtime_decision(log, current_user, "converted", data.notes)
    return await _overtime_response(log, db)


# ── Tardiness Records (must be before /{record_id} to avoid route conflict) ──

@router.get("/tardiness", response_model=List[TardinessRecordResponse])
async def list_tardiness_records(
    employee_id: Optional[int] = Query(None),
    resolution_type: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(require_permission("schedules", "view")),
    db: AsyncSession = Depends(get_db),
):
    records, total = await TardinessService.list_tardiness_records(
        db, current_user.tenant_id, employee_id, resolution_type, skip, limit
    )
    results = []
    for r in records:
        results.append(await _tardiness_response(r, db))
    return results


@router.post("/tardiness/{record_id}/resolve", response_model=TardinessRecordResponse)
async def resolve_tardiness(
    record_id: int,
    data: TardinessResolveRequest,
    current_user: User = Depends(require_permission("schedules", "edit")),
    db: AsyncSession = Depends(get_db),
):
    record = await TardinessService.resolve_tardiness(
        db,
        current_user.tenant_id,
        record_id,
        data.resolution_type,
        current_user.id,
        data.deduction_amount,
        data.leave_type,
        data.notes,
    )
    if not record:
        raise HTTPException(404, "Tardiness record not found")
    await db.commit()
    return await _tardiness_response(record, db)


# ── Attendance Records ─────────────────────────────────────────────

@router.post("", response_model=AttendanceRecordResponse, status_code=201)
async def record_attendance(
    data: AttendanceRecordCreate,
    current_user: User = Depends(require_permission("schedules", "edit")),
    db: AsyncSession = Depends(get_db),
):
    """Record attendance for an employee. Requires schedules:edit permission.

    Upserts: one record per employee per day is a database constraint, so
    recording the same day twice is a correction, not an error.
    """
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
    current_user: User = Depends(require_permission("schedules", "view")),
    db: AsyncSession = Depends(get_db),
):
    records, total = await AttendanceService.list_attendance(
        db, current_user.tenant_id, employee_id, start_date, end_date, status, skip, limit
    )
    results = []
    for r in records:
        results.append(await _attendance_response(r, db))
    return results


# NOTE: this must stay ABOVE GET /{record_id}. FastAPI matches routes in
# registration order, and "punches" is not an int, so a parameterised route
# declared first would swallow this path and 422.
@router.get("/punches", response_model=List[TimePunchResponse])
async def list_punches(
    employee_id: Optional[int] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    flagged_only: bool = Query(False, description="Only punches needing a look: no location, outside the geofence, or a large clock skew."),
    limit: int = Query(200, le=1000),
    current_user: User = Depends(require_permission("schedules", "view")),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(TimePunch).where(TimePunch.tenant_id == current_user.tenant_id)
    if employee_id is not None:
        stmt = stmt.where(TimePunch.employee_id == employee_id)
    if start_date is not None:
        stmt = stmt.where(TimePunch.business_date >= start_date)
    if end_date is not None:
        stmt = stmt.where(TimePunch.business_date <= end_date)
    if flagged_only:
        stmt = stmt.where(
            (TimePunch.latitude.is_(None))
            | (TimePunch.geofence_status == "outside")
            | (TimePunch.clock_skew_seconds > 300)
            | (TimePunch.clock_skew_seconds < -300)
        )
    stmt = stmt.order_by(TimePunch.punched_at.desc()).limit(limit)
    return list((await db.execute(stmt)).scalars().all())


@router.get("/{record_id}", response_model=AttendanceRecordResponse)
async def get_attendance(
    record_id: int,
    current_user: User = Depends(require_permission("schedules", "view")),
    db: AsyncSession = Depends(get_db),
):
    record = await AttendanceService.get_attendance(db, current_user.tenant_id, record_id)
    if not record:
        raise HTTPException(404, "Attendance record not found")
    return await _attendance_response(record, db)


@router.put("/{record_id}", response_model=AttendanceRecordResponse)
async def update_attendance(
    record_id: int,
    data: AttendanceRecordUpdate,
    current_user: User = Depends(require_permission("schedules", "edit")),
    db: AsyncSession = Depends(get_db),
):
    record = await AttendanceService.update_attendance(
        db, current_user.tenant_id, record_id, data.model_dump(exclude_unset=True)
    )
    if not record:
        raise HTTPException(404, "Attendance record not found")
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
    utc_now = datetime.now(timezone.utc)

    # The day being shown is the open punch's day when one is running — a night
    # shift worker at 01:00 is still on yesterday's shift and should see it.
    if open_punch is not None:
        business_date = open_punch.business_date
    else:
        business_date = await TimeclockService._resolve_business_date(
            db, current_user.tenant_id, current_user.id,
            utc_now.astimezone(), "in", None,
        )

    punches = await TimeclockService.punches_for_day(
        db, current_user.tenant_id, current_user.id, business_date
    )
    shifts = await TimeclockService._day_shifts(
        db, current_user.tenant_id, current_user.id, business_date
    )
    shift_info = []
    for s in shifts:
        mode = await TimeclockService._arrangement_mode(
            db, current_user.tenant_id, s.work_arrangement
        )
        shift_info.append(TimeclockShiftInfo(
            shift_id=s.id,
            sequence_number=s.sequence_number or 1,
            start_time=s.start_time,
            end_time=s.end_time,
            status=s.status,
            work_arrangement=s.work_arrangement,
            geofence_mode=mode,
            work_site_id=getattr(s, "work_site_id", None),
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
