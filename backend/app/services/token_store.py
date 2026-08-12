"""Redis-backed stores for token revocation and brute-force throttling.

Design notes:

* Single-session logout uses a Redis JTI denylist. If Redis is unavailable this
  degrades to the token expiring naturally (15 minutes), which is acceptable —
  the cookie has already been cleared client-side.
* Global revocation ("log out everywhere", triggered by password change, role
  change or deactivation) does NOT depend on Redis. It is a `tokens_valid_from`
  timestamp on the user row, checked in `get_current_user` against the token's
  `iat`. That check is free (the row is already loaded) and survives a Redis
  outage, so the security-critical path has no external dependency.
"""

import logging
import time
from typing import Optional

import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger(__name__)

_redis: Optional[aioredis.Redis] = None

REVOKED_JTI_PREFIX = "revoked_jti:"
RATE_LIMIT_PREFIX = "ratelimit:"
LOCKOUT_PREFIX = "lockout:"
LOCKOUT_COUNT_PREFIX = "lockout_count:"


def get_redis() -> Optional[aioredis.Redis]:
    global _redis
    if _redis is None:
        try:
            _redis = aioredis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
        except Exception:
            logger.exception("Failed to initialise Redis client")
            return None
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        try:
            await _redis.aclose()
        finally:
            _redis = None


class TokenDenylist:
    """Per-token revocation for explicit logout."""

    @staticmethod
    async def revoke(jti: str, expires_at: Optional[int]) -> None:
        client = get_redis()
        if client is None or not jti:
            return
        # Only need to remember the token until it would have expired anyway.
        ttl = max(int((expires_at or 0) - time.time()), 1) if expires_at else 3600
        try:
            await client.setex(f"{REVOKED_JTI_PREFIX}{jti}", ttl, "1")
        except Exception:
            logger.warning("Could not record token revocation for jti=%s", jti, exc_info=True)

    @staticmethod
    async def is_revoked(jti: str) -> bool:
        client = get_redis()
        if client is None or not jti:
            return False
        try:
            return await client.exists(f"{REVOKED_JTI_PREFIX}{jti}") == 1
        except Exception:
            # Fail open: a Redis outage must not lock every user out. Global
            # revocation still works via User.tokens_valid_from.
            logger.warning("Revocation check unavailable for jti=%s", jti, exc_info=True)
            return False


class RateLimiter:
    """Fixed-window counter. Fails open so a Redis outage cannot deny service."""

    @staticmethod
    async def hit(key: str, limit: int, window_seconds: int) -> bool:
        """Record an attempt. Returns True if the caller is over the limit."""
        client = get_redis()
        if client is None:
            return False
        redis_key = f"{RATE_LIMIT_PREFIX}{key}"
        try:
            pipe = client.pipeline()
            pipe.incr(redis_key)
            pipe.expire(redis_key, window_seconds, nx=True)
            count, _ = await pipe.execute()
            return int(count) > limit
        except Exception:
            logger.warning("Rate limit check unavailable for key=%s", key, exc_info=True)
            return False

    @staticmethod
    async def reset(key: str) -> None:
        client = get_redis()
        if client is None:
            return
        try:
            await client.delete(f"{RATE_LIMIT_PREFIX}{key}")
        except Exception:
            logger.warning("Rate limit reset failed for key=%s", key, exc_info=True)


class AccountLockout:
    """Per-account lockout after repeated failed credential attempts."""

    @staticmethod
    async def is_locked(identifier: str) -> bool:
        client = get_redis()
        if client is None:
            return False
        try:
            return await client.exists(f"{LOCKOUT_PREFIX}{identifier}") == 1
        except Exception:
            logger.warning("Lockout check unavailable for %s", identifier, exc_info=True)
            return False

    @staticmethod
    async def record_failure(identifier: str) -> bool:
        """Returns True if this failure triggered a lockout."""
        client = get_redis()
        if client is None:
            return False
        count_key = f"{LOCKOUT_COUNT_PREFIX}{identifier}"
        window = settings.ACCOUNT_LOCKOUT_MINUTES * 60
        try:
            pipe = client.pipeline()
            pipe.incr(count_key)
            pipe.expire(count_key, window, nx=True)
            count, _ = await pipe.execute()
            if int(count) >= settings.ACCOUNT_LOCKOUT_ATTEMPTS:
                await client.setex(f"{LOCKOUT_PREFIX}{identifier}", window, "1")
                await client.delete(count_key)
                logger.warning("Account locked after repeated failures: %s", identifier)
                return True
            return False
        except Exception:
            logger.warning("Lockout tracking failed for %s", identifier, exc_info=True)
            return False

    @staticmethod
    async def clear(identifier: str) -> None:
        client = get_redis()
        if client is None:
            return
        try:
            await client.delete(
                f"{LOCKOUT_PREFIX}{identifier}", f"{LOCKOUT_COUNT_PREFIX}{identifier}"
            )
        except Exception:
            logger.warning("Lockout clear failed for %s", identifier, exc_info=True)
