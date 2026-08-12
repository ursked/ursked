from typing import List

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
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

@router.post("/preview", response_model=PreviewResponse)
async def preview_data(
    data: DataExportRequest,
    current_user: User = Depends(require_permission("settings", "view")),
    db: AsyncSession = Depends(get_db),
):
    try:
        await _assert_salary_access_if_needed(db, current_user, data)
        custom_cols = [{"name": c.name, "formula": c.formula} for c in data.custom_columns]
        filters = [{"column": f.column, "operator": f.operator, "value": f.value} for f in (data.filters or [])]

        if data.data_source == "multi":
            # Multi-source mode: columns are namespaced like "employees.full_name"
            rows, total = await DataExportService.query_multi_source_data(
                db=db,
                tenant_id=current_user.tenant_id,
                namespaced_columns=data.columns,
                custom_columns=custom_cols if custom_cols else None,
                filters=filters if filters else None,
                sort_by=data.sort_by,
                sort_direction=data.sort_direction,
                limit=20,
                name_format=data.name_format,
                date_from=data.date_from,
                date_to=data.date_to,
            )
            all_cols = list(data.columns)
            for cc in data.custom_columns:
                all_cols.append(cc.name)
            return PreviewResponse(columns=all_cols, rows=rows, total=total)

        rows, total = await DataExportService.query_data(
            db=db,
            tenant_id=current_user.tenant_id,
            data_source=data.data_source,
            columns=data.columns,
            custom_columns=custom_cols if custom_cols else None,
            filters=filters if filters else None,
            sort_by=data.sort_by,
            sort_direction=data.sort_direction,
            limit=20,
            name_format=data.name_format,
            date_from=data.date_from,
            date_to=data.date_to,
        )
        # Build column list for response
        all_cols = list(data.columns)
        for cc in data.custom_columns:
            all_cols.append(cc.name)
        return PreviewResponse(columns=all_cols, rows=rows, total=total)
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
        currency_code = await SettingsService.get_tenant_currency(db, current_user.tenant_id)
        custom_cols = [{"name": c.name, "formula": c.formula} for c in data.custom_columns]
        filters = [{"column": f.column, "operator": f.operator, "value": f.value} for f in (data.filters or [])]

        if data.data_source == "multi":
            # Multi-source export
            rows, total = await DataExportService.query_multi_source_data(
                db=db,
                tenant_id=current_user.tenant_id,
                namespaced_columns=data.columns,
                custom_columns=custom_cols if custom_cols else None,
                filters=filters if filters else None,
                sort_by=data.sort_by,
                sort_direction=data.sort_direction,
                name_format=data.name_format,
                date_from=data.date_from,
                date_to=data.date_to,
            )
            csv_content = DataExportService.generate_multi_csv(
                rows=rows,
                namespaced_columns=data.columns,
                custom_columns=custom_cols if custom_cols else None,
                currency_code=currency_code,
            )
            import io as _io
            return StreamingResponse(
                _io.StringIO(csv_content),
                media_type="text/csv",
                headers={"Content-Disposition": "attachment; filename=multi_source_export.csv"},
            )

        rows, total = await DataExportService.query_data(
            db=db,
            tenant_id=current_user.tenant_id,
            data_source=data.data_source,
            columns=data.columns,
            custom_columns=custom_cols if custom_cols else None,
            filters=filters if filters else None,
            sort_by=data.sort_by,
            sort_direction=data.sort_direction,
            name_format=data.name_format,
            date_from=data.date_from,
            date_to=data.date_to,
        )
        source = get_source(data.data_source)
        source_columns = source["columns"] if source else []
        csv_content = DataExportService.generate_csv(
            rows=rows,
            columns=data.columns,
            custom_columns=custom_cols if custom_cols else None,
            source_columns=source_columns,
            data_source=data.data_source,
            currency_code=currency_code,
        )
        import io
        return StreamingResponse(
            io.StringIO(csv_content),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={data.data_source}_export.csv"},
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


# ── Configs CRUD ─────────────────────────────────────────────────

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
        "created_by": config.created_by,
        "created_at": config.created_at,
        "updated_at": config.updated_at,
    }
