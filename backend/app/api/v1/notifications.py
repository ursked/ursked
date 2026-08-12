from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import get_current_user
from app.models.user import User
from app.schemas.notification import NotificationList
from app.services.notification_service import NotificationService

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=NotificationList)
async def list_notifications(
    unread_only: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    items = await NotificationService.list_for_user(
        db, current_user.tenant_id, current_user.id, unread_only=unread_only
    )
    unread = await NotificationService.unread_count(db, current_user.tenant_id, current_user.id)
    return {"items": items, "unread_count": unread}


@router.post("/{notification_id}/read", status_code=204)
async def mark_read(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ok = await NotificationService.mark_read(
        db, current_user.tenant_id, current_user.id, notification_id
    )
    if not ok:
        raise HTTPException(404, "Notification not found")
    await db.commit()


@router.post("/read-all", status_code=204)
async def mark_all_read(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await NotificationService.mark_all_read(db, current_user.tenant_id, current_user.id)
    await db.commit()
