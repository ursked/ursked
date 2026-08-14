from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import get_current_user, require_permission
from app.models.user import User
from app.schemas.attendance import (
    AttendanceRecordCreate,
    AttendanceRecordResponse,
    AttendanceRecordUpdate,
    OvertimeLogResponse,
    OvertimeApproveRequest,
    OvertimeConvertRequest,
    SelfTimeEntry,
    TardinessRecordResponse,
    TardinessResolveRequest,
    LeaveCreditAdjustmentResponse,
    LeaveCreditAdjustmentCreate,
)
from app.services.attendance_service import AttendanceService
from app.services.email_service import EmailService
from app.services.overtime_service import OvertimeService
from app.services.tardiness_service import TardinessService

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
    """Record attendance for an employee. Requires schedules:edit permission."""
    try:
        record = await AttendanceService.record_attendance(
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
        record = await AttendanceService.record_attendance(
            db,
            tenant_id=current_user.tenant_id,
            employee_id=current_user.id,
            attendance_date=data.date,
            actual_start=data.actual_start_time,
            actual_end=data.actual_end_time,
            notes=data.notes,
            recorded_by=current_user.id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    return await _attendance_response(record, db)
