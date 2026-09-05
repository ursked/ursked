from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import require_permission
from app.models.user import User
import io

from app.services.export_pipeline import resolve_date_window
from app.schemas.data_export import (
    DataExportConfigCreate,
    DataExportConfigResponse,
    DataExportConfigUpdate,
    DataExportRequest,
    DataSourceInfo,
    PreviewResponse,
    ScheduledExportCreate,
    ScheduledExportResponse,
    ScheduledExportUpdate,
)
from app.services.data_export_service import DataExportService
from app.services.data_source_registry import (
    get_source,
    get_sources_metadata,
    namespaced_columns_touch_salary,
    request_touches_salary,
)
from app.services.salary_enrollment_service import SalaryEnrollmentService
from app.services.scheduled_export_service import (
    ScheduledExportService,
    SalaryAccessRevoked,
)
from app.services.settings_service import SettingsService

router = APIRouter(prefix="/data-export", tags=["data-export"])


async def _assert_salary_access_if_needed(
    db: AsyncSession, user: User, data: "DataExportRequest"
) -> None:
    """If the request references salary/pay data, require an active salary-viewer
    enrollment — mirroring require_salary_access() used across the app. Non-salary
    exports are unaffected. Does NOT bypass tenant_admin (enrollment is required
    of admins too, matching the rest of the salary-visibility model)."""
    if data.data_source == "multi":
        touches = namespaced_columns_touch_salary(data.columns)
    else:
        touches = request_touches_salary(data.data_source, data.columns)
    if not touches:
        return
    if not await SalaryEnrollmentService.is_viewer(db, user.tenant_id, user.id):
        raise HTTPException(
            status_code=403,
            detail="This export includes salary data, which requires an approved "
                   "salary-viewer enrollment.",
        )


# ── Data sources (must be before /configs/{id}) ──────────────────

@router.get("/sources", response_model=List[DataSourceInfo])
async def list_data_sources(
    current_user: User = Depends(require_permission("settings", "view")),
):
    return get_sources_metadata()


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
    }


@router.post("/preview", response_model=PreviewResponse)
async def preview_data(
    data: DataExportRequest,
    current_user: User = Depends(require_permission("settings", "view")),
    db: AsyncSession = Depends(get_db),
):
    """Run the export but return only the first N rows, plus the true total.

    The builder calls this on every change, which is the whole point: you can
    see what a filter or a grouping did to your data before committing to it.
    """
    try:
        await _assert_salary_access_if_needed(db, current_user, data)
        spec = _spec_from_request(data)
        limit = max(1, min(int(data.limit or 50), 500))
        rows, total, output_columns = await DataExportService.run_export(
            db, current_user.tenant_id, spec, limit=limit
        )
        rfrom, rto = resolve_date_window(data.date_preset, data.date_from, data.date_to)
        return PreviewResponse(
            columns=[k for k, _h in output_columns],
            column_headers=[{"key": k, "header": h} for k, h in output_columns],
            rows=rows,
            total=total,
            returned=len(rows),
            resolved_date_from=rfrom,
            resolved_date_to=rto,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/export")
async def export_data(
    data: DataExportRequest,
    current_user: User = Depends(require_permission("settings", "view")),
    db: AsyncSession = Depends(get_db),
):
    try:
        await _assert_salary_access_if_needed(db, current_user, data)
        spec = _spec_from_request(data)
        rows, _total, output_columns = await DataExportService.run_export(
            db, current_user.tenant_id, spec
        )

        # Monetary headers carry the tenant currency so a bare number is never
        # ambiguous about its denomination.
        currency_code = await SettingsService.get_tenant_currency(db, current_user.tenant_id)
        output_columns = _suffix_currency(output_columns, data.data_source, currency_code, data.column_aliases)

        fmt = (data.output_format or "csv").lower()
        payload, media_type, ext = DataExportService.serialise(
            rows, output_columns, fmt, sheet_name=data.data_source
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
    for key, header in output_columns:
        if key in aliases:
            out.append((key, header))
            continue
        src, col = (key.split(".", 1) if "." in key else (data_source, key))
        if column_is_monetary(src, col):
            header = f"{header} ({currency_code})"
        out.append((key, header))
    return out


@router.get("/configs", response_model=List[DataExportConfigResponse])
async def list_configs(
    current_user: User = Depends(require_permission("settings", "view")),
    db: AsyncSession = Depends(get_db),
):
    configs = await DataExportService.list_configs(db, current_user.tenant_id)
    return [_config_response(c) for c in configs]


@router.post("/configs", response_model=DataExportConfigResponse, status_code=201)
async def create_config(
    data: DataExportConfigCreate,
    current_user: User = Depends(require_permission("settings", "edit")),
    db: AsyncSession = Depends(get_db),
):
    try:
        config_data = data.model_dump()
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
            f"You already have a report called \u201c{data.name}\u201d. "
            "Give this one a different name, or open the existing one and save your changes to it.",
        )


@router.get("/configs/{config_id}", response_model=DataExportConfigResponse)
async def get_config(
    config_id: int,
    current_user: User = Depends(require_permission("settings", "view")),
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
    current_user: User = Depends(require_permission("settings", "edit")),
    db: AsyncSession = Depends(get_db),
):
    try:
        update_data = data.model_dump(exclude_unset=True)
        config = await DataExportService.update_config(
            db, current_user.tenant_id, config_id, update_data
        )
        if not config:
            raise HTTPException(404, "Export configuration not found")
        await db.commit()
        await db.refresh(config)
        return _config_response(config)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "Another report already uses that name.")


