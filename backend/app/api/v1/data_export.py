import io
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import require_permission
from app.models.user import User
from app.schemas.data_export import (
    DataExportConfigCreate,
    DataExportConfigResponse,
    DataExportConfigUpdate,
    DataExportRequest,
    DataSourceInfo,
    PreviewResponse,
    ReportTemplate,
    ScheduledExportCreate,
    ScheduledExportResponse,
    ScheduledExportRun,
    ScheduledExportUpdate,
)
from app.services import access_scope
from app.services import export_pipeline as pipeline
from app.services.data_export_service import DataExportService
from app.services.data_source_registry import (
    clean_source_options,
    spec_touches_salary,
    tenant_sources_metadata,
)
from app.services.export_pipeline import resolve_date_window
from app.services.permission_service import PermissionService
from app.services.report_templates import list_templates
from app.services.salary_enrollment_service import SalaryEnrollmentService
from app.services.scheduled_export_service import (
    ScheduledExportService,
    describe_next_run,
    tenant_timezone,
)
from app.services.settings_service import SettingsService

router = APIRouter(prefix="/data-export", tags=["data-export"])

# Who may do what is the `reports` row of the permission matrix (see the
# contract in permission_service):
#
#   create   run, preview and download reports, ad hoc or saved; list the data,
#            the templates, the saved reports and the schedules
#   edit     save and change reports and scheduled exports
#   delete   delete saved reports and scheduled exports
#
# (`view` is the analytics dashboards.) Until 2026-09 this router checked the
# `settings` row, so HR and Finance could export everything through the API
# while the screen said Reports was for administrators only.
#
# To WHOM a report reaches is access_scope: roles in FULL_SCOPE_ROLES["reports"]
# report on everyone, anyone else on the employees they manage. Pay data
# additionally needs an approved salary-viewer enrollment, admins included.

REPORTS_RUN = require_permission("reports", "create")
REPORTS_SAVE = require_permission("reports", "edit")
REPORTS_DELETE = require_permission("reports", "delete")


async def _can(db: AsyncSession, user: User, module: str, action: str) -> bool:
    if user.has_role("tenant_admin"):
        return True
    return await PermissionService.check_permission(
        db, user.tenant_id, [ur.role_id for ur in user.user_roles], module, action
    )


async def _assert_salary_access_if_needed(db: AsyncSession, user: User, spec: Dict[str, Any]) -> None:
    """If the report touches salary/pay data ANYWHERE (a column, a filter, a
    sort, a total, a formula), require an active salary-viewer enrollment —
    mirroring require_salary_access() used across the app. Does NOT bypass
    tenant_admin (enrollment is required of admins too)."""
    if not spec_touches_salary(spec):
        return
    if not await SalaryEnrollmentService.is_viewer(db, user.tenant_id, user.id):
        raise HTTPException(
            status_code=403,
            detail="This export includes salary data, which requires an approved "
                   "salary-viewer enrollment.",
        )


def _wants_drafts(spec: Dict[str, Any]) -> bool:
    opts = spec.get("source_options") or {}
    return bool(opts.get("include_drafts") or opts.get("schedules.include_drafts"))


async def _assert_drafts_allowed(db: AsyncSession, user: User, spec: Dict[str, Any]) -> None:
    """Draft shifts are other people's unpublished plans; seeing them is
    schedules:view, the same rule the grid follows."""
    if _wants_drafts(spec) and not await _can(db, user, "schedules", "view"):
        raise HTTPException(
            status_code=403,
            detail="Draft shifts are only available to people who can view other "
                   "employees' schedules. Turn off “Include draft shifts”.",
        )


async def _run_for(db: AsyncSession, user: User, spec: Dict[str, Any], **kw):
    """run_export as `user`: their reports scope, their view of custom fields."""
    await _assert_salary_access_if_needed(db, user, spec)
    await _assert_drafts_allowed(db, user, spec)
    scope = await access_scope.managed_employee_ids(db, user, "reports")
    return await DataExportService.run_export(
        db, user.tenant_id, spec, viewer=user, employee_scope=scope, **kw
    )


# ── Data sources and templates (must be before /configs/{id}) ────

