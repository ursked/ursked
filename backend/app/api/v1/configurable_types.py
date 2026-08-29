from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import get_current_user, require_role
from app.models.configurable_types import EmployeeType, ScheduleFormat
from app.models.user import User
from app.schemas.configurable_types import (
    EmployeeTypeCreate,
    EmployeeTypeResponse,
    EmployeeTypeUpdate,
    ScheduleFormatCreate,
    ScheduleFormatResponse,
    ScheduleFormatUpdate,
)
from app.services.configurable_type_service import ConfigurableTypeService

router = APIRouter(tags=["configurable-types"])


# ── Employee Types ──────────────────────────────────────────────────────


@router.get("/employee-types", response_model=List[EmployeeTypeResponse])
async def list_employee_types(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(EmployeeType)
        .where(
            EmployeeType.tenant_id == current_user.tenant_id,
            EmployeeType.is_active == True,
        )
        .order_by(EmployeeType.sort_order, EmployeeType.name)
    )
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/employee-types/all", response_model=List[EmployeeTypeResponse])
async def list_all_employee_types(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(["tenant_admin"])),
):
    """List all employee types including inactive (for admin management)."""
    stmt = (
        select(EmployeeType)
        .where(EmployeeType.tenant_id == current_user.tenant_id)
        .order_by(EmployeeType.sort_order, EmployeeType.name)
    )
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("/employee-types/backfill")
async def backfill_employee_types(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(["tenant_admin"])),
):
    """Ensure this tenant has the generic seed employee types plus any codes
    already referenced by existing users. Fixes tenants whose type list is
    empty while users carry free-text types. Idempotent."""
    codes_result = await db.execute(
        select(User.employee_type).where(
            User.tenant_id == current_user.tenant_id,
            User.employee_type.isnot(None),
        )
    )
    in_use = {row[0] for row in codes_result.all() if row[0]}
    created = await ConfigurableTypeService.backfill_missing_types(
        db, current_user.tenant_id, extra_codes=in_use
    )
    await db.commit()
    return {"created": created, "codes_in_use": sorted(in_use)}


@router.post("/employee-types", response_model=EmployeeTypeResponse, status_code=201)
async def create_employee_type(
    data: EmployeeTypeCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(["tenant_admin"])),
):
    # Check uniqueness
    existing = await db.execute(
        select(EmployeeType).where(
            EmployeeType.tenant_id == current_user.tenant_id,
            EmployeeType.code == data.code,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(400, f"Employee type code '{data.code}' already exists")

    et = EmployeeType(
        tenant_id=current_user.tenant_id,
        code=data.code,
        name=data.name,
        description=data.description,
        sort_order=data.sort_order,
    )
    db.add(et)
    await db.commit()
    await db.refresh(et)
    return et


@router.patch("/employee-types/{type_id}", response_model=EmployeeTypeResponse)
async def update_employee_type(
    type_id: int,
    data: EmployeeTypeUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(["tenant_admin"])),
):
    et = await db.get(EmployeeType, type_id)
    if not et or et.tenant_id != current_user.tenant_id:
        raise HTTPException(404, "Employee type not found")

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(et, key, value)

    await db.commit()
    await db.refresh(et)
    return et


@router.delete("/employee-types/{type_id}", status_code=204)
async def delete_employee_type(
    type_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(["tenant_admin"])),
):
    et = await db.get(EmployeeType, type_id)
    if not et or et.tenant_id != current_user.tenant_id:
        raise HTTPException(404, "Employee type not found")

    if et.is_system:
        # System types can only be deactivated, not deleted
        et.is_active = False
        await db.commit()
        return

    # Check if any users reference this code
    from app.models.user import User as UserModel

    usage = await db.execute(
        select(UserModel.id)
        .where(
            UserModel.tenant_id == current_user.tenant_id,
            UserModel.employee_type == et.code,
        )
        .limit(1)
    )
    if usage.scalar_one_or_none():
        # In use: deactivate instead of delete
        et.is_active = False
        await db.commit()
        return

    await db.delete(et)
    await db.commit()


# ── Schedule Formats ────────────────────────────────────────────────────


@router.get("/schedule-formats", response_model=List[ScheduleFormatResponse])
async def list_schedule_formats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(ScheduleFormat)
        .where(
            ScheduleFormat.tenant_id == current_user.tenant_id,
            ScheduleFormat.is_active == True,
        )
        .order_by(ScheduleFormat.sort_order, ScheduleFormat.name)
    )
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/schedule-formats/all", response_model=List[ScheduleFormatResponse])
async def list_all_schedule_formats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(["tenant_admin"])),
):
    """List all schedule formats including inactive (for admin management)."""
    stmt = (
        select(ScheduleFormat)
        .where(ScheduleFormat.tenant_id == current_user.tenant_id)
        .order_by(ScheduleFormat.sort_order, ScheduleFormat.name)
    )
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("/schedule-formats", response_model=ScheduleFormatResponse, status_code=201)
async def create_schedule_format(
    data: ScheduleFormatCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(["tenant_admin"])),
):
    existing = await db.execute(
        select(ScheduleFormat).where(
            ScheduleFormat.tenant_id == current_user.tenant_id,
            ScheduleFormat.code == data.code,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(400, f"Schedule format code '{data.code}' already exists")

    # The four break fields must be copied explicitly. They were previously omitted
    # here while PATCH persisted them, so a format created through the API or the UI
    # silently lost its break configuration and fell back to the column defaults
    # (0 minutes). That is not cosmetic: the schedules export DERIVES the paid and
    # unpaid break clock times from these, so every export came out with empty break
    # columns until someone happened to re-save the format.
    sf = ScheduleFormat(
        tenant_id=current_user.tenant_id,
        code=data.code,
        name=data.name,
        hours_per_day=data.hours_per_day,
        hours_per_week=data.hours_per_week,
        is_flexible=data.is_flexible,
        paid_break_minutes=data.paid_break_minutes,
        unpaid_break_minutes=data.unpaid_break_minutes,
        paid_break_after_hours=data.paid_break_after_hours,
        unpaid_break_after_hours=data.unpaid_break_after_hours,
        description=data.description,
        sort_order=data.sort_order,
    )
    db.add(sf)
    await db.commit()
    await db.refresh(sf)
    return sf


@router.patch("/schedule-formats/{format_id}", response_model=ScheduleFormatResponse)
async def update_schedule_format(
    format_id: int,
    data: ScheduleFormatUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(["tenant_admin"])),
):
    sf = await db.get(ScheduleFormat, format_id)
    if not sf or sf.tenant_id != current_user.tenant_id:
        raise HTTPException(404, "Schedule format not found")

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(sf, key, value)

    await db.commit()
    await db.refresh(sf)
    return sf


@router.delete("/schedule-formats/{format_id}", status_code=204)
async def delete_schedule_format(
    format_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(["tenant_admin"])),
):
    sf = await db.get(ScheduleFormat, format_id)
    if not sf or sf.tenant_id != current_user.tenant_id:
        raise HTTPException(404, "Schedule format not found")

    if sf.is_system:
        sf.is_active = False
        await db.commit()
        return

    from app.models.user import User as UserModel

    usage = await db.execute(
        select(UserModel.id)
        .where(
            UserModel.tenant_id == current_user.tenant_id,
            UserModel.schedule_format == sf.code,
        )
        .limit(1)
    )
    if usage.scalar_one_or_none():
        sf.is_active = False
        await db.commit()
        return

    await db.delete(sf)
    await db.commit()
