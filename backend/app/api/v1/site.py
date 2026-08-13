from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.site_settings import SiteSettings

router = APIRouter(prefix="/site", tags=["Site"])


class SiteStatusResponse(BaseModel):
    maintenance_mode: bool = False
    registration_enabled: bool = True
    site_name: str = "ursked"


@router.get("/status", response_model=SiteStatusResponse)
async def get_site_status(db: AsyncSession = Depends(get_db)):
    """Public endpoint — returns maintenance mode and registration status."""
    result = await db.execute(select(SiteSettings).limit(1))
    settings = result.scalar_one_or_none()
    if not settings:
        return SiteStatusResponse()
    return SiteStatusResponse(
        maintenance_mode=settings.maintenance_mode,
        registration_enabled=settings.registration_enabled,
        site_name=settings.site_name,
    )
