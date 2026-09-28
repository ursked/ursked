"""Seed SMTP config from environment on first boot (self-host / CE).

The Community Edition has no operator console to write SMTP settings, so a
self-hosted install can configure SMTP via SMTP_* env vars. On startup, if
SMTP_HOST is set, the env values are written into the single SiteSettings row
and marked active. The hosted SaaS leaves SMTP_HOST unset and this is a no-op.

Settings changed in the app always win. This used to re-apply the env values
on every restart whenever the stored host still matched SMTP_HOST, so an admin
who changed the password, port or sender under Settings -> Email lost the
change at the next restart. Now the bootstrap records a fingerprint of exactly
what it wrote (smtp_env_fingerprint) and only writes again when:

  * no SMTP host is stored yet (a fresh install), or
  * the stored SMTP settings are still exactly what the environment wrote last
    time (nobody has touched them in the app), and the environment changed.

Once an admin saves different values in the app the fingerprint no longer
matches and the environment is ignored from then on.
"""
import hashlib
import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings as app_settings
from app.models.site_settings import SiteSettings

logger = logging.getLogger(__name__)

_FIELDS = (
    "smtp_host", "smtp_port", "smtp_username", "smtp_password", "smtp_use_tls",
    "smtp_use_ssl", "smtp_from_email", "smtp_from_name", "smtp_active",
)


def smtp_fingerprint(row: SiteSettings) -> str:
    """Hash of the row's SMTP settings (the password only ever as part of it)."""
    payload = json.dumps([getattr(row, f) for f in _FIELDS], default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def bootstrap_smtp_from_env(db: AsyncSession) -> None:
    """If SMTP_HOST is configured in env, seed SiteSettings SMTP (see module
    docstring for when it may write)."""
    if not app_settings.SMTP_HOST:
        return

    result = await db.execute(select(SiteSettings).limit(1))
    row = result.scalar_one_or_none()
    created = False
    if row is None:
        row = SiteSettings()
        db.add(row)
        created = True

    if row.smtp_host:
        seeded = row.smtp_env_fingerprint
        if not seeded or seeded != smtp_fingerprint(row):
            # Configured in the app (or edited there since the env seeded it).
            logger.info("SMTP settings were changed in the app; ignoring SMTP_* environment values")
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
    fingerprint = smtp_fingerprint(row)
    if fingerprint == row.smtp_env_fingerprint:
        return  # the environment has not changed since it last seeded
    row.smtp_env_fingerprint = fingerprint

    await db.commit()
    logger.info(
        "SMTP bootstrapped from env (%s host=%s:%s)",
        "created settings row" if created else "updated settings row",
        app_settings.SMTP_HOST,
        app_settings.SMTP_PORT,
    )
