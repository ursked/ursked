"""Read-only audit log for the tenant's own records (CE scope).

Exposes the audit_logs table filtered to the current user's tenant. Tenant
admins can see who did what and when — user changes, setting edits, login
activity, and any other action that writes an audit entry.

CE scope: read-only, own tenant only, tenant_admin.
Paid (not built): cross-tenant audit dashboard, log retention policies, export.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.middleware.auth import get_current_user, require_role
from app.models.site_settings import AuditLog
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/audit", tags=["Audit"])


@router.get("/logs")
async def list_audit_logs(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(["tenant_admin"])),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    action: Optional[str] = Query(None, description="Filter by action (e.g. login_success, user_create)"),
    user_id: Optional[int] = Query(None, description="Filter by acting user ID"),
):
    """Paginated audit log for this tenant. Read-only."""
    base = select(AuditLog).where(
        AuditLog.tenant_id == current_user.tenant_id,
    )
    if action:
        base = base.where(AuditLog.action == action)
    if user_id:
        base = base.where(AuditLog.user_id == user_id)

    total = await db.scalar(select(func.count()).select_from(base.subquery()))

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
                "user_id": r.user_id,
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
        "total": total or 0,
        "page": page,
        "per_page": per_page,
    }
