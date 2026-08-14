"""
Invite Service

Handles invite token generation, validation, and user account activation.
"""

import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional, Tuple
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.middleware.auth import get_password_hash
from app.models.role import UserRole
from app.models.user import User, UserInviteToken

INVITE_TOKEN_EXPIRY_DAYS = 7


def _hash_token(raw: str) -> str:
    """SHA-256 hex of the raw token. Only the hash is stored, so a leaked table
    is not a set of working activation links (matches PasswordResetToken)."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


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
    ) -> Tuple[UserInviteToken, str]:
        """Create and persist a new invite token. Returns (row, raw_token). Only
        the token's hash is stored; the raw token is returned once so the caller
        can build the activation URL, and lives nowhere else."""
        raw_token = secrets.token_urlsafe(48)
        expires_at = datetime.utcnow() + timedelta(days=INVITE_TOKEN_EXPIRY_DAYS)

        invite = UserInviteToken(
            user_id=user_id,
            tenant_id=tenant_id,
            token_hash=_hash_token(raw_token),
            expires_at=expires_at,
            created_by=created_by,
        )
        db.add(invite)
        await db.flush()
        return invite, raw_token

    @staticmethod
    async def validate_token(db: AsyncSession, token: str) -> Optional[UserInviteToken]:
        """Look up a raw token by its hash. Returns the invite if valid and
        unused, else None."""
        if not token:
            return None
        stmt = select(UserInviteToken).where(
            UserInviteToken.token_hash == _hash_token(token),
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
    ) -> Tuple[UserInviteToken, str]:
        """Invalidate existing unused tokens and create a fresh one. Returns
        (row, raw_token) — see create_invite_token."""
        stmt = select(UserInviteToken).where(
            UserInviteToken.user_id == user_id,
            UserInviteToken.used_at.is_(None),
        )
        result = await db.execute(stmt)
        for old_token in result.scalars().all():
            old_token.used_at = datetime.utcnow()

        await db.flush()
        return await InviteService.create_invite_token(db, user_id, tenant_id, created_by)
