from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.middleware.auth import get_current_user, require_role
from app.models.schedule import ScheduleChangeApprovalStep, ScheduleChangeRequest
from app.models.settings import AppSettings
from app.models.user import User
from app.schemas.schedule import (
    DateRemarkCreate,
    DateRemarkUpdate,
    DateRemarkResponse,
    ScheduleChangeApprovalStepResponse,
    ScheduleChangeRequestCreate,
    ScheduleChangeRequestResponse,
    ScheduleChangeReviewRequest,
    CopyWeekRequest,
    PublishRangeRequest,
    PublishRangeResponse,
    ScheduleGridResponse,
    ScheduleLintRequest,
    ScheduleLintResponse,
    ShiftBulkCreate,
    UnpublishRangeResponse,
    ShiftBulkCreateResponse,
    ShiftBulkDelete,
    ShiftCopyRequest,
    ShiftCreate,
    ShiftResponse,
    ShiftUpdate,
    SnapshotApply,
    SnapshotApplyResult,
    SnapshotCreate,
    SnapshotPreviewRequest,
    SnapshotPreviewResponse,
    SnapshotResponse,
    TemplateApply,
    TemplateCreate,
    TemplateResponse,
)
from app.services.email_service import EmailService
from app.services.schedule_change_service import ScheduleChangeService
from app.services.schedule_service import ScheduleConflictError, ScheduleService

router = APIRouter(prefix="/schedules", tags=["Schedules"])

EDITOR_ROLES = ["tenant_admin", "hr", "manager", "schedule_editor"]
HOLIDAY_ADMIN_ROLES = ["tenant_admin", "hr"]


async def _should_notify_schedule(db: AsyncSession, tenant_id) -> bool:
    """Check AppSettings to see if schedule change notifications are enabled."""
    result = await db.execute(
        select(AppSettings).where(AppSettings.tenant_id == tenant_id)
    )
    settings = result.scalar_one_or_none()
    return not settings or settings.notify_on_schedule_change


async def _notify_employee_ids(db: AsyncSession, tenant_id, employee_ids: list[int], change_desc: str):
    """Send schedule change emails to a list of employee IDs."""
    if not employee_ids:
        return
    unique_ids = list(set(employee_ids))
    result = await db.execute(
        select(User.id, User.email, User.first_name, User.last_name)
        .where(User.id.in_(unique_ids), User.tenant_id == tenant_id, User.is_active == True)
    )
    employees = result.all()
    for emp in employees:
        name = f"{emp.first_name} {emp.last_name}"
        EmailService.fire_and_forget(
            lambda db, e=emp, n=name: EmailService.send_schedule_change_email(
                db, to_email=e.email, employee_name=n, changes_summary=change_desc,
            )
        )


# ── Schedule Grid ────────────────────────────────────────────────────

