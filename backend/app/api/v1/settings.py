from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import get_current_user, require_role
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
