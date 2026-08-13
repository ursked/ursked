"""Seed SMTP config from environment on first boot (self-host / CE).

The Community Edition has no operator console to write SMTP settings, so a
self-hosted install configures SMTP via SMTP_* env vars. On startup, if
SMTP_HOST is set, we upsert the single SiteSettings row's SMTP columns and mark
it active — idempotently, so restarts don't clobber changes an admin later makes
in-app (we only overwrite from env when the stored config still matches env or
is empty). The hosted SaaS leaves SMTP_HOST unset and this is a no-op.
"""
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings as app_settings
from app.models.site_settings import SiteSettings

logger = logging.getLogger(__name__)


async def bootstrap_smtp_from_env(db: AsyncSession) -> None:
    """If SMTP_HOST is configured in env, seed SiteSettings SMTP once."""
    if not app_settings.SMTP_HOST:
        return

    result = await db.execute(select(SiteSettings).limit(1))
    row = result.scalar_one_or_none()
    created = False
    if row is None:
        row = SiteSettings()
        db.add(row)
        created = True

    # Only seed when the row has no host yet (fresh install) OR the stored host
    # still equals the env host (env is the source of truth for that value).
    # If an admin changed the host in-app to something else, leave it alone.
    if row.smtp_host and row.smtp_host != app_settings.SMTP_HOST:
        return

    row.smtp_host = app_settings.SMTP_HOST
    row.smtp_port = app_settings.SMTP_PORT
    row.smtp_username = app_settings.SMTP_USERNAME
    row.smtp_password = app_settings.SMTP_PASSWORD
    row.smtp_use_tls = app_settings.SMTP_USE_TLS
    row.smtp_use_ssl = app_settings.SMTP_USE_SSL
    row.smtp_from_email = app_settings.SMTP_FROM_EMAIL or app_settings.SMTP_USERNAME
    row.smtp_from_name = app_settings.SMTP_FROM_NAME or row.site_name or "ursked"
    row.smtp_active = True

    await db.commit()
    logger.info(
        "SMTP bootstrapped from env (%s host=%s:%s)",
        "created settings row" if created else "updated settings row",
        app_settings.SMTP_HOST,
        app_settings.SMTP_PORT,
    )
