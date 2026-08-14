"""Database backup download (CE scope: tenant_admin only).

Streams a pg_dump of the entire database as a SQL file. This is a single-tenant
install, so the dump contains all the tenant's data — there is no cross-tenant
concern in CE. The endpoint is restricted to tenant_admin and rate-limited (one
concurrent dump at a time via a simple lock) to prevent resource abuse.

CE scope: download your own database dump.
Paid (not built): scheduled backups, S3 upload, incremental, cross-tenant backup console.
"""
import asyncio
import logging
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.middleware.auth import get_current_user, require_role
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/backup", tags=["Backup"])

# Prevent concurrent dumps from overloading the database.
_dump_lock = asyncio.Lock()


def _pg_dump_url() -> str:
    """Convert the asyncpg DATABASE_URL to a plain postgresql:// for pg_dump."""
    return re.sub(r"^postgresql\+asyncpg://", "postgresql://", settings.DATABASE_URL)


@router.get("/download")
async def download_backup(
    current_user: User = Depends(get_current_user),
    _=Depends(require_role(["tenant_admin"])),
    db: AsyncSession = Depends(get_db),
):
    """Stream a pg_dump of the database as a downloadable .sql file."""
    if _dump_lock.locked():
        raise HTTPException(status_code=429, detail="A backup is already in progress")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    filename = f"ursked-backup-{stamp}.sql"

    async def generate():
        async with _dump_lock:
            proc = await asyncio.create_subprocess_exec(
                "pg_dump", "--no-owner", "--no-acl", _pg_dump_url(),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            while True:
                chunk = await proc.stdout.read(65536)
                if not chunk:
                    break
                yield chunk
            await proc.wait()
            if proc.returncode != 0:
                stderr = await proc.stderr.read()
                logger.error("pg_dump failed (exit %d): %s", proc.returncode, stderr.decode())

    return StreamingResponse(
        generate(),
        media_type="application/sql",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