@router.get("/grid", response_model=ScheduleGridResponse)
async def get_schedule_grid(
    start_date: date = Query(...),
    end_date: date = Query(...),
    department_id: Optional[int] = None,
    section_id: Optional[int] = None,
    org_node_id: Optional[int] = None,
    search: Optional[str] = None,
    published_only: Optional[bool] = None,
    include_actuals: bool = Query(
        False,
        description=(
            "Overlay what actually happened (attendance outcome, approved "
            "overtime) on top of the planned schedule. Off by default: the grid "
            "is a planning view and actuals only exist for days already worked."
        ),
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Compute visibility filter based on user's roles and org position
    visible_ids = await ScheduleService.get_visible_employee_ids(
        db,
        tenant_id=current_user.tenant_id,
        current_user_id=current_user.id,
        user_roles=current_user.role_codes,
    )

    # Draft/publish gate: editors see everything (drafts included); everyone
    # else only sees PUBLISHED shifts. An explicit published_only=true (the
    # employee /my/schedule view) forces published-only even for editors.
    is_editor = bool(set(current_user.role_codes) & set(EDITOR_ROLES))
    effective_published_only = True if published_only else (not is_editor)

    result = await ScheduleService.get_schedule_grid(
        db,
        tenant_id=current_user.tenant_id,
        start_date=start_date,
        end_date=end_date,
        department_id=department_id,
        section_id=section_id,
        org_node_id=org_node_id,
        search=search,
        visible_employee_ids=visible_ids,
        published_only=effective_published_only,
        include_actuals=include_actuals,
    )
    return result


@router.get("/export.xlsx")
async def export_schedule_xlsx(
    start_date: date = Query(...),
    end_date: date = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(EDITOR_ROLES)),
):
    """Formatted 'Regular Work Schedule' XLSX for the cutoff, matching the
    formal client layout (merged headers, Excel dates/times, remark codes)."""
    from app.services.schedule_export_service import ScheduleExportService

    if end_date < start_date:
        raise HTTPException(status_code=400, detail="end_date must be on or after start_date")

    content = await ScheduleExportService.build_workbook(
        db, current_user.tenant_id, start_date, end_date
    )
    fname = f"work-schedule-{start_date:%Y%m%d}-{end_date:%Y%m%d}.xlsx"
    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


# ── Shift CRUD ───────────────────────────────────────────────────────

@router.post("/shifts", response_model=ShiftResponse, status_code=201)
async def create_shift(
    data: ShiftCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(EDITOR_ROLES)),
):
    payload = data.model_dump()
    force = payload.pop("force", False)
    try:
        shift = await ScheduleService.create_shift(
            db,
            tenant_id=current_user.tenant_id,
            data=payload,
            created_by=current_user.id,
            force=force,
        )
    except ScheduleConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Shift conflicts with the employee's leave or schedule policy.",
                "conflicts": exc.conflicts,
            },
        )

    if await _should_notify_schedule(db, current_user.tenant_id):
        desc = f"New shift on {data.date} (status: {data.status})"
        await _notify_employee_ids(db, current_user.tenant_id, [data.employee_id], desc)

    return ShiftResponse.model_validate(shift)


@router.patch("/shifts/{shift_id}", response_model=ShiftResponse)
async def update_shift(
    shift_id: int,
    data: ShiftUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(EDITOR_ROLES)),
):
    shift = await ScheduleService.update_shift(
        db,
        shift_id=shift_id,
        tenant_id=current_user.tenant_id,
        data=data.model_dump(exclude_unset=True),
    )
    if not shift:
        raise HTTPException(status_code=404, detail="Shift not found")

    if await _should_notify_schedule(db, current_user.tenant_id):
        changes = data.model_dump(exclude_unset=True)
        desc = f"Shift on {shift.date} updated: {', '.join(changes.keys())}"
        await _notify_employee_ids(db, current_user.tenant_id, [shift.employee_id], desc)

    return ShiftResponse.model_validate(shift)


@router.delete("/shifts/{shift_id}", status_code=204)
async def delete_shift(
    shift_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(EDITOR_ROLES)),
):
    deleted = await ScheduleService.delete_shift(
        db, shift_id=shift_id, tenant_id=current_user.tenant_id
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Shift not found")


# ── Bulk Create Shifts ───────────────────────────────────────────────

@router.post("/shifts/bulk", response_model=ShiftBulkCreateResponse, status_code=201)
async def bulk_create_shifts(
    data: ShiftBulkCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(EDITOR_ROLES)),
):
    payload = data.model_dump()
    force = payload.pop("force", False)
    shifts, skipped = await ScheduleService.bulk_create_shifts(
        db,
        tenant_id=current_user.tenant_id,
        data=payload,
        created_by=current_user.id,
        force=force,
    )

    if shifts and await _should_notify_schedule(db, current_user.tenant_id):
        desc = f"New shifts scheduled from {data.start_date} to {data.end_date}"
        await _notify_employee_ids(db, current_user.tenant_id, data.employee_ids, desc)

    return ShiftBulkCreateResponse(
        created=[ShiftResponse.model_validate(s) for s in shifts],
        skipped_conflicts=skipped,
    )


