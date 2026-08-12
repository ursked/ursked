"""Site-wide maintenance mode gate.

This module previously also resolved a "current tenant" from the client-supplied
`X-Tenant-ID` header (falling back to subdomain/custom domain) and stashed it on
`request.state`. That was removed because:

* Nothing ever read `request.state.tenant` — every route derives the tenant from
  `current_user.tenant_id`, which comes from the signed JWT and is the only
  trustworthy source.
* Honouring a client-supplied tenant header is a cross-tenant IDOR waiting to
  happen the moment someone does start reading it.
* It cost up to three DB round-trips on separate sessions for every request,
  reachable before authentication.

Tenant scoping is enforced in the service layer via `current_user.tenant_id`.
"""

import importlib
import importlib.util
import logging
import time

from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.database import AsyncSessionLocal
from app.models.site_settings import SiteSettings

logger = logging.getLogger(__name__)

# Paths that stay reachable during maintenance so users can sign in, see status,
# and superadmins can turn maintenance back off.
MAINTENANCE_ALLOWED_PATHS = {
    "/",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/health",
    "/api/v1/site/status",
    "/api/v1/auth/login",
    "/api/v1/auth/logout",
    "/api/v1/auth/refresh",
    "/api/v1/auth/2fa/verify",
    "/api/v1/auth/me",
}

# Prefixes that stay reachable during maintenance are contributed by the
# Enterprise package (the console that toggles maintenance lives there). The
# Community build has no such package, so it names no Enterprise routes and this
# is simply empty — same "absence is the gate" pattern as the API router.
if importlib.util.find_spec("app.ee") is not None:
    MAINTENANCE_ALLOWED_PREFIXES = importlib.import_module("app.ee").MAINTENANCE_ALLOWED_PREFIXES
else:
    MAINTENANCE_ALLOWED_PREFIXES = ()

_maintenance_cache = {"value": False, "expires": 0.0}
CACHE_TTL = 5  # seconds


async def _is_maintenance_mode() -> bool:
    now = time.time()
    if now < _maintenance_cache["expires"]:
        return _maintenance_cache["value"]

    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(SiteSettings.maintenance_mode).limit(1))
            row = result.scalar_one_or_none()
            val = bool(row) if row is not None else False
            _maintenance_cache["value"] = val
            _maintenance_cache["expires"] = now + CACHE_TTL
            return val
    except Exception:
        logger.exception("Could not read maintenance mode; using last known value")
        return _maintenance_cache["value"]


class TenantMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        exempt = path in MAINTENANCE_ALLOWED_PATHS or path.startswith(
            MAINTENANCE_ALLOWED_PREFIXES
        )

        if not exempt and await _is_maintenance_mode():
            return JSONResponse(
                status_code=503,
                content={"detail": "System is under maintenance. Please try again later."},
            )

        return await call_next(request)