@router.delete("/configs/{config_id}", status_code=204)
async def delete_config(
    config_id: int,
    current_user: User = Depends(require_permission("settings", "delete")),
    db: AsyncSession = Depends(get_db),
):
    deleted = await DataExportService.delete_config(db, current_user.tenant_id, config_id)
    if not deleted:
        raise HTTPException(404, "Export configuration not found")
    await db.commit()


# ── Scheduled Exports CRUD ────────────────────────────────────────

@router.get("/schedules", response_model=List[ScheduledExportResponse])
async def list_schedules(
    current_user: User = Depends(require_permission("settings", "view")),
    db: AsyncSession = Depends(get_db),
):
    schedules = await ScheduledExportService.list_schedules(db, current_user.tenant_id)
    return [_schedule_response(s) for s in schedules]


@router.post("/schedules", response_model=ScheduledExportResponse, status_code=201)
async def create_schedule(
    data: ScheduledExportCreate,
    current_user: User = Depends(require_permission("settings", "edit")),
    db: AsyncSession = Depends(get_db),
):
    try:
        schedule_data = data.model_dump()
        schedule = await ScheduledExportService.create_schedule(
            db, current_user.tenant_id, schedule_data, current_user.id
        )
        await db.commit()
        await db.refresh(schedule)
        # Reload with relationship
        schedule = await ScheduledExportService.get_schedule(
            db, current_user.tenant_id, schedule.id
        )
        return _schedule_response(schedule)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.put("/schedules/{schedule_id}", response_model=ScheduledExportResponse)
async def update_schedule(
    schedule_id: int,
    data: ScheduledExportUpdate,
    current_user: User = Depends(require_permission("settings", "edit")),
    db: AsyncSession = Depends(get_db),
):
    try:
        update_data = data.model_dump(exclude_unset=True)
        schedule = await ScheduledExportService.update_schedule(
            db, current_user.tenant_id, schedule_id, update_data
        )
        if not schedule:
            raise HTTPException(404, "Scheduled export not found")
        await db.commit()
        schedule = await ScheduledExportService.get_schedule(
            db, current_user.tenant_id, schedule_id
        )
        return _schedule_response(schedule)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/schedules/{schedule_id}", status_code=204)
async def delete_schedule(
    schedule_id: int,
    current_user: User = Depends(require_permission("settings", "delete")),
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
    current_user: User = Depends(require_permission("settings", "edit")),
    db: AsyncSession = Depends(get_db),
):
    schedule = await ScheduledExportService.get_schedule(
        db, current_user.tenant_id, schedule_id
    )
    if not schedule:
        raise HTTPException(404, "Scheduled export not found")
    from datetime import datetime
    now = datetime.utcnow()
    try:
        await ScheduledExportService.execute_export(db, schedule)
        schedule.last_run_at = now
        schedule.last_run_status = "success"
        schedule.last_run_error = None
        await db.commit()
        await ScheduledExportService._record_run(
            current_user.tenant_id, schedule_id, now, "success", None
        )
        schedule = await ScheduledExportService.get_schedule(
            db, current_user.tenant_id, schedule_id
        )
        return _schedule_response(schedule)
    except SalaryAccessRevoked as e:
        schedule.last_run_at = now
        schedule.last_run_status = "failed"
        schedule.last_run_error = str(e)[:500]
        await db.commit()
        await ScheduledExportService._record_run(
            current_user.tenant_id, schedule_id, now, "failed", str(e)[:500]
        )
        raise HTTPException(403, str(e))
    except Exception as e:
        await ScheduledExportService._record_run(
            current_user.tenant_id, schedule_id, now, "failed", str(e)[:500]
        )
        raise HTTPException(500, f"Export execution failed: {str(e)}")


@router.get("/schedules/{schedule_id}/runs")
async def get_schedule_runs(
    schedule_id: int,
    current_user: User = Depends(require_permission("settings", "view")),
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


def _schedule_response(schedule) -> dict:
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
        "last_run_at": schedule.last_run_at,
        "next_run_at": schedule.next_run_at,
        "last_run_status": schedule.last_run_status,
        "last_run_error": schedule.last_run_error,
        "created_by": schedule.created_by,
        "created_at": schedule.created_at,
        "updated_at": schedule.updated_at,
    }


def _config_response(config) -> dict:
    """Hand-mapped rather than from_attributes.

    That is a trap worth naming: a field added to the model, the migration, the
    request schema AND the response schema still comes back empty unless it is
    also listed here, and nothing warns you. It is how a rename survived the
    round trip to the database and then vanished on the way back.
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
        "created_by": config.created_by,
        "created_at": config.created_at,
        "updated_at": config.updated_at,
    }