@router.get("/sources", response_model=List[DataSourceInfo])
async def list_data_sources(
    current_user: User = Depends(REPORTS_RUN),
    db: AsyncSession = Depends(get_db),
):
    return await tenant_sources_metadata(db, current_user.tenant_id)


@router.get("/templates", response_model=List[ReportTemplate])
async def list_report_templates(current_user: User = Depends(REPORTS_RUN)):
    """Built-in reports a user can open in the builder as a starting point."""
    return list_templates()


# ── Preview & Export ─────────────────────────────────────────────

def _spec_from_request(data: DataExportRequest) -> dict:
    """One dict shape shared by preview, download and the scheduler."""
    return {
        "data_source": data.data_source,
        "columns": data.columns,
        "custom_columns": [{"name": c.name, "formula": c.formula} for c in data.custom_columns],
        "filters": [
            {"column": f.column, "operator": f.operator, "value": f.value}
            for f in (data.filters or [])
        ],
        "group_by": data.group_by,
        "aggregations": [a.model_dump() for a in data.aggregations],
        "column_aliases": data.column_aliases,
        "column_formats": {k: v.model_dump() for k, v in (data.column_formats or {}).items()},
        "sorts": [s.model_dump() for s in data.sorts],
        "sort_by": data.sort_by,
        "sort_direction": data.sort_direction,
        "name_format": data.name_format,
        "date_preset": data.date_preset,
        "date_from": data.date_from,
        "date_to": data.date_to,
        "row_limit": data.row_limit,
        "layout": data.layout.model_dump(by_alias=True) if data.layout else None,
        "source_options": clean_source_options(data.data_source, data.source_options),
    }


def spec_from_config(config) -> dict:
    """Same shape, built from a saved config row."""
    return {
        "data_source": config.data_source,
        "columns": config.columns or [],
        "custom_columns": config.custom_columns or [],
        "filters": config.filters or [],
        "group_by": config.group_by or [],
        "aggregations": config.aggregations or [],
        "column_aliases": config.column_aliases or {},
        "column_formats": config.column_formats or {},
        "sorts": config.sorts or [],
        "sort_by": config.sort_by,
        "sort_direction": config.sort_direction,
        "name_format": config.name_format,
        "date_preset": config.date_preset,
        "date_from": config.date_from,
        "date_to": config.date_to,
        "row_limit": config.row_limit,
        "layout": config.layout,
        "source_options": config.source_options or {},
    }


def _context(spec: Dict[str, Any], report_name: Optional[str]) -> Dict[str, Any]:
    rfrom, rto = resolve_date_window(spec.get("date_preset"), spec.get("date_from"), spec.get("date_to"))
    return {"report_name": report_name or "", "date_from": rfrom, "date_to": rto}


