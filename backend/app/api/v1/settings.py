import asyncio
import logging
from datetime import datetime, timezone
from typing import List, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import func, select as sa_select

from app.config import settings as app_settings
from app.database import get_db
from app.middleware.auth import get_current_user, require_role
from app.models.site_settings import AuditLog
from app.models.user import User
from app.schemas.settings import (
    AppSettingsResponse,
    AppSettingsUpdate,
    ShiftStatusTypeCreate,
    ShiftStatusTypeResponse,
    ShiftStatusTypeUpdate,
    UserPreferencesResponse,
    UserPreferencesUpdate,
)
from app.services.settings_service import SettingsService

router = APIRouter(prefix="/settings", tags=["Settings"])


# ── App Settings ─────────────────────────────────────────────────────

@router.get("/app", response_model=AppSettingsResponse)
async def get_app_settings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    settings = await SettingsService.get_or_create_app_settings(db, current_user.tenant_id)
    return AppSettingsResponse.model_validate(settings)


@router.patch("/app", response_model=AppSettingsResponse)
async def update_app_settings(
    data: AppSettingsUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(["tenant_admin"])),
):
    settings = await SettingsService.update_app_settings(
        db, current_user.tenant_id, data.model_dump(exclude_unset=True)
    )
    return AppSettingsResponse.model_validate(settings)


# ── Shift Status Types ───────────────────────────────────────────────

@router.get("/status-types", response_model=List[ShiftStatusTypeResponse])
async def get_status_types(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    types = await SettingsService.get_status_types(db, current_user.tenant_id)
    return [ShiftStatusTypeResponse.model_validate(t) for t in types]


@router.post("/status-types", response_model=ShiftStatusTypeResponse, status_code=201)
async def create_status_type(
    data: ShiftStatusTypeCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(["tenant_admin"])),
):
    try:
        status_type = await SettingsService.create_status_type(
            db, current_user.tenant_id, data.model_dump()
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ShiftStatusTypeResponse.model_validate(status_type)


@router.patch("/status-types/{status_id}", response_model=ShiftStatusTypeResponse)
async def update_status_type(
    status_id: int,
    data: ShiftStatusTypeUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(["tenant_admin"])),
):
    status_type = await SettingsService.update_status_type(
        db, status_id, current_user.tenant_id, data.model_dump(exclude_unset=True)
    )
    if not status_type:
        raise HTTPException(status_code=404, detail="Status type not found")
    return ShiftStatusTypeResponse.model_validate(status_type)


@router.delete("/status-types/{status_id}", status_code=204)
async def delete_status_type(
    status_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(["tenant_admin"])),
):
    try:
        deleted = await SettingsService.delete_status_type(
            db, status_id, current_user.tenant_id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not deleted:
        raise HTTPException(status_code=404, detail="Status type not found")


# ── User Preferences ─────────────────────────────────────────────

@router.get("/preferences", response_model=UserPreferencesResponse)
async def get_user_preferences(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get current user's preferences. Any authenticated user can access their own."""
    prefs = await SettingsService.get_user_preferences(
        db, current_user.id, current_user.tenant_id
    )
    resp = UserPreferencesResponse.model_validate(prefs)
    resp.org_timezone = await SettingsService.get_tenant_timezone(db, current_user.tenant_id)
    return resp


@router.patch("/preferences", response_model=UserPreferencesResponse)
async def update_user_preferences(
    data: UserPreferencesUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update current user's preferences. Any authenticated user can update their own."""
    prefs = await SettingsService.update_user_preferences(
        db, current_user.id, current_user.tenant_id,
        data.model_dump(exclude_unset=True),
    )
    resp = UserPreferencesResponse.model_validate(prefs)
    resp.org_timezone = await SettingsService.get_tenant_timezone(db, current_user.tenant_id)
    return resp


# ── Database Backup ──────────────────────────────────────────────────

_backup_logger = logging.getLogger(__name__ + ".backup")


@router.get("/backup")
async def download_backup(
    current_user: User = Depends(get_current_user),
    _=Depends(require_role(["tenant_admin"])),
):
    """Stream a pg_dump of the database as a downloadable SQL file.

    Tenant-admin only. Runs pg_dump inside the backend container (which ships
    postgresql-client) and streams the output so the browser downloads it
    without the full dump being held in memory.
    """
    parsed = urlparse(app_settings.DATABASE_URL.replace("+asyncpg", ""))
    env = {
        "PGPASSWORD": parsed.password or "",
        "PATH": "/usr/bin:/usr/local/bin:/bin",
    }
    cmd = [
        "pg_dump",
        "-h", parsed.hostname or "db",
        "-p", str(parsed.port or 5432),
        "-U", parsed.username or "postgres",
        "-d", (parsed.path or "/ursked").lstrip("/"),
        "--no-owner",
        "--no-privileges",
    ]

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )

    async def _stream():
        try:
            while True:
                chunk = await process.stdout.read(64 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            await process.wait()
            if process.returncode != 0:
                err = await process.stderr.read()
                _backup_logger.error("pg_dump failed (rc=%d): %s", process.returncode, err.decode()[:500])

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    filename = f"ursked-backup-{stamp}.sql"

    return StreamingResponse(
        _stream(),
        media_type="application/sql",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Audit Log ────────────────────────────────────────────────────────

@router.get("/audit-log")
async def list_audit_log(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(["tenant_admin"])),
    action: Optional[str] = Query(None, description="Filter by action (e.g. login_success, login_failure)"),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
):
    """Read-only view of this tenant's own audit trail.

    CE scope: tenant admins query their OWN tenant's audit_logs.
    EE scope (not built): cross-tenant audit UI in the superadmin console.
    """
    base = sa_select(AuditLog).where(
        AuditLog.tenant_id == current_user.tenant_id,
    )
    if action:
        base = base.where(AuditLog.action == action)

    total = await db.scalar(sa_select(func.count()).select_from(base.subquery()))

    stmt = (
        base
        .order_by(AuditLog.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()

    return {
        "items": [
            {
                "id": r.id,
                "user_email": r.user_email,
                "action": r.action,
                "resource_type": r.resource_type,
                "resource_id": r.resource_id,
                "details": r.details,
                "ip_address": r.ip_address,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
    }
