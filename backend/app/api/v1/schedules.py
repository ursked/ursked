from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.middleware.auth import get_current_user, require_permission
from app.models.schedule import ScheduleChangeApprovalStep, ScheduleChangeRequest, Shift
from app.models.settings import AppSettings
from app.models.user import User
from app.schemas.schedule import (
    DateRemarkCreate,
    DateRemarkUpdate,
    DateRemarkResponse,
    HolidaySourceResponse,
    HolidaySourceUpdate,
    HolidaySyncResponse,
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
    ShiftBulkDeleteResponse,
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
    TemplateApplyResult,
    TemplateCreate,
    TemplateResponse,
)
from app.services import access_scope
from app.services.email_service import EmailService
from app.services.permission_service import ADMIN_ROLE, PermissionService
from app.services.schedule_change_service import ScheduleChangeService
from app.services.schedule_service import ScheduleConflictError, ScheduleService

router = APIRouter(prefix="/schedules", tags=["Schedules"])

# Who may do what here is the permission matrix (schedules view/create/edit/
# delete, see the contract in permission_service), and to WHOM is access_scope.
# Until 2026-09 this router used a hard-coded EDITOR_ROLES list, so unticking a
# box on the Permissions screen changed nothing, and a manager limited to their
# team on the grid could still write anyone's shifts through the API.


async def _can(db: AsyncSession, user: User, module: str, action: str) -> bool:
    """The check `require_permission` makes, for decisions taken inside a
    handler (a query flag that needs more than the endpoint itself does)."""
    return await PermissionService.user_can(db, user, module, action)


def _require_holiday_admin(action: str):
    """Holidays and date remarks apply to the whole company. They are
    configuration (Policies): an administrator changes them from the admin
    dashboard, and so may anyone holding the matching schedules action with
    full scope (HR, schedule editors) from the regular one. A team manager may
    schedule their team but must not change everyone's holiday pay."""

    async def checker(
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ):
        if current_user.has_role(ADMIN_ROLE):
            return current_user
        if not await _can(db, current_user, "schedules", action):
            raise HTTPException(status_code=403, detail=f"No {action} permission on schedules")
        if action != "view" and not access_scope.has_full_scope(current_user, "schedules"):
            raise HTTPException(
                status_code=403,
                detail=(
                    "Holidays apply to the whole company, so only people who "
                    "schedule everyone (administrators, HR and schedule editors) "
                    "can change them."
                ),
            )
        return current_user

    return checker


async def _visible_ids(db: AsyncSession, user: User) -> Optional[list]:
    return await ScheduleService.get_visible_employee_ids(
        db,
        tenant_id=user.tenant_id,
        current_user_id=user.id,
        user_roles=user.role_codes,
    )


async def _read_scope(
    db: AsyncSession, user: User, requested: Optional[List[int]]
) -> Optional[List[int]]:
    """Narrow a read-only request (lint, snapshot capture, CSV) to the
    employees `user` can see. None = everyone, [] = nobody."""
    visible = await _visible_ids(db, user)
    if requested is None:
        return visible
    if visible is None:
        return list(requested)
    allowed = set(visible)
    return [e for e in requested if e in allowed]


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


def _date_list(dates) -> str:
    ds = sorted({d if isinstance(d, date) else date.fromisoformat(str(d)) for d in dates})
    if len(ds) <= 3:
        return ", ".join(d.isoformat() for d in ds)
    return f"{ds[0].isoformat()} to {ds[-1].isoformat()} ({len(ds)} days)"


async def _notify_schedule_change(
    db: AsyncSession, tenant_id, by_employee: dict, what: str
) -> None:
    """Tell each employee that a PUBLISHED part of their schedule changed.

    Drafts are never announced: an employee cannot see a draft, so a message
    about one is noise at best and, when the draft is then reworked, wrong.
    Publishing announces the finished schedule once. After that, any change,
    removal or withdrawal of something they could already see is announced,
    in-app always and by email when the company has schedule emails on.
    `what` completes the sentence "Your shift on <dates> ...".
    """
    from app.services.notification_service import NotificationService

    by_employee = {e: ds for e, ds in (by_employee or {}).items() if e and ds}
    if not by_employee:
        return
    email = await _should_notify_schedule(db, tenant_id)
    for emp_id, dates in by_employee.items():
        body = f"Your shift on {_date_list(dates)} {what}."
        await NotificationService.notify(
            db, tenant_id, emp_id,
            type="schedule_changed",
            title="Your schedule changed",
            body=body,
        )
        if email:
            await _notify_employee_ids(db, tenant_id, [emp_id], body)