@router.post("/preview", response_model=PreviewResponse)
async def preview_data(
    data: DataExportRequest,
    current_user: User = Depends(REPORTS_RUN),
    db: AsyncSession = Depends(get_db),
):
    """Run the export but return only the first N rows, plus the true total.

    The builder calls this on every change, which is the whole point: you can
    see what a filter or a grouping did to your data before committing to it.
    """
    try:
        spec = _spec_from_request(data)
        limit = max(1, min(int(data.limit or 50), 500))
        layout = spec.get("layout") or {}
        per_tab = bool((layout.get("blocks") or {}).get("sheet_per_group"))
        # One tab per block needs every row to name the tabs; otherwise only
        # the rows shown are shaped.
        rows, total, output_columns = await _run_for(
            db, current_user, spec, limit=None if per_tab else limit
        )
        ctx = _context(spec, data.report_name)
        headings = [pipeline.resolve_tokens(h.get("text"), ctx) for h in (layout.get("heading_rows") or [])]
        sheet_names: List[str] = []
        if layout:
            plans = pipeline.build_sheet_plan(
                rows if per_tab else [], output_columns, layout, ctx,
                sheet_name=data.report_name or data.data_source,
            )
            sheet_names = [p.title for p in plans]
        shown = pipeline.format_rows(rows[:limit], output_columns)
        return PreviewResponse(
            columns=[c.key for c in output_columns],
            column_headers=[{"key": c.key, "header": c.header, "type": c.type} for c in output_columns],
            rows=shown,
            total=total,
            returned=len(shown),
            resolved_date_from=ctx["date_from"],
            resolved_date_to=ctx["date_to"],
            headings=headings,
            sheet_names=sheet_names,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/export")
async def export_data(
    data: DataExportRequest,
    current_user: User = Depends(REPORTS_RUN),
    db: AsyncSession = Depends(get_db),
):
    try:
        spec = _spec_from_request(data)
        rows, _total, output_columns = await _run_for(db, current_user, spec)

        # Monetary headers carry the tenant currency so a bare number is never
        # ambiguous about its denomination.
        currency_code = await SettingsService.get_tenant_currency(db, current_user.tenant_id)
        output_columns = _suffix_currency(output_columns, data.data_source, currency_code, data.column_aliases)

        fmt = (data.output_format or "csv").lower()
        payload, media_type, ext = DataExportService.serialise(
            rows, output_columns, fmt, sheet_name=data.report_name or data.data_source,
            layout=spec.get("layout"), context=_context(spec, data.report_name),
        )
        filename = f"{data.data_source}_export.{ext}"
        return StreamingResponse(
            io.BytesIO(payload),
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


def _suffix_currency(output_columns, data_source, currency_code, aliases=None):
    """Append "(PHP)" to money column headers, unless the user renamed them."""
    if not currency_code:
        return output_columns
    from app.services.data_source_registry import column_is_monetary

    aliases = aliases or {}
    out = []
    for c in output_columns:
        key, header = c[0], c[1]
        if key in aliases:
            out.append(c)
            continue
        src, col = (key.split(".", 1) if "." in key else (data_source, key))
        if column_is_monetary(src, col):
            header = f"{header} ({currency_code})"
        out.append(c._replace(header=header) if hasattr(c, "_replace") else (key, header, *c[2:]))
    return out


@router.get("/configs", response_model=List[DataExportConfigResponse])
async def list_configs(
    current_user: User = Depends(REPORTS_RUN),
    db: AsyncSession = Depends(get_db),
):
    configs = await DataExportService.list_configs(db, current_user.tenant_id)
    return [_config_response(c) for c in configs]


@router.post("/configs", response_model=DataExportConfigResponse, status_code=201)
async def create_config(
    data: DataExportConfigCreate,
    current_user: User = Depends(REPORTS_SAVE),
    db: AsyncSession = Depends(get_db),
):
    try:
        config_data = data.model_dump()
        config_data["layout"] = data.layout.model_dump(by_alias=True) if data.layout else None
        config = await DataExportService.create_config(
            db, current_user.tenant_id, config_data, current_user.id
        )
        await db.commit()
        await db.refresh(config)
        return _config_response(config)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except IntegrityError:
        # Report names are unique per tenant. Only ValueError was caught, so
        # re-using a name produced an opaque 500 instead of saying so.
        await db.rollback()
        raise HTTPException(
            409,
            f"You already have a report called “{data.name}”. "
            "Give this one a different name, or open the existing one and save your changes to it.",
        )


@router.get("/configs/{config_id}", response_model=DataExportConfigResponse)
async def get_config(
    config_id: int,
    current_user: User = Depends(REPORTS_RUN),
    db: AsyncSession = Depends(get_db),
):
    config = await DataExportService.get_config(db, current_user.tenant_id, config_id)
    if not config:
        raise HTTPException(404, "Export configuration not found")
    return _config_response(config)


@router.put("/configs/{config_id}", response_model=DataExportConfigResponse)
async def update_config(
    config_id: int,
    data: DataExportConfigUpdate,
    current_user: User = Depends(REPORTS_SAVE),
    db: AsyncSession = Depends(get_db),
):
    try:
        update_data = data.model_dump(exclude_unset=True)
        if "layout" in update_data:
            update_data["layout"] = data.layout.model_dump(by_alias=True) if data.layout else None
        config = await DataExportService.update_config(
            db, current_user.tenant_id, config_id, update_data
        )
        if not config:
            raise HTTPException(404, "Export configuration not found")
        await db.commit()
        await db.refresh(config)
        return _config_response(config)
    except ValueError as e:
        await db.rollback()
        raise HTTPException(400, str(e))
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "Another report already uses that name.")


@router.delete("/configs/{config_id}", status_code=204)
async def delete_config(
    config_id: int,
    current_user: User = Depends(REPORTS_DELETE),
    db: AsyncSession = Depends(get_db),
):
    deleted = await DataExportService.delete_config(db, current_user.tenant_id, config_id)
    if not deleted:
        raise HTTPException(404, "Export configuration not found")
    await db.commit()


# ── Scheduled Exports CRUD ────────────────────────────────────────

@router.get("/schedules", response_model=List[ScheduledExportResponse])
async def list_schedules(
    current_user: User = Depends(REPORTS_RUN),
    db: AsyncSession = Depends(get_db),
):
    schedules = await ScheduledExportService.list_schedules(db, current_user.tenant_id)
    tz = await tenant_timezone(db, current_user.tenant_id)
    owners = await _owner_names(db, {s.created_by for s in schedules if s.created_by})
    return [_schedule_response(s, tz, owners) for s in schedules]


async def _assert_schedulable(db: AsyncSession, user: User, config_id: Optional[int]) -> None:
    """A schedule runs as the person saving it, so they must be able to run the
    report themselves today: pay data needs their enrollment, drafts need
    schedules:view."""
    if config_id is None:
        return
    config = await DataExportService.get_config(db, user.tenant_id, config_id)
    if config is None:
        raise HTTPException(400, "Export configuration not found")
    spec = spec_from_config(config)
    await _assert_salary_access_if_needed(db, user, spec)
    await _assert_drafts_allowed(db, user, spec)


@router.post("/schedules", response_model=ScheduledExportResponse, status_code=201)
async def create_schedule(
    data: ScheduledExportCreate,
    current_user: User = Depends(REPORTS_SAVE),
    db: AsyncSession = Depends(get_db),
):
    try:
        await _assert_schedulable(db, current_user, data.export_config_id)
        schedule = await ScheduledExportService.create_schedule(
            db, current_user.tenant_id, data.model_dump(), current_user.id
        )
        await db.commit()
        return await _one_schedule_response(db, current_user, schedule.id)
    except ValueError as e:
        await db.rollback()
        raise HTTPException(400, str(e))


@router.put("/schedules/{schedule_id}", response_model=ScheduledExportResponse)
async def update_schedule(
    schedule_id: int,
    data: ScheduledExportUpdate,
    current_user: User = Depends(REPORTS_SAVE),
    db: AsyncSession = Depends(get_db),
):
    """Edit, pause (is_active=false) or resume a schedule. Anything other than
    pausing or resuming makes the editor its owner (see the service)."""
    try:
        update_data = data.model_dump(exclude_unset=True)
        existing = await ScheduledExportService.get_schedule(db, current_user.tenant_id, schedule_id)
        if not existing:
            raise HTTPException(404, "Scheduled export not found")
        if any(k != "is_active" for k in update_data):
            await _assert_schedulable(
                db, current_user, update_data.get("export_config_id") or existing.export_config_id
            )
        schedule = await ScheduledExportService.update_schedule(
            db, current_user.tenant_id, schedule_id, update_data, actor_id=current_user.id
        )
        await db.commit()
        return await _one_schedule_response(db, current_user, schedule.id)
    except ValueError as e:
        await db.rollback()
        raise HTTPException(400, str(e))


@router.delete("/schedules/{schedule_id}", status_code=204)
async def delete_schedule(
    schedule_id: int,
    current_user: User = Depends(REPORTS_DELETE),
    db: AsyncSession = Depends(get_db),
):
    deleted = await ScheduledExportService.delete_schedule(
        db, current_user.tenant_id, schedule_id
    )
    if not deleted:
        raise HTTPException(404, "Scheduled export not found")
    await db.commit()


@router.post("/schedules/{schedule_id}/run-now", response_model=ScheduledExportResponse)
async def run_schedule_now(
    schedule_id: int,
    current_user: User = Depends(REPORTS_RUN),
    db: AsyncSession = Depends(get_db),
):
    """Send a schedule now, as its owner, to its recipients. Recorded in the
    run history like any other run."""
    from datetime import datetime, timezone

    schedule = await ScheduledExportService.get_schedule(
        db, current_user.tenant_id, schedule_id
    )
    if not schedule:
        raise HTTPException(404, "Scheduled export not found")
    outcome = await ScheduledExportService.run_one(
        db, schedule_id, current_user.tenant_id, datetime.now(timezone.utc), manual=True
    )
    if outcome.get("status") != "success":
        code = 403 if outcome.get("reason") == "salary" else 400
        raise HTTPException(code, outcome.get("error") or "The report could not be sent.")
    return await _one_schedule_response(db, current_user, schedule_id)


@router.get("/schedules/{schedule_id}/runs", response_model=List[ScheduledExportRun])
async def get_schedule_runs(
    schedule_id: int,
    current_user: User = Depends(REPORTS_RUN),
    db: AsyncSession = Depends(get_db),
):
    """Recent run history (from the JobRun ledger) for a scheduled export."""
    schedule = await ScheduledExportService.get_schedule(
        db, current_user.tenant_id, schedule_id
    )
    if not schedule:
        raise HTTPException(404, "Scheduled export not found")
    return await ScheduledExportService.get_run_history(
        db, current_user.tenant_id, schedule_id
    )


async def _owner_names(db: AsyncSession, ids) -> Dict[int, str]:
    if not ids:
        return {}
    rows = (
        await db.execute(select(User.id, User.first_name, User.last_name).where(User.id.in_(list(ids))))
    ).all()
    return {i: f"{f} {l}".strip() for i, f, l in rows}


async def _one_schedule_response(db: AsyncSession, user: User, schedule_id: int) -> dict:
    schedule = await ScheduledExportService.get_schedule(db, user.tenant_id, schedule_id)
    tz = await tenant_timezone(db, user.tenant_id)
    owners = await _owner_names(db, {schedule.created_by} if schedule.created_by else set())
    return _schedule_response(schedule, tz, owners)


def _schedule_response(schedule, tz: str = "UTC", owners: Optional[Dict[int, str]] = None) -> dict:
    from app.services.scheduled_export_service import _utc

    config = schedule.export_config
    return {
        "id": schedule.id,
        "tenant_id": str(schedule.tenant_id),
        "export_config_id": schedule.export_config_id,
        "export_config_name": config.name if config else "Unknown",
        "schedule_type": schedule.schedule_type,
        "schedule_day": schedule.schedule_day,
        "schedule_time": schedule.schedule_time.strftime("%H:%M") if schedule.schedule_time else "00:00",
        "recipient_emails": schedule.recipient_emails or [],
        "is_active": schedule.is_active,
        "last_run_at": _utc(schedule.last_run_at),
        "next_run_at": _utc(schedule.next_run_at),
        "next_run_local": describe_next_run(schedule.next_run_at, tz) if schedule.is_active else None,
        "timezone": tz,
        "last_run_status": schedule.last_run_status,
        "last_run_error": schedule.last_run_error,
        "created_by": schedule.created_by,
        "owner_name": (owners or {}).get(schedule.created_by),
        "created_at": schedule.created_at,
        "updated_at": schedule.updated_at,
    }


def _config_response(config) -> dict:
    """Hand-mapped rather than from_attributes.

    That is a trap worth naming: a field added to the model, the migration, the
    request schema AND the response schema still comes back empty unless it is
    also listed here, and nothing warns you. It is how a rename survived the
    round trip to the database and then vanished on the way back.
    tests/test_export_config_roundtrip.py now fails if a response field is
    missing here, so it cannot happen quietly again.
    """
    return {
        "id": config.id,
        "tenant_id": str(config.tenant_id),
        "name": config.name,
        "description": config.description,
        "data_source": config.data_source,
        "columns": config.columns or [],
        "custom_columns": config.custom_columns or [],
        "filters": config.filters,
        "sort_by": config.sort_by,
        "sort_direction": config.sort_direction,
        "name_format": config.name_format,
        "group_by": config.group_by or [],
        "aggregations": config.aggregations or [],
        "column_aliases": config.column_aliases or {},
        "column_formats": config.column_formats or {},
        "sorts": config.sorts or [],
        "date_preset": config.date_preset,
        "date_from": config.date_from,
        "date_to": config.date_to,
        "output_format": config.output_format or "csv",
        "row_limit": config.row_limit,
        "layout": config.layout,
        "source_options": config.source_options or {},
        "created_by": config.created_by,
        "created_at": config.created_at,
        "updated_at": config.updated_at,
    }