# ── Copy Shifts ──────────────────────────────────────────────────────

@router.post("/copy", response_model=List[ShiftResponse], status_code=201)
async def copy_shifts(
    data: ShiftCopyRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(EDITOR_ROLES)),
):
    shifts = await ScheduleService.copy_shifts(
        db,
        tenant_id=current_user.tenant_id,
        source_employee_id=data.source_employee_id,
        source_start_date=data.source_start_date,
        source_end_date=data.source_end_date,
        target_employee_ids=data.target_employee_ids,
        target_start_date=data.target_start_date,
        created_by=current_user.id,
    )

    if shifts and await _should_notify_schedule(db, current_user.tenant_id):
        desc = f"Shifts copied from another employee starting {data.target_start_date}"
        await _notify_employee_ids(db, current_user.tenant_id, data.target_employee_ids, desc)

    return [ShiftResponse.model_validate(s) for s in shifts]


# ── Date Remarks ─────────────────────────────────────────────────────

@router.get("/date-remarks", response_model=List[DateRemarkResponse])
async def get_date_remarks(
    start_date: date = Query(...),
    end_date: date = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    remarks = await ScheduleService.get_date_remarks(
        db,
        tenant_id=current_user.tenant_id,
        start_date=start_date,
        end_date=end_date,
    )
    return [DateRemarkResponse.model_validate(r) for r in remarks]


@router.post("/date-remarks", response_model=DateRemarkResponse, status_code=201)
async def create_date_remark(
    data: DateRemarkCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(EDITOR_ROLES)),
):
    # One remark per date (uq_date_remark_tenant_date). Check first so a repeat
    # submission gets a clear 409 naming the existing entry, rather than the
    # database raising IntegrityError and the caller seeing an opaque 500.
    existing = await ScheduleService.get_date_remarks(
        db,
        tenant_id=current_user.tenant_id,
        start_date=data.date,
        end_date=data.date,
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{data.date.isoformat()} already has a remark "
                f"(\"{existing[0].title}\"). Edit or delete it instead."
            ),
        )

    remark = await ScheduleService.create_date_remark(
        db,
        tenant_id=current_user.tenant_id,
        data=data.model_dump(),
    )
    return DateRemarkResponse.model_validate(remark)


@router.patch("/date-remarks/{remark_id}", response_model=DateRemarkResponse)
async def update_date_remark(
    remark_id: int,
    data: DateRemarkUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(HOLIDAY_ADMIN_ROLES)),
):
    remark = await ScheduleService.update_date_remark(
        db,
        tenant_id=current_user.tenant_id,
        remark_id=remark_id,
        data=data.model_dump(exclude_unset=True),
    )
    if not remark:
        raise HTTPException(status_code=404, detail="Date remark not found")
    return DateRemarkResponse.model_validate(remark)


