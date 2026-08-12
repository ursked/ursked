"""Notification Service

Minimal in-app notification feed. Currently backs the salary-enrollment approval
flow, but the model is generic enough to grow into a general notifications system.
"""
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification


class NotificationService:
    @staticmethod
    async def notify(
        db: AsyncSession,
        tenant_id: UUID,
        user_id: int,
        type: str,
        title: str,
        body: Optional[str] = None,
        action_type: Optional[str] = None,
        action_ref_id: Optional[int] = None,
    ) -> Notification:
        n = Notification(
            tenant_id=tenant_id,
            user_id=user_id,
            type=type,
            title=title,
            body=body,
            action_type=action_type,
            action_ref_id=action_ref_id,
        )
        db.add(n)
        await db.flush()
        return n

    @staticmethod
    async def list_for_user(
        db: AsyncSession,
        tenant_id: UUID,
        user_id: int,
        unread_only: bool = False,
        limit: int = 50,
    ) -> List[Notification]:
        stmt = select(Notification).where(
            Notification.tenant_id == tenant_id,
            Notification.user_id == user_id,
        )
        if unread_only:
            stmt = stmt.where(Notification.is_read == False)  # noqa: E712
        stmt = stmt.order_by(Notification.is_read.asc(), Notification.created_at.desc()).limit(limit)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def unread_count(db: AsyncSession, tenant_id: UUID, user_id: int) -> int:
        from sqlalchemy import func

        stmt = select(func.count()).select_from(Notification).where(
            Notification.tenant_id == tenant_id,
            Notification.user_id == user_id,
            Notification.is_read == False,  # noqa: E712
        )
        return (await db.execute(stmt)).scalar() or 0

    @staticmethod
    async def mark_read(db: AsyncSession, tenant_id: UUID, user_id: int, notification_id: int) -> bool:
        stmt = select(Notification).where(
            Notification.id == notification_id,
            Notification.tenant_id == tenant_id,
            Notification.user_id == user_id,
        )
        n = (await db.execute(stmt)).scalar_one_or_none()
        if not n:
            return False
        n.is_read = True
        await db.flush()
        return True

    @staticmethod
    async def mark_all_read(db: AsyncSession, tenant_id: UUID, user_id: int) -> None:
        await db.execute(
            update(Notification)
            .where(
                Notification.tenant_id == tenant_id,
                Notification.user_id == user_id,
                Notification.is_read == False,  # noqa: E712
            )
            .values(is_read=True)
        )
        await db.flush()

    @staticmethod
    async def mark_actioned(db: AsyncSession, tenant_id: UUID, action_type: str, action_ref_id: int) -> None:
        """Flag every notification pointing at a now-resolved action (e.g. an
        approved/declined request) as actioned + read, so approvers don't act twice."""
        await db.execute(
            update(Notification)
            .where(
                Notification.tenant_id == tenant_id,
                Notification.action_type == action_type,
                Notification.action_ref_id == action_ref_id,
            )
            .values(is_actioned=True, is_read=True)
        )
        await db.flush()
