"""Deployment capabilities endpoint.

Advertises what this ursked install can do so the frontend can render
conditionally: the edition, the core modules present, and the installed plugins.

`edition` is computed at request time from the presence of the `app.ee`
package — the same signal the API router gates on. It is NOT a stored flag:
there is nothing to toggle, consistent with "absence is the gate". Plugins follow
the same principle: they are discovered from the `app.plugins` package at request
time (see app.services.plugin_registry), not tracked in a table.
"""
import importlib.util
from typing import List

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings as app_settings
from app.database import get_db
from app.models.site_settings import SiteSettings
from app.schemas.permission import VALID_MODULES

router = APIRouter(prefix="/capabilities", tags=["Capabilities"])


class PluginInfo(BaseModel):
    name: str
    version: str
    enabled: bool
    capabilities: List[str] = []


class CapabilitiesResponse(BaseModel):
    site_name: str = "ursked"
    version: str = app_settings.APP_VERSION
    edition: str = "community"  # "community" | "enterprise"
    core_modules: List[str] = []
    plugins: List[PluginInfo] = []


def _edition() -> str:
    # Enterprise code ships as the app.ee package; its absence is the gate.
    return "enterprise" if importlib.util.find_spec("app.ee") is not None else "community"


def _discover_plugins() -> List[PluginInfo]:
    """Read installed plugins from the registry. Never raises — a discovery
    failure yields an empty list so this public endpoint stays up."""
    try:
        from app.services import plugin_registry

        return [
            PluginInfo(
                name=m.name, version=m.version,
                enabled=m.enabled, capabilities=m.capabilities,
            )
            for m in plugin_registry.discover()
        ]
    except Exception:  # noqa: BLE001
        return []


@router.get("", response_model=CapabilitiesResponse)
async def get_capabilities(db: AsyncSession = Depends(get_db)):
    """Public: what this deployment offers (edition, core modules, plugins)."""
    result = await db.execute(select(SiteSettings.site_name).limit(1))
    site_name = result.scalar_one_or_none() or "ursked"
    return CapabilitiesResponse(
        site_name=site_name,
        version=app_settings.APP_VERSION,
        edition=_edition(),
        core_modules=list(VALID_MODULES),
        plugins=_discover_plugins(),
    )
