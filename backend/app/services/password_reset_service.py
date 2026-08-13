"""Forgot / reset password flow.

Security properties (see reference module auth-password-reset):
  * No address enumeration — request_reset always returns the same thing and does
    equivalent work whether or not the address matches an account.
  * Tokens are 32 bytes from a CSPRNG; only their SHA-256 hash is stored.
  * Short expiry, single use, and issuing a new token invalidates prior unused
    ones for that user (an old email in an inbox cannot be replayed).
  * On success: revoke every session (tokens_valid_from bump), email a
    confirmation, and do NOT sign the user in.
"""

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.middleware.auth import get_password_hash
from app.models.user import PasswordResetToken, User
from app.services.email_service import EmailService

logger = logging.getLogger(__name__)


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class PasswordResetService:

    @staticmethod
    async def request_reset(db: AsyncSession, email: str, frontend_base: str) -> None:
        """Issue a reset token and email it — but only if an active,
        password-based account matches. Always completes silently either way so
        the caller can return an identical response for any address."""
        normalized = (email or "").strip().lower()
        if not normalized:
            return

        result = await db.execute(
            select(User).where(User.email == normalized, User.is_active == True)  # noqa: E712
        )
        user = result.scalar_one_or_none()
        if not user:
            # Unknown or inactive address: do nothing, but the endpoint still
            # returns the same message.
            return

        # Invalidate any prior unused tokens for this user.
        await db.execute(
            update(PasswordResetToken)
            .where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.used_at.is_(None),
            )
            .values(used_at=datetime.now(timezone.utc))
        )

        raw_token = secrets.token_urlsafe(32)
        ttl = settings.PASSWORD_RESET_TOKEN_TTL_MINUTES
        row = PasswordResetToken(
            user_id=user.id,
            token_hash=_hash_token(raw_token),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=ttl),
        )
        db.add(row)
        await db.commit()

        reset_url = f"{frontend_base.rstrip('/')}/auth/reset-password?token={raw_token}"
        EmailService.fire_and_forget(
            lambda d, to=user.email, name=user.first_name, url=reset_url, mins=ttl:
                EmailService.send_password_reset_email(
                    d, to_email=to, first_name=name, reset_url=url, expiry_minutes=mins,
                )
        )

    @staticmethod
    async def validate_token(db: AsyncSession, raw_token: str) -> bool:
        """True if the token exists, is unused, and unexpired."""
        if not raw_token:
            return False
        result = await db.execute(
            select(PasswordResetToken).where(
                PasswordResetToken.token_hash == _hash_token(raw_token)
            )
        )
        row = result.scalar_one_or_none()
        return bool(row and PasswordResetService._token_usable(row))

    @staticmethod
    def _token_usable(row: PasswordResetToken) -> bool:
        if row.used_at is not None:
            return False
        expires = row.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return expires >= datetime.now(timezone.utc)

    @staticmethod
    async def complete_reset(db: AsyncSession, raw_token: str, new_password: str) -> bool:
        """Consume the token and set the new password. Returns False if the token
        is invalid/expired/used. On success revokes all sessions and emails a
        confirmation. Does not sign the user in."""
        if not raw_token:
            return False

        result = await db.execute(
            select(PasswordResetToken).where(
                PasswordResetToken.token_hash == _hash_token(raw_token)
            )
        )
        row = result.scalar_one_or_none()
        if not row or not PasswordResetService._token_usable(row):
            return False

        user = await db.get(User, row.user_id)
        if not user or not user.is_active:
            return False

        user.password_hash = get_password_hash(new_password)
        user.must_change_password = False
        # Revoke every existing session — a user resetting after a scare expects
        # any attacker to be signed out.
        user.tokens_valid_from = datetime.now(timezone.utc)
        row.used_at = datetime.now(timezone.utc)
        await db.commit()

        EmailService.fire_and_forget(
            lambda d, to=user.email, name=user.first_name:
                EmailService.send_password_changed_email(d, to_email=to, first_name=name)
        )
        return True