@router.delete("/date-remarks/{remark_id}", status_code=204)
async def delete_date_remark(
    remark_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(HOLIDAY_ADMIN_ROLES)),
):
    deleted = await ScheduleService.delete_date_remark(
        db, remark_id=remark_id, tenant_id=current_user.tenant_id
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Date remark not found")


@router.get("/holidays", response_model=List[DateRemarkResponse])
async def get_holidays(
    year: Optional[int] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all holidays for the tenant, optionally filtered by year."""
    holidays = await ScheduleService.get_holidays(
        db, tenant_id=current_user.tenant_id, year=year
    )
    return [DateRemarkResponse.model_validate(r) for r in holidays]


# ── Templates ────────────────────────────────────────────────────────

@router.get("/templates", response_model=List[TemplateResponse])
async def get_templates(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(EDITOR_ROLES)),
):
    templates = await ScheduleService.get_templates(
        db, tenant_id=current_user.tenant_id
    )
    return [TemplateResponse.model_validate(t) for t in templates]


@router.post("/templates", response_model=TemplateResponse, status_code=201)
async def create_template(
    data: TemplateCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(EDITOR_ROLES)),
):
    template = await ScheduleService.create_template(
        db,
        tenant_id=current_user.tenant_id,
        data=data.model_dump(),
        created_by=current_user.id,
    )
    return TemplateResponse.model_validate(template)


@router.post("/templates/{template_id}/apply", response_model=List[ShiftResponse], status_code=201)
async def apply_template(
    template_id: int,
    data: TemplateApply,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(EDITOR_ROLES)),
):
    shifts = await ScheduleService.apply_template(
        db,
        tenant_id=current_user.tenant_id,
        template_id=template_id,
        employee_ids=data.employee_ids,
        start_date=data.start_date,
        created_by=current_user.id,
    )
    return [ShiftResponse.model_validate(s) for s in shifts]


# ── Bulk Delete Shifts ────────────────────────────────────────────

@router.post("/shifts/bulk-delete")
async def bulk_delete_shifts(
    data: ShiftBulkDelete,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(EDITOR_ROLES)),
):
    count = await ScheduleService.bulk_delete_shifts(
        db,
        tenant_id=current_user.tenant_id,
        start_date=data.start_date,
        end_date=data.end_date,
        employee_ids=data.employee_ids,
    )
    return {"deleted_count": count}


# ── Schedule Snapshots ───────────────────────────────────────────

@router.get("/snapshots", response_model=List[SnapshotResponse])
async def list_snapshots(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(EDITOR_ROLES)),
):
    snapshots = await ScheduleService.get_snapshots(db, tenant_id=current_user.tenant_id)
    return [SnapshotResponse.model_validate(s) for s in snapshots]


@router.post("/snapshots", response_model=SnapshotResponse, status_code=201)
async def create_snapshot(
    data: SnapshotCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(EDITOR_ROLES)),
):
    snapshot = await ScheduleService.create_snapshot(
        db,
        tenant_id=current_user.tenant_id,
        name=data.name,
        description=data.description,
        start_date=data.start_date,
        end_date=data.end_date,
        range_type=data.range_type,
        created_by=current_user.id,
    )
    return SnapshotResponse.model_validate(snapshot)


@router.post("/snapshots/{snapshot_id}/preview", response_model=SnapshotPreviewResponse)
async def preview_snapshot(
    snapshot_id: int,
    data: SnapshotPreviewRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(EDITOR_ROLES)),
):
    """Dry-run: show the occurrences and conflicts a repeat-apply would produce,
    without writing any shifts."""
    result = await ScheduleService.preview_snapshot_apply(
        db,
        tenant_id=current_user.tenant_id,
        snapshot_id=snapshot_id,
        target_start_date=data.target_start_date,
        repeat_until=data.repeat_until,
        employee_ids=data.employee_ids,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return result


@router.post("/snapshots/{snapshot_id}/apply", response_model=SnapshotApplyResult, status_code=201)
async def apply_snapshot(
    snapshot_id: int,
    data: SnapshotApply,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(EDITOR_ROLES)),
):
    result = await ScheduleService.apply_snapshot(
        db,
        tenant_id=current_user.tenant_id,
        snapshot_id=snapshot_id,
        target_start_date=data.target_start_date,
        employee_ids=data.employee_ids,
        created_by=current_user.id,
        repeat_until=data.repeat_until,
        on_conflict=data.on_conflict,
    )
    await db.commit()
    return result


@router.delete("/snapshots/{snapshot_id}", status_code=204)
async def delete_snapshot(
    snapshot_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(EDITOR_ROLES)),
):
    deleted = await ScheduleService.delete_snapshot(
        db, snapshot_id=snapshot_id, tenant_id=current_user.tenant_id,
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Snapshot not found")


# ── Copy week ────────────────────────────────────────────────────────

def _copy_week_target_start(data: CopyWeekRequest):
    """Default target = the window immediately AFTER the source (next week)."""
    if data.target_start_date:
        return data.target_start_date
    from datetime import timedelta
    span = (data.source_end_date - data.source_start_date).days + 1
    return data.source_start_date + timedelta(days=max(span, 1))


async def _copy_week_employee_ids(current_user, db, data):
    """Restrict to the caller's visible employees, intersected with any
    explicit employee_ids from the request (so the grid's dept filter narrows
    the copy)."""
    visible = await ScheduleService.get_visible_employee_ids(
        db, tenant_id=current_user.tenant_id,
        current_user_id=current_user.id, user_roles=current_user.role_codes,
    )
    if data.employee_ids is None:
        return visible
    if visible is None:
        return data.employee_ids
    return [e for e in data.employee_ids if e in set(visible)]


@router.post("/copy-week/preview", response_model=SnapshotPreviewResponse)
async def preview_copy_week(
    data: CopyWeekRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(EDITOR_ROLES)),
):
    """Dry-run: what a copy of [source_start, source_end] into the target window
    WOULD do (occurrences + conflicts), writing nothing."""
    return await ScheduleService.preview_copy_week(
        db,
        tenant_id=current_user.tenant_id,
        source_start=data.source_start_date,
        source_end=data.source_end_date,
        target_start=_copy_week_target_start(data),
        employee_ids=await _copy_week_employee_ids(current_user, db, data),
    )


@router.post("/copy-week", response_model=SnapshotApplyResult, status_code=201)
async def copy_week(
    data: CopyWeekRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(EDITOR_ROLES)),
):
    """Copy the source window's shifts into the target window (default: next
    week) for the visible employees, skipping/overwriting per on_conflict.
    Approved-leave dates are always skipped."""
    result = await ScheduleService.copy_week(
        db,
        tenant_id=current_user.tenant_id,
        source_start=data.source_start_date,
        source_end=data.source_end_date,
        target_start=_copy_week_target_start(data),
        employee_ids=await _copy_week_employee_ids(current_user, db, data),
        created_by=current_user.id,
        on_conflict=data.on_conflict,
    )
    await db.commit()
    return result


# ── Guardrail lint ───────────────────────────────────────────────────

@router.post("/lint", response_model=ScheduleLintResponse)
async def lint_schedule(
    data: ScheduleLintRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(EDITOR_ROLES)),
):
    """Report guardrail violations (consecutive-days / rest-days / work-on-leave)
    in the existing shifts for the range, so the grid can flag them inline.
    Read-only."""
    violations = await ScheduleService.lint_schedule(
        db,
        tenant_id=current_user.tenant_id,
        start_date=data.start_date,
        end_date=data.end_date,
        employee_ids=data.employee_ids,
    )
    return {"violations": violations}


# ── Draft / publish ──────────────────────────────────────────────────

@router.post("/publish", response_model=PublishRangeResponse)
async def publish_schedule_range(
    data: PublishRangeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(EDITOR_ROLES)),
):
    """Release the DRAFT shifts in the range to employees, and notify each
    affected employee in-app that their schedule is published."""
    from app.services.notification_service import NotificationService

    result = await ScheduleService.publish_range(
        db,
        tenant_id=current_user.tenant_id,
        start_date=data.start_date,
        end_date=data.end_date,
        employee_ids=data.employee_ids,
        published_by=current_user.id,
    )
    affected = result["employee_ids"]
    label = f"{data.start_date.isoformat()} – {data.end_date.isoformat()}"
    for emp_id in affected:
        await NotificationService.notify(
            db, current_user.tenant_id, emp_id,
            type="schedule_published",
            title="Your schedule is published",
            body=f"Your schedule for {label} has been published.",
        )
    await db.commit()
    # Also email each affected employee (fire-and-forget), respecting the
    # tenant's schedule-change notification preference.
    if affected and await _should_notify_schedule_change(db, current_user.tenant_id):
        await _notify_employee_ids(
            db, current_user.tenant_id, affected,
            f"Your schedule for {label} has been published.",
        )
    return {"published_count": result["published_count"], "notified": len(affected)}


@router.post("/unpublish", response_model=UnpublishRangeResponse)
async def unpublish_schedule_range(
    data: PublishRangeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(EDITOR_ROLES)),
):
    """Return published shifts in the range to DRAFT (hidden from employees) so
    they can be reworked. No notification."""
    result = await ScheduleService.unpublish_range(
        db,
        tenant_id=current_user.tenant_id,
        start_date=data.start_date,
        end_date=data.end_date,
        employee_ids=data.employee_ids,
    )
    await db.commit()
    return result


# ── Export ───────────────────────────────────────────────────────────

@router.get("/export")
async def export_schedule(
    start_date: date = Query(...),
    end_date: date = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(EDITOR_ROLES)),
):
    csv_content = await ScheduleService.export_shifts_csv(
        db,
        tenant_id=current_user.tenant_id,
        start_date=start_date,
        end_date=end_date,
    )
    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=schedule_{start_date}_{end_date}.csv"
        },
    )


# ══════════════════════════════════════════════════════════════════════
# SCHEDULE CHANGE REQUESTS (swap & change)
# ══════════════════════════════════════════════════════════════════════


def _request_to_response(r: ScheduleChangeRequest) -> ScheduleChangeRequestResponse:
    """Serialize a ScheduleChangeRequest to response schema."""
    requester_name = ""
    if r.requester:
        requester_name = f"{r.requester.first_name} {r.requester.last_name}"

    target_name = None
    if r.target_employee:
        target_name = f"{r.target_employee.first_name} {r.target_employee.last_name}"

    reviewer_name = None
    if r.reviewer:
        reviewer_name = f"{r.reviewer.first_name} {r.reviewer.last_name}"

    steps = []
    current_step = None
    for s in (r.approval_steps or []):
        approver_name = ""
        if s.approver:
            approver_name = f"{s.approver.first_name} {s.approver.last_name}"
        steps.append(ScheduleChangeApprovalStepResponse(
            id=s.id,
            step_order=s.step_order,
            step_type=s.step_type,
            approver_id=s.approver_id,
            approver_name=approver_name,
            status=s.status,
            decided_at=s.decided_at,
            notes=s.notes,
        ))
        if s.status == "pending" and current_step is None:
            current_step = s.step_order

    return ScheduleChangeRequestResponse(
        id=r.id,
        request_type=r.request_type,
        requester_id=r.requester_id,
        requester_name=requester_name,
        date=r.date,
        end_date=r.end_date,
        target_employee_id=r.target_employee_id,
        target_employee_name=target_name,
        original_start_time=r.original_start_time,
        original_end_time=r.original_end_time,
        original_status=r.original_status,
        target_original_start_time=r.target_original_start_time,
        target_original_end_time=r.target_original_end_time,
        target_original_status=r.target_original_status,
        requested_start_time=r.requested_start_time,
        requested_end_time=r.requested_end_time,
        requested_status=r.requested_status,
        requested_work_arrangement=r.requested_work_arrangement,
        reason=r.reason,
        status=r.status,
        reviewed_by=r.reviewed_by,
        reviewer_name=reviewer_name,
        reviewed_at=r.reviewed_at,
        reviewer_notes=r.reviewer_notes,
        approval_steps=steps,
        current_step=current_step,
        created_at=r.created_at,
    )


_CHANGE_REQUEST_LOAD = [
    selectinload(ScheduleChangeRequest.requester),
    selectinload(ScheduleChangeRequest.target_employee),
    selectinload(ScheduleChangeRequest.reviewer),
    selectinload(ScheduleChangeRequest.approval_steps)
    .selectinload(ScheduleChangeApprovalStep.approver),
]


@router.post("/change-requests", response_model=ScheduleChangeRequestResponse, status_code=201)
async def create_schedule_change_request(
    data: ScheduleChangeRequestCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a schedule swap or change request."""
    if data.request_type == "swap" and not data.target_employee_id:
        raise HTTPException(status_code=400, detail="target_employee_id is required for swap requests")

    if data.request_type == "swap" and data.target_employee_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot swap schedule with yourself")

    try:
        request = await ScheduleChangeService.create_request(
            db=db,
            tenant_id=current_user.tenant_id,
            requester_id=current_user.id,
            request_type=data.request_type,
            req_date=data.date,
            end_date=data.end_date,
            target_employee_id=data.target_employee_id,
            requested_start_time=data.requested_start_time,
            requested_end_time=data.requested_end_time,
            requested_status=data.requested_status,
            requested_work_arrangement=data.requested_work_arrangement,
            reason=data.reason,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Reload with relationships
    result = await db.execute(
        select(ScheduleChangeRequest)
        .options(*_CHANGE_REQUEST_LOAD)
        .where(ScheduleChangeRequest.id == request.id)
    )
    loaded = result.scalar_one()

    # Notify the approver(s) who currently have a pending step (fire-and-forget).
    requester_name = (
        f"{loaded.requester.first_name} {loaded.requester.last_name}"
        if loaded.requester else "An employee"
    )
    req_date = loaded.date.isoformat() if loaded.date else ""
    for step in loaded.approval_steps:
        if step.status == "pending" and step.approver and step.approver.email:
            EmailService.fire_and_forget(
                lambda db, email=step.approver.email,
                approver_name=f"{step.approver.first_name} {step.approver.last_name}":
                    EmailService.send_schedule_change_request_email(
                        db,
                        approver_email=email,
                        approver_name=approver_name,
                        requester_name=requester_name,
                        request_type=loaded.request_type,
                        req_date=req_date,
                        reason=loaded.reason or "",
                    )
            )

    return _request_to_response(loaded)


@router.get("/change-requests", response_model=List[ScheduleChangeRequestResponse])
async def list_my_schedule_change_requests(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List the current user's schedule change/swap requests."""
    result = await db.execute(
        select(ScheduleChangeRequest)
        .options(*_CHANGE_REQUEST_LOAD)
        .where(
            ScheduleChangeRequest.tenant_id == current_user.tenant_id,
            ScheduleChangeRequest.requester_id == current_user.id,
        )
        .order_by(ScheduleChangeRequest.created_at.desc())
    )
    return [_request_to_response(r) for r in result.scalars().all()]


@router.get("/change-requests/pending-approvals", response_model=List[ScheduleChangeRequestResponse])
async def get_pending_schedule_approvals(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get schedule change/swap requests pending this user's approval."""
    requests = await ScheduleChangeService.get_pending_for_approver(
        db, current_user.tenant_id, current_user.id,
    )
    return [_request_to_response(r) for r in requests]


@router.get("/change-requests/{request_id}", response_model=ScheduleChangeRequestResponse)
async def get_schedule_change_request(
    request_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single schedule change request by ID."""
    result = await db.execute(
        select(ScheduleChangeRequest)
        .options(*_CHANGE_REQUEST_LOAD)
        .where(
            ScheduleChangeRequest.id == request_id,
            ScheduleChangeRequest.tenant_id == current_user.tenant_id,
        )
    )
    request = result.scalar_one_or_none()
    if not request:
        raise HTTPException(status_code=404, detail="Request not found")
    return _request_to_response(request)


@router.post("/change-requests/{request_id}/review")
async def review_schedule_change_request(
    request_id: int,
    review: ScheduleChangeReviewRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Approve or reject a schedule change/swap request step."""
    # Load the request
    result = await db.execute(
        select(ScheduleChangeRequest)
        .options(*_CHANGE_REQUEST_LOAD)
        .where(
            ScheduleChangeRequest.id == request_id,
            ScheduleChangeRequest.tenant_id == current_user.tenant_id,
        )
    )
    request = result.scalar_one_or_none()
    if not request:
        raise HTTPException(status_code=404, detail="Request not found")

    if request.status != "pending":
        raise HTTPException(status_code=400, detail=f"Request is already {request.status}")

    # Find the pending step for this approver
    my_step = None
    for step in request.approval_steps:
        if step.approver_id == current_user.id and step.status == "pending":
            my_step = step
            break

    if not my_step:
        raise HTTPException(status_code=403, detail="You don't have a pending approval step for this request")

    # Validate all previous steps are approved
    for step in request.approval_steps:
        if step.step_order < my_step.step_order and step.status != "approved":
            raise HTTPException(
                status_code=400,
                detail=f"Previous approval step {step.step_order} is still {step.status}",
            )

    new_status = await ScheduleChangeService.process_step_decision(
        db, request, my_step, review.action, review.notes, current_user.id,
    )

    # Reload for response
    result = await db.execute(
        select(ScheduleChangeRequest)
        .options(*_CHANGE_REQUEST_LOAD)
        .where(ScheduleChangeRequest.id == request_id)
    )
    loaded = result.scalar_one()

    # On a FINAL decision, notify the requester (fire-and-forget). A rejection
    # at any step is final; an approval is only final once no pending steps remain.
    if new_status in ("approved", "rejected") and loaded.requester and loaded.requester.email:
        EmailService.fire_and_forget(
            lambda db, email=loaded.requester.email,
            requester_name=f"{loaded.requester.first_name} {loaded.requester.last_name}",
            reviewer_name=f"{current_user.first_name} {current_user.last_name}",
            req_date=(loaded.date.isoformat() if loaded.date else ""):
                EmailService.send_schedule_change_decision_email(
                    db,
                    to_email=email,
                    requester_name=requester_name,
                    decision=new_status,
                    request_type=loaded.request_type,
                    req_date=req_date,
                    reviewer_name=reviewer_name,
                    notes=review.notes or "",
                )
        )
    elif new_status == "pending":
        # This approval advanced the chain: notify the NEXT approver(s) whose
        # step just became actionable (lowest pending step_order), so multi-step
        # chains don't stall waiting on someone who was never told.
        pending_steps = [s for s in loaded.approval_steps if s.status == "pending"]
        if pending_steps:
            next_order = min(s.step_order for s in pending_steps)
            requester_name = (
                f"{loaded.requester.first_name} {loaded.requester.last_name}"
                if loaded.requester else "An employee"
            )
            req_date = loaded.date.isoformat() if loaded.date else ""
            for step in pending_steps:
                if step.step_order != next_order:
                    continue
                if step.approver and step.approver.email:
                    EmailService.fire_and_forget(
                        lambda db, email=step.approver.email,
                        approver_name=f"{step.approver.first_name} {step.approver.last_name}":
                            EmailService.send_schedule_change_request_email(
                                db,
                                approver_email=email,
                                approver_name=approver_name,
                                requester_name=requester_name,
                                request_type=loaded.request_type,
                                req_date=req_date,
                                reason=loaded.reason or "",
                            )
                    )

    return _request_to_response(loaded)


@router.post("/change-requests/{request_id}/cancel")
async def cancel_schedule_change_request(
    request_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cancel a pending schedule change/swap request (only the requester can cancel)."""
    result = await db.execute(
        select(ScheduleChangeRequest).where(
            ScheduleChangeRequest.id == request_id,
            ScheduleChangeRequest.tenant_id == current_user.tenant_id,
            ScheduleChangeRequest.requester_id == current_user.id,
        )
    )
    request = result.scalar_one_or_none()
    if not request:
        raise HTTPException(status_code=404, detail="Request not found")

    if request.status != "pending":
        raise HTTPException(status_code=400, detail=f"Request is already {request.status}")

    request.status = "cancelled"
    await db.flush()
    return {"status": "cancelled"}
