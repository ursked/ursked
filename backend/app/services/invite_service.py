"""
Invite Service

Handles invite token generation, validation, and user account activation.
"""

import secrets
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.middleware.auth import get_password_hash
from app.models.role import UserRole
from app.models.user import User, UserInviteToken

INVITE_TOKEN_EXPIRY_DAYS = 7


class InviteService:

    @staticmethod
    def generate_placeholder_password() -> str:
        """Generate a random 32-char password for placeholder use."""
        return secrets.token_urlsafe(32)

    @staticmethod
    async def create_invite_token(
        db: AsyncSession,
        user_id: int,
        tenant_id: UUID,
        created_by: Optional[int] = None,
    ) -> UserInviteToken:
        """Create and persist a new invite token for the given user."""
        token = secrets.token_urlsafe(48)
        expires_at = datetime.utcnow() + timedelta(days=INVITE_TOKEN_EXPIRY_DAYS)

        invite = UserInviteToken(
            user_id=user_id,
            tenant_id=tenant_id,
            token=token,
            expires_at=expires_at,
            created_by=created_by,
        )
        db.add(invite)
        await db.flush()
        return invite

    @staticmethod
    async def validate_token(db: AsyncSession, token: str) -> Optional[UserInviteToken]:
        """Look up a token. Returns the invite if valid and unused, else None."""
        stmt = select(UserInviteToken).where(
            UserInviteToken.token == token,
            UserInviteToken.used_at.is_(None),
            UserInviteToken.expires_at > datetime.utcnow(),
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def activate_user(
        db: AsyncSession,
        invite: UserInviteToken,
        new_password: str,
    ) -> User:
        """Set the user's password, mark the token as used, clear must_change_password."""
        stmt = (
            select(User)
            .options(selectinload(User.user_roles).selectinload(UserRole.role))
            .where(User.id == invite.user_id)
        )
        result = await db.execute(stmt)
        user = result.scalar_one()

        user.password_hash = get_password_hash(new_password)
        user.must_change_password = False

        invite.used_at = datetime.utcnow()

        await db.flush()
        await db.refresh(user)
        return user

    @staticmethod
    async def resend_invite(
        db: AsyncSession,
        user_id: int,
        tenant_id: UUID,
        created_by: Optional[int] = None,
    ) -> UserInviteToken:
        """Invalidate existing unused tokens and create a fresh one."""
        stmt = select(UserInviteToken).where(
            UserInviteToken.user_id == user_id,
            UserInviteToken.used_at.is_(None),
        )
        result = await db.execute(stmt)
        for old_token in result.scalars().all():
            old_token.used_at = datetime.utcnow()

        await db.flush()
        return await InviteService.create_invite_token(db, user_id, tenant_id, created_by)
