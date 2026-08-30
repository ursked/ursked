"""Work sites and the geofence expectation attached to each work arrangement."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import get_current_user, require_permission
from app.models.user import User
from app.models.work_site import WorkArrangementRule, WorkSite
from app.schemas.attendance import (
    ArrangementRuleResponse,
    ArrangementRuleUpdate,
    WorkSiteCreate,
    WorkSiteResponse,
    WorkSiteUpdate,
)
from app.services.timeclock_service import TimeclockService

router = APIRouter(prefix="/work-sites", tags=["work-sites"])


@router.get("", response_model=List[WorkSiteResponse])
async def list_work_sites(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Readable by any employee: you cannot be expected to be somewhere you are
    not allowed to look up."""
    rows = (
        await db.execute(
            select(WorkSite)
            .where(WorkSite.tenant_id == current_user.tenant_id)
            .order_by(WorkSite.name)
        )
    ).scalars().all()
    return list(rows)


@router.post("", response_model=WorkSiteResponse, status_code=201)
async def create_work_site(
    data: WorkSiteCreate,
    current_user: User = Depends(require_permission("settings", "edit")),
    db: AsyncSession = Depends(get_db),
):
    dup = (
        await db.execute(
            select(WorkSite).where(
                WorkSite.tenant_id == current_user.tenant_id,
                WorkSite.name == data.name,
            )
        )
    ).scalar_one_or_none()
    if dup:
        raise HTTPException(409, f"A work site named '{data.name}' already exists.")

    site = WorkSite(
        tenant_id=current_user.tenant_id,
        created_by=current_user.id,
        **data.model_dump(),
    )
    db.add(site)
    await db.commit()
    await db.refresh(site)
    return site


@router.patch("/{site_id}", response_model=WorkSiteResponse)
async def update_work_site(
    site_id: int,
    data: WorkSiteUpdate,
    current_user: User = Depends(require_permission("settings", "edit")),
    db: AsyncSession = Depends(get_db),
):
    site = await db.get(WorkSite, site_id)
    if not site or site.tenant_id != current_user.tenant_id:
        raise HTTPException(404, "Work site not found")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(site, key, value)
    await db.commit()
    await db.refresh(site)
    return site


@router.delete("/{site_id}", status_code=204)
async def delete_work_site(
    site_id: int,
    current_user: User = Depends(require_permission("settings", "edit")),
    db: AsyncSession = Depends(get_db),
):
    """Deactivates rather than deletes. Punches reference the site they were
    judged against, and removing it would rewrite history."""
    site = await db.get(WorkSite, site_id)
    if not site or site.tenant_id != current_user.tenant_id:
        raise HTTPException(404, "Work site not found")
    site.is_active = False
    await db.commit()


@router.get("/arrangements/rules", response_model=List[ArrangementRuleResponse])
async def list_arrangement_rules(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await TimeclockService.seed_arrangement_rules(db, current_user.tenant_id)
    await db.commit()
    rows = (
        await db.execute(
            select(WorkArrangementRule)
            .where(WorkArrangementRule.tenant_id == current_user.tenant_id)
            .order_by(WorkArrangementRule.sort_order, WorkArrangementRule.code)
        )
    ).scalars().all()
    return list(rows)


@router.patch("/arrangements/rules/{rule_id}", response_model=ArrangementRuleResponse)
async def update_arrangement_rule(
    rule_id: int,
    data: ArrangementRuleUpdate,
    current_user: User = Depends(require_permission("settings", "edit")),
    db: AsyncSession = Depends(get_db),
):
    rule = await db.get(WorkArrangementRule, rule_id)
    if not rule or rule.tenant_id != current_user.tenant_id:
        raise HTTPException(404, "Arrangement rule not found")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(rule, key, value)
    await db.commit()
    await db.refresh(rule)
    return rule