async def _notify_published_removed(db: AsyncSession, user: User, removed: dict, what: str):
    await _notify_schedule_change(db, user.tenant_id, removed, what)


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
    mine: bool = Query(
        False,
        description=(
            "Only the caller's own row. My Schedule uses this so it can never "
            "pick up someone else's shifts."
        ),
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Schedules are operations: the admin dashboard has no grid, and an
    # administrator's own shifts are in their employee dashboard.
    access_scope.assert_operational_session(current_user)
    # Seeing other people's drafts, attendance and overtime is schedules:view.
    # Without it the grid is still readable (teammates' published shifts) but
    # actuals are refused outright: they were the way an employee could read a
    # colleague's lateness and absences with ?include_actuals=true.
    can_view_others = await _can(db, current_user, "schedules", "view")
    if include_actuals and not can_view_others:
        raise HTTPException(
            status_code=403,
            detail=(
                "Attendance and overtime on the schedule are only shown to people "
                "allowed to view other employees' schedules."
            ),
        )

    visible_ids = [current_user.id] if mine else await _visible_ids(db, current_user)

    # Draft/publish gate: drafts are visible only with schedules:view. An
    # explicit published_only=true (the employee /my/schedule view) forces
    # published-only even for editors.
    effective_published_only = True if published_only else (not can_view_others)

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
    # Which rows the caller may change, so the grid offers only the edits the
    # API will accept. Visibility is wider than management: a manager can see
    # a neighbouring team without being able to move its shifts.
    managed = await access_scope.managed_employee_ids(db, current_user, "schedules")
    for emp in result["employees"]:
        emp["can_manage"] = managed is None or emp["employee_id"] in managed
    return result


@router.get("/export.xlsx")
async def export_schedule_xlsx(
    start_date: date = Query(...),
    end_date: date = Query(...),
    employee_ids: Optional[List[int]] = Query(
        None, description="Only these employees. Default: everyone you manage."
    ),
    include_drafts: bool = Query(
        False, description="Include shifts that have not been published yet."
    ),
    current_user: User = Depends(require_permission("schedules", "view")),
    db: AsyncSession = Depends(get_db),
):
    """The formal 'Regular Work Schedule' workbook for a cutoff (merged
    headings, Excel dates and times, REMARKS codes), built from the report
    builder's built-in template (area R, report_templates).

    It used to be a separate hard-coded exporter that could not filter by
    employee, so it was limited to people who schedule everyone. It now covers
    the employees the caller manages (all of them for full-scope roles), and
    only published shifts unless drafts are asked for; seeing drafts is what
    schedules:view already allows on the grid.
    """
    from app.services.report_templates import build_work_schedule_xlsx

    if end_date < start_date:
        raise HTTPException(status_code=400, detail="end_date must be on or after start_date")
    if (end_date - start_date).days > 366:
        raise HTTPException(status_code=400, detail="Export at most a year at a time.")

    scope = await access_scope.managed_employee_ids(db, current_user, "schedules")
    if employee_ids:
        await access_scope.assert_manages(db, current_user, employee_ids, "schedules")
        scope = set(employee_ids)

    try:
        content = await build_work_schedule_xlsx(
            db, current_user.tenant_id, start_date, end_date,
            employee_scope=scope, viewer=current_user, include_drafts=include_drafts,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    fname = f"work-schedule-{start_date:%Y%m%d}-{end_date:%Y%m%d}.xlsx"
    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


# ── Shift CRUD ───────────────────────────────────────────────────────

async def _load_shift(db: AsyncSession, user: User, shift_id: int) -> Shift:
    """The shift, or 404. Tenant-scoped, so another company's id is simply
    not found rather than forbidden."""
    shift = (
        await db.execute(
            select(Shift).where(Shift.id == shift_id, Shift.tenant_id == user.tenant_id)
        )
    ).scalar_one_or_none()
    if not shift:
        raise HTTPException(status_code=404, detail="Shift not found")
    return shift


def _conflict_http(exc: ScheduleConflictError) -> HTTPException:
    """409 carrying every conflict, so the grid can list them and offer an
    override when all of them are forceable."""
    locked = any(c["type"] == "approved_leave_locked" for c in exc.conflicts)
    return HTTPException(
        status_code=409,
        detail={
            "message": (
                exc.conflicts[0]["message"] if locked
                else "Shift conflicts with the employee's leave or schedule policy."
            ),
            "conflicts": exc.conflicts,
        },
    )


# Creating, bulk-creating and copying shifts notify nobody: new shifts are
# drafts, which the employee cannot see. They hear once, when the range is
# published, and after that about every change to something they could see.

@router.post("/shifts", response_model=ShiftResponse, status_code=201)
async def create_shift(
    data: ShiftCreate,
    current_user: User = Depends(require_permission("schedules", "create")),
    db: AsyncSession = Depends(get_db),
):
    await access_scope.assert_manages(db, current_user, [data.employee_id], "schedules", own="shifts")
    payload = data.model_dump()
    force = payload.pop("force", False)
    try:
        shift = await ScheduleService.create_shift(
            db,
            tenant_id=current_user.tenant_id,
            data=payload,
            created_by=current_user.id,
            force=force,
            actor=current_user,
        )
    except ScheduleConflictError as exc:
        raise _conflict_http(exc)
    return ShiftResponse.model_validate(shift)


@router.patch("/shifts/{shift_id}", response_model=ShiftResponse)
async def update_shift(
    shift_id: int,
    data: ShiftUpdate,
    current_user: User = Depends(require_permission("schedules", "edit")),
    db: AsyncSession = Depends(get_db),
):
    """Edit or move (drag) a shift. Goes through the same validator as
    create; `force` overrides guardrails exactly as it does there. Explicit
    nulls clear optional fields."""
    existing = await _load_shift(db, current_user, shift_id)
    # Both ends of a move: the employee it is taken from and the one it is
    # given to must be in the caller's teams.
    await access_scope.assert_manages(
        db, current_user, [existing.employee_id, data.employee_id], "schedules", own="shifts"
    )
    old_emp, old_date, was_published = existing.employee_id, existing.date, existing.is_published
    payload = data.model_dump(exclude_unset=True)
    force = bool(payload.pop("force", False))
    try:
        shift = await ScheduleService.update_shift(
            db,
            shift_id=shift_id,
            tenant_id=current_user.tenant_id,
            data=payload,
            force=force,
            actor=current_user,
        )
    except ScheduleConflictError as exc:
        raise _conflict_http(exc)
    if not shift:
        raise HTTPException(status_code=404, detail="Shift not found")

    if was_published and payload:
        if shift.employee_id != old_emp:
            await _notify_schedule_change(
                db, current_user.tenant_id, {old_emp: [old_date]}, "was removed from your schedule"
            )
            await _notify_schedule_change(
                db, current_user.tenant_id, {shift.employee_id: [shift.date]},
                "was added to your schedule",
            )
        else:
            moved = f" (moved from {old_date.isoformat()})" if shift.date != old_date else ""
            await _notify_schedule_change(
                db, current_user.tenant_id, {shift.employee_id: [shift.date]}, f"was changed{moved}"
            )

    return ShiftResponse.model_validate(shift)


@router.delete("/shifts/{shift_id}", status_code=204)
async def delete_shift(
    shift_id: int,
    current_user: User = Depends(require_permission("schedules", "delete")),
    db: AsyncSession = Depends(get_db),
):
    existing = await _load_shift(db, current_user, shift_id)
    await access_scope.assert_manages(db, current_user, [existing.employee_id], "schedules", own="shifts")
    emp, d, was_published = existing.employee_id, existing.date, existing.is_published
    try:
        deleted = await ScheduleService.delete_shift(
            db, shift_id=shift_id, tenant_id=current_user.tenant_id, actor=current_user,
        )
    except ScheduleConflictError as exc:
        raise _conflict_http(exc)
    if not deleted:
        raise HTTPException(status_code=404, detail="Shift not found")
    if was_published:
        await _notify_schedule_change(
            db, current_user.tenant_id, {emp: [d]}, "was removed from your schedule"
        )


# ── Bulk Create Shifts ───────────────────────────────────────────────

@router.post("/shifts/bulk", response_model=ShiftBulkCreateResponse, status_code=201)
async def bulk_create_shifts(
    data: ShiftBulkCreate,
    current_user: User = Depends(require_permission("schedules", "create")),
    db: AsyncSession = Depends(get_db),
):
    await access_scope.assert_manages(db, current_user, data.employee_ids, "schedules", own="shifts")
    payload = data.model_dump()
    force = payload.pop("force", False)
    shifts, skipped = await ScheduleService.bulk_create_shifts(
        db,
        tenant_id=current_user.tenant_id,
        data=payload,
        created_by=current_user.id,
        force=force,
        actor=current_user,
    )
    return ShiftBulkCreateResponse(
        created=[ShiftResponse.model_validate(s) for s in shifts],
        skipped_conflicts=skipped,
    )


# ── Copy Shifts ──────────────────────────────────────────────────────

@router.post("/copy", response_model=List[ShiftResponse], status_code=201)
async def copy_shifts(
    data: ShiftCopyRequest,
    current_user: User = Depends(require_permission("schedules", "create")),
    db: AsyncSession = Depends(get_db),
):
    await access_scope.assert_manages(db, current_user, data.target_employee_ids, "schedules", own="shifts")
    shifts = await ScheduleService.copy_shifts(
        db,
        tenant_id=current_user.tenant_id,
        source_employee_id=data.source_employee_id,
        source_start_date=data.source_start_date,
        source_end_date=data.source_end_date,
        target_employee_ids=data.target_employee_ids,
        target_start_date=data.target_start_date,
        created_by=current_user.id,
        actor=current_user,
    )
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
    current_user: User = Depends(_require_holiday_admin("create")),
    db: AsyncSession = Depends(get_db),
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
        actor=current_user,
    )
    return DateRemarkResponse.model_validate(remark)


@router.patch("/date-remarks/{remark_id}", response_model=DateRemarkResponse)
async def update_date_remark(
    remark_id: int,
    data: DateRemarkUpdate,
    current_user: User = Depends(_require_holiday_admin("edit")),
    db: AsyncSession = Depends(get_db),
):
    try:
        remark = await ScheduleService.update_date_remark(
            db,
            tenant_id=current_user.tenant_id,
            remark_id=remark_id,
            data=data.model_dump(exclude_unset=True),
            actor=current_user,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if not remark:
        raise HTTPException(status_code=404, detail="Date remark not found")
    return DateRemarkResponse.model_validate(remark)


@router.delete("/date-remarks/{remark_id}", status_code=204)
async def delete_date_remark(
    remark_id: int,
    current_user: User = Depends(_require_holiday_admin("delete")),
    db: AsyncSession = Depends(get_db),
):
    deleted = await ScheduleService.delete_date_remark(
        db, remark_id=remark_id, tenant_id=current_user.tenant_id, actor=current_user,
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


# ── Live holiday feed ────────────────────────────────────────────────

async def _source_response(db: AsyncSession, user: User, source) -> dict:
    from app.models.tenant import Tenant
    from app.services import holiday_sync_service as hs

    tenant = await db.get(Tenant, user.tenant_id)
    out = {
        "configured": source is not None,
        "suggested_country_slug": hs.suggest_country_slug(getattr(tenant, "country", None)),
        "countries": [{"slug": s, "name": n} for s, n, _ in hs.COUNTRIES],
    }
    if source is not None:
        for k in ("provider", "country_slug", "feed_url", "auto_sync", "last_synced_at",
                  "last_status", "last_error", "last_counts", "discovered_regions"):
            out[k] = getattr(source, k)
        out["include_regions"] = list(source.include_regions or [])
    return out


@router.get("/holidays/source", response_model=HolidaySourceResponse)
async def get_holiday_source(
    current_user: User = Depends(_require_holiday_admin("view")),
    db: AsyncSession = Depends(get_db),
):
    """Where holidays come from and how the last sync went."""
    from app.services import holiday_sync_service as hs

    return await _source_response(db, current_user, await hs.get_source(db, current_user.tenant_id))


@router.put("/holidays/source", response_model=HolidaySourceResponse)
async def set_holiday_source(
    data: HolidaySourceUpdate,
    current_user: User = Depends(_require_holiday_admin("edit")),
    db: AsyncSession = Depends(get_db),
):
    """Choose the holiday feed (a country on officeholidays.com, or any https
    iCal address), the regions to include, and whether to sync daily."""
    from app.models.schedule import HolidaySource
    from app.services import holiday_sync_service as hs

    if data.provider == "officeholidays" and not data.country_slug:
        raise HTTPException(status_code=400, detail="Choose a country for the holiday calendar.")
    if data.provider == "ics_url":
        try:
            await hs.assert_public_https_url((data.feed_url or "").strip())
        except hs.HolidayFeedError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    source = await hs.get_source(db, current_user.tenant_id)
    if source is None:
        source = HolidaySource(tenant_id=current_user.tenant_id)
        db.add(source)
    changed_feed = (
        source.provider != data.provider
        or source.country_slug != data.country_slug
        or (source.feed_url or None) != ((data.feed_url or "").strip() or None)
    )
    source.provider = data.provider
    source.country_slug = data.country_slug if data.provider == "officeholidays" else None
    source.feed_url = (data.feed_url or "").strip() or None if data.provider == "ics_url" else None
    source.include_regions = sorted(set(data.include_regions))
    source.auto_sync = data.auto_sync
    if changed_feed:
        # A different feed: the old region list and status describe the old one.
        source.discovered_regions = None
        source.last_status = None
        source.last_error = None
        source.last_attempt_at = None
    await db.flush()
    return await _source_response(db, current_user, source)


@router.get("/holidays/source/regions")
async def get_holiday_regions(
    refresh: bool = Query(False),
    current_user: User = Depends(_require_holiday_admin("edit")),
    db: AsyncSession = Depends(get_db),
):
    """The regions the feed has regional holidays for, for the region picker.
    From the last sync unless `refresh` (which reads the feed, writing nothing)."""
    from app.services import holiday_sync_service as hs

    source = await hs.get_source(db, current_user.tenant_id)
    if source is None:
        raise HTTPException(status_code=400, detail="Set up a holiday calendar source first.")
    if source.discovered_regions is not None and not refresh:
        return source.discovered_regions
    try:
        return hs.discover_regions(await hs.fetch_holidays(source))
    except hs.HolidayFeedError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/holidays/sync", response_model=HolidaySyncResponse)
async def sync_holidays(
    dry_run: bool = Query(
        False,
        description="Report what a sync would add, change and remove without writing anything.",
    ),
    current_user: User = Depends(_require_holiday_admin("edit")),
    db: AsyncSession = Depends(get_db),
):
    """Sync holidays from the feed now (or preview it with dry_run=true)."""
    from app.services import holiday_sync_service as hs

    try:
        return await hs.sync_tenant(db, current_user.tenant_id, dry_run=dry_run, actor=current_user)
    except hs.HolidayFeedError as exc:
        # Keep the recorded failure (last_status / last_error) for the card.
        await db.commit()
        raise HTTPException(status_code=502, detail=str(exc))


# ── Templates ────────────────────────────────────────────────────────

@router.get("/templates", response_model=List[TemplateResponse])
async def get_templates(
    current_user: User = Depends(require_permission("schedules", "view")),
    db: AsyncSession = Depends(get_db),
):
    templates = await ScheduleService.get_templates(
        db, tenant_id=current_user.tenant_id
    )
    return [TemplateResponse.model_validate(t) for t in templates]


@router.post("/templates", response_model=TemplateResponse, status_code=201)
async def create_template(
    data: TemplateCreate,
    current_user: User = Depends(require_permission("schedules", "create")),
    db: AsyncSession = Depends(get_db),
):
    template = await ScheduleService.create_template(
        db,
        tenant_id=current_user.tenant_id,
        data=data.model_dump(),
        created_by=current_user.id,
    )
    return TemplateResponse.model_validate(template)


@router.post("/templates/{template_id}/apply", response_model=TemplateApplyResult, status_code=201)
async def apply_template(
    template_id: int,
    data: TemplateApply,
    current_user: User = Depends(require_permission("schedules", "create")),
    db: AsyncSession = Depends(get_db),
):
    await access_scope.assert_manages(db, current_user, data.employee_ids, "schedules", own="shifts")
    skipped: list = []
    shifts = await ScheduleService.apply_template(
        db,
        tenant_id=current_user.tenant_id,
        template_id=template_id,
        employee_ids=data.employee_ids,
        start_date=data.start_date,
        end_date=data.end_date,
        created_by=current_user.id,
        force=data.force,
        skipped=skipped,
        actor=current_user,
    )
    return TemplateApplyResult(
        created=[ShiftResponse.model_validate(s) for s in shifts],
        skipped_conflicts=skipped,
    )


# ── Bulk Delete Shifts ────────────────────────────────────────────

@router.post("/shifts/bulk-delete", response_model=ShiftBulkDeleteResponse)
async def bulk_delete_shifts(
    data: ShiftBulkDelete,
    current_user: User = Depends(require_permission("schedules", "delete")),
    db: AsyncSession = Depends(get_db),
):
    """Delete the shifts of exactly the listed employees in the range ("Clear
    all shifts in current view").

    The list is required and an empty one deletes nothing. It used to be
    optional, and absent meant the whole company, so a view filtered to one
    team deleted every team's range. Approved-leave days are kept unless
    include_leave is set, because deleting one silently un-does a leave
    decision. dry_run returns the same counts without deleting, so the
    confirmation can state exactly what the button will do."""
    ids = await access_scope.scope_employee_ids(
        db, current_user, data.employee_ids, "schedules", leave_out_own=True
    )
    result = await ScheduleService.bulk_delete_shifts(
        db,
        tenant_id=current_user.tenant_id,
        start_date=data.start_date,
        end_date=data.end_date,
        employee_ids=ids,
        include_leave=data.include_leave,
        dry_run=data.dry_run,
        actor=current_user,
    )
    removed = result.pop("published_removed", {})
    if not data.dry_run:
        await _notify_published_removed(
            db, current_user, removed, "was removed from your schedule"
        )
    return result


# ── Schedule Snapshots ───────────────────────────────────────────

@router.get("/snapshots", response_model=List[SnapshotResponse])
async def list_snapshots(
    current_user: User = Depends(require_permission("schedules", "view")),
    db: AsyncSession = Depends(get_db),
):
    snapshots = await ScheduleService.get_snapshots(db, tenant_id=current_user.tenant_id)
    return [SnapshotResponse.model_validate(s) for s in snapshots]


@router.post("/snapshots", response_model=SnapshotResponse, status_code=201)
async def create_snapshot(
    data: SnapshotCreate,
    current_user: User = Depends(require_permission("schedules", "edit")),
    db: AsyncSession = Depends(get_db),
):
    # Capture only the employees the caller asked for (the grid sends the rows
    # it shows) and can see. It used to capture the whole company's range.
    snapshot = await ScheduleService.create_snapshot(
        db,
        tenant_id=current_user.tenant_id,
        name=data.name,
        description=data.description,
        start_date=data.start_date,
        end_date=data.end_date,
        range_type=data.range_type,
        created_by=current_user.id,
        employee_ids=await _read_scope(db, current_user, data.employee_ids),
    )
    return SnapshotResponse.model_validate(snapshot)


async def _snapshot_employee_ids(db, user, requested):
    """None from the client means "the snapshot's own employees"; narrow that
    to the ones the caller manages so nobody else's calendar is written."""
    return await access_scope.scope_employee_ids(db, user, requested, "schedules", leave_out_own=True)


@router.post("/snapshots/{snapshot_id}/preview", response_model=SnapshotPreviewResponse)
async def preview_snapshot(
    snapshot_id: int,
    data: SnapshotPreviewRequest,
    current_user: User = Depends(require_permission("schedules", "edit")),
    db: AsyncSession = Depends(get_db),
):
    """Dry-run: show the occurrences and conflicts a repeat-apply would produce,
    without writing any shifts."""
    result = await ScheduleService.preview_snapshot_apply(
        db,
        tenant_id=current_user.tenant_id,
        snapshot_id=snapshot_id,
        target_start_date=data.target_start_date,
        repeat_until=data.repeat_until,
        employee_ids=await _snapshot_employee_ids(db, current_user, data.employee_ids),
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return result


@router.post("/snapshots/{snapshot_id}/apply", response_model=SnapshotApplyResult, status_code=201)
async def apply_snapshot(
    snapshot_id: int,
    data: SnapshotApply,
    current_user: User = Depends(require_permission("schedules", "edit")),
    db: AsyncSession = Depends(get_db),
):
    result = await ScheduleService.apply_snapshot(
        db,
        tenant_id=current_user.tenant_id,
        snapshot_id=snapshot_id,
        target_start_date=data.target_start_date,
        employee_ids=await _snapshot_employee_ids(db, current_user, data.employee_ids),
        created_by=current_user.id,
        repeat_until=data.repeat_until,
        on_conflict=data.on_conflict,
        actor=current_user,
    )
    await _notify_published_removed(
        db, current_user, result.pop("published_removed", {}),
        "was replaced on your schedule",
    )
    await db.commit()
    return result


@router.delete("/snapshots/{snapshot_id}", status_code=204)
async def delete_snapshot(
    snapshot_id: int,
    current_user: User = Depends(require_permission("schedules", "edit")),
    db: AsyncSession = Depends(get_db),
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
    """The employees whose week is copied onto themselves: the ones asked for
    (the grid sends the rows it shows), narrowed to the ones the caller
    manages. Absent means everyone they manage; an empty list means nobody."""
    return await access_scope.scope_employee_ids(
        db, current_user, data.employee_ids, "schedules", leave_out_own=True
    )


@router.post("/copy-week/preview", response_model=SnapshotPreviewResponse)
async def preview_copy_week(
    data: CopyWeekRequest,
    current_user: User = Depends(require_permission("schedules", "create")),
    db: AsyncSession = Depends(get_db),
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
    current_user: User = Depends(require_permission("schedules", "create")),
    db: AsyncSession = Depends(get_db),
):
    """Copy the source window's shifts into the target window (default: next
    week) for the chosen employees, skipping/overwriting per on_conflict.
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
        actor=current_user,
    )
    await _notify_published_removed(
        db, current_user, result.pop("published_removed", {}),
        "was replaced on your schedule",
    )
    await db.commit()
    return result


# ── Guardrail lint ───────────────────────────────────────────────────

@router.post("/lint", response_model=ScheduleLintResponse)
async def lint_schedule(
    data: ScheduleLintRequest,
    current_user: User = Depends(require_permission("schedules", "view")),
    db: AsyncSession = Depends(get_db),
):
    """Report guardrail violations (consecutive-days / rest-days / work-on-leave)
    in the existing shifts for the range, so the grid can flag them inline.
    Read-only, and limited to the employees asked for that the caller can see
    (the grid sends the rows it shows)."""
    violations = await ScheduleService.lint_schedule(
        db,
        tenant_id=current_user.tenant_id,
        start_date=data.start_date,
        end_date=data.end_date,
        employee_ids=await _read_scope(db, current_user, data.employee_ids),
    )
    return {"violations": violations}


# ── Draft / publish ──────────────────────────────────────────────────

@router.post("/publish", response_model=PublishRangeResponse)
async def publish_schedule_range(
    data: PublishRangeRequest,
    current_user: User = Depends(require_permission("schedules", "edit")),
    db: AsyncSession = Depends(get_db),
):
    """Release the DRAFT shifts of the listed employees in the range, and
    notify each affected employee that their schedule is published.

    The grid sends exactly the rows it shows. An empty list publishes nothing
    (it used to mean everyone), and dry_run returns the counts without
    publishing so the confirmation matches what the button will do."""
    from app.services.notification_service import NotificationService

    ids = await access_scope.scope_employee_ids(
        db, current_user, data.employee_ids, "schedules"
    )
    result = await ScheduleService.publish_range(
        db,
        tenant_id=current_user.tenant_id,
        start_date=data.start_date,
        end_date=data.end_date,
        employee_ids=ids,
        published_by=current_user.id,
        dry_run=data.dry_run,
        actor=current_user,
    )
    affected = result["employee_ids"]
    if data.dry_run:
        return {
            "published_count": result["published_count"],
            "notified": 0,
            "employee_count": len(affected),
            "dry_run": True,
        }
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
    if affected and await _should_notify_schedule(db, current_user.tenant_id):
        await _notify_employee_ids(
            db, current_user.tenant_id, affected,
            f"Your schedule for {label} has been published.",
        )
    return {
        "published_count": result["published_count"],
        "notified": len(affected),
        "employee_count": len(affected),
        "dry_run": False,
    }


@router.post("/unpublish", response_model=UnpublishRangeResponse)
async def unpublish_schedule_range(
    data: PublishRangeRequest,
    current_user: User = Depends(require_permission("schedules", "edit")),
    db: AsyncSession = Depends(get_db),
):
    """Return published shifts of the listed employees in the range to DRAFT
    (hidden from employees) so they can be reworked. The employees are told:
    a schedule they may have planned around has been withdrawn."""
    from app.services.notification_service import NotificationService

    ids = await access_scope.scope_employee_ids(
        db, current_user, data.employee_ids, "schedules"
    )
    result = await ScheduleService.unpublish_range(
        db,
        tenant_id=current_user.tenant_id,
        start_date=data.start_date,
        end_date=data.end_date,
        employee_ids=ids,
        dry_run=data.dry_run,
        actor=current_user,
    )
    affected = result.pop("employee_ids")
    if data.dry_run:
        return {**result, "employee_count": len(affected), "notified": 0, "dry_run": True}

    label = f"{data.start_date.isoformat()} – {data.end_date.isoformat()}"
    body = (
        f"Your published schedule for {label} was withdrawn for changes. "
        "You will be notified when it is published again."
    )
    for emp_id in affected:
        await NotificationService.notify(
            db, current_user.tenant_id, emp_id,
            type="schedule_unpublished",
            title="Your schedule was withdrawn for changes",
            body=body,
        )
    await db.commit()
    if affected and await _should_notify_schedule(db, current_user.tenant_id):
        await _notify_employee_ids(db, current_user.tenant_id, affected, body)
    return {**result, "employee_count": len(affected), "notified": len(affected), "dry_run": False}


# ── Export ───────────────────────────────────────────────────────────

@router.get("/export")
async def export_schedule(
    start_date: date = Query(...),
    end_date: date = Query(...),
    current_user: User = Depends(require_permission("schedules", "view")),
    db: AsyncSession = Depends(get_db),
):
    # Limited to the employees the caller can see; it used to be every
    # employee in the company for anyone on the editor role list.
    csv_content = await ScheduleService.export_shifts_csv(
        db,
        tenant_id=current_user.tenant_id,
        start_date=start_date,
        end_date=end_date,
        employee_ids=await _visible_ids(db, current_user),
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
    """One schedule change request. Readable by the requester, the swap
    partner, anyone with a step on it, and people with schedules:view whose
    scope covers the requester. It used to be readable by anyone in the
    company who guessed an id."""
    result = await db.execute(
        select(ScheduleChangeRequest)
        .options(*_CHANGE_REQUEST_LOAD)
        .where(
            ScheduleChangeRequest.id == request_id,
            ScheduleChangeRequest.tenant_id == current_user.tenant_id,
        )
    )
    request = result.scalar_one_or_none()
    if not request or not await _may_read_request(db, current_user, request):
        raise HTTPException(status_code=404, detail="Request not found")
    return _request_to_response(request)


async def _may_read_request(db: AsyncSession, user: User, r: ScheduleChangeRequest) -> bool:
    if user.id in (r.requester_id, r.target_employee_id):
        return True
    if any(s.approver_id == user.id for s in (r.approval_steps or [])):
        return True
    if not await _can(db, user, "schedules", "view"):
        return False
    managed = await access_scope.managed_employee_ids(db, user, "schedules")
    return managed is None or r.requester_id in managed


async def _notify_request_decision(db: AsyncSession, current_user: User, r: ScheduleChangeRequest, decision: str):
    """In-app notice of a final decision to the requester and, for a swap, to
    the colleague whose shifts moved too (they used to hear nothing)."""
    from app.services.notification_service import NotificationService

    when = r.date.isoformat() + (f" to {r.end_date.isoformat()}" if r.end_date and r.end_date > r.date else "")
    kind = "swap" if r.request_type == "swap" else "schedule change"
    word = "approved" if decision == "approved" else "rejected"
    requester_name = f"{r.requester.first_name} {r.requester.last_name}" if r.requester else "A colleague"
    recipients = [(r.requester_id, f"Your {kind} request for {when} was {word}.")]
    if r.request_type == "swap" and r.target_employee_id:
        recipients.append((
            r.target_employee_id,
            f"The swap {requester_name} asked you for on {when} was {word}."
            + (" Your schedule has changed." if decision == "approved" else ""),
        ))
    for emp_id, body in recipients:
        await NotificationService.notify(
            db, current_user.tenant_id, emp_id,
            type="schedule_change_decision",
            title=f"Schedule {kind} {word}",
            body=body,
            action_type="schedule_change_request",
            action_ref_id=r.id,
        )
    # The partner of an approved swap also gets the usual schedule email.
    if (
        decision == "approved" and r.request_type == "swap" and r.target_employee_id
        and await _should_notify_schedule(db, current_user.tenant_id)
    ):
        await _notify_employee_ids(
            db, current_user.tenant_id, [r.target_employee_id],
            f"Your shift on {when} was swapped with {requester_name}.",
        )


@router.post("/change-requests/{request_id}/review")
async def review_schedule_change_request(
    request_id: int,
    review: ScheduleChangeReviewRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Approve or reject a schedule change/swap request step.

    A swap partner answers their own peer step. A manager step is an edit of
    other people's shifts, so approving one needs schedules:edit and scope
    over the requester (and swap partner), like any other shift write. The
    final approval applies the change through the grid's validator: a
    conflict returns 409 with the list, and `force` overrides guardrails
    (never leave)."""
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

    if review.action == "approve" and my_step.step_type != "peer_approval":
        if not await _can(db, current_user, "schedules", "edit"):
            raise HTTPException(
                status_code=403,
                detail="Approving a schedule change needs permission to edit schedules.",
            )
        await access_scope.assert_manages(
            db, current_user, [request.requester_id, request.target_employee_id], "schedules",
            own="shifts",
        )

    try:
        new_status = await ScheduleChangeService.process_step_decision(
            db, request, my_step, review.action, review.notes, current_user.id,
            force=review.force, actor=current_user,
        )
    except ScheduleConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Approving this would break the schedule rules below.",
                "conflicts": exc.conflicts,
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Reload for response
    result = await db.execute(
        select(ScheduleChangeRequest)
        .options(*_CHANGE_REQUEST_LOAD)
        .where(ScheduleChangeRequest.id == request_id)
        .execution_options(populate_existing=True)
    )
    loaded = result.scalar_one()

    # On a FINAL decision, notify the requester (fire-and-forget). A rejection
    # at any step is final; an approval is only final once no pending steps remain.
    if new_status in ("approved", "rejected"):
        await _notify_request_decision(db, current_user, loaded, new_status)
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


@router.post("/change-requests/{request_id}/cancel", response_model=ScheduleChangeRequestResponse)
async def cancel_schedule_change_request(
    request_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cancel a pending schedule change/swap request (only the requester can
    cancel). Returns the request, as the client always expected (it used to
    return a bare {"status": "cancelled"})."""
    result = await db.execute(
        select(ScheduleChangeRequest)
        .options(*_CHANGE_REQUEST_LOAD)
        .where(
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
    return _request_to_response(request)
