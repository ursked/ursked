"""Database backup download (CE-only feature).

Streams a pg_dump of the entire database as a SQL file. Because it dumps the
WHOLE database (not per-tenant), it is safe ONLY in a single-tenant install.
A runtime guard counts the tenants table and refuses with 409 if there is more
than one — this is the belt; the braces is structural (this module should not
ship in the SaaS build at all, see the CE-only mechanism discussion).

CE scope: tenant_admin downloads their own single-tenant database.
Paid (not built): per-tenant backup, scheduled, S3 upload, incremental.
"""
import asyncio
import logging
from datetime import datetime, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.middleware.auth import get_current_user, require_role
from app.models.tenant import Tenant
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/backup", tags=["Backup"])

# Prevent concurrent dumps from overloading the database.
_dump_lock = asyncio.Lock()


@router.get("/download")
async def download_backup(
    current_user: User = Depends(get_current_user),
    _=Depends(require_role(["tenant_admin"])),
    db: AsyncSession = Depends(get_db),
):
    """Stream a pg_dump of the database as a downloadable .sql file.

    Refuses if the database contains more than one tenant — a full pg_dump in a
    multi-tenant deployment would be a cross-tenant data breach.
    """
    # ── Multi-tenant safety guard ───────────────────────────────────────
    # This is the runtime control. A docstring is not a control.
    tenant_count = await db.scalar(select(func.count()).select_from(Tenant))
    if tenant_count is not None and tenant_count > 1:
        raise HTTPException(
            status_code=409,
            detail=(
                "Database backup is available only in single-tenant installs. "
                "This database contains multiple tenants; a full dump would "
                "expose other tenants' data."
            ),
        )

    if _dump_lock.locked():
        raise HTTPException(status_code=429, detail="A backup is already in progress")

    # Parse DATABASE_URL for pg_dump args. The password goes via PGPASSWORD env
    # var, not in the connection URL (which would be visible in process listings).
    parsed = urlparse(settings.DATABASE_URL.replace("+asyncpg", ""))
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
        "--no-acl",
    ]

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    filename = f"ursked-backup-{stamp}.sql"

    async def generate():
        async with _dump_lock:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            while True:
                chunk = await proc.stdout.read(65536)
                if not chunk:
                    break
                yield chunk
            await proc.wait()
            if proc.returncode != 0:
                stderr = await proc.stderr.read()
                logger.error("pg_dump failed (exit %d): %s", proc.returncode, stderr.decode()[:500])

    return StreamingResponse(
        generate(),
        media_type="application/sql",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
