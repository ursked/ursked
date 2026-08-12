"""First-boot seed for the ursked Community Edition.

Creates exactly ONE organization and ONE administrator, then gets out of the way.
This is not seed_admin.py: that one builds a demo tenant with three known users and
published passwords, which is right for development and catastrophic on someone
else's server.

Run automatically from docker-entrypoint.sh after the alembic upgrade.

Environment:
  ORG_NAME        display name of the organization        (default "My Organization")
  ADMIN_EMAIL     the administrator's login               (default "admin@localhost")
  ADMIN_PASSWORD  their initial password                  (generated if unset)
  TZ              organization timezone                   (default "UTC")
"""
import asyncio
import os
import re
import secrets

from sqlalchemy import func, select

from app.database import AsyncSessionLocal
from app.middleware.auth import get_password_hash
from app.models.settings import AppSettings
from app.models.site_settings import SiteSettings
from app.models.tenant import Tenant
from app.models.user import User
from app.services.role_service import RoleService
from app.services.settings_service import SettingsService


def env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "org"


async def seed() -> None:
    async with AsyncSessionLocal() as db:
        # Idempotent on ANY user, deliberately — not on a named tenant like the dev
        # seed does. This script runs on every container start, and the second run
        # must never mint a second administrator, whatever the org was called on the
        # first one.
        existing = await db.scalar(select(func.count()).select_from(User))
        if existing:
            print(f"[seed] {existing} user(s) already present — nothing to do.")
            return

        org_name = env("ORG_NAME", "My Organization")
        admin_email = env("ADMIN_EMAIL", "admin@localhost")
        admin_password = env("ADMIN_PASSWORD")
        generated = not admin_password
        if generated:
            admin_password = secrets.token_urlsafe(12)

        tenant = Tenant(
            name=org_name,
            slug=slugify(org_name),
            email=admin_email,
            timezone=env("TZ", "UTC"),
            # The SaaS columns exist on the model but nothing enforces them. Fill
            # them with honest single-tenant values so a self-hosted install never
            # looks like a trial about to lapse, and so a future quota check cannot
            # silently strand a Community install at ten users.
            plan="community",
            subscription_status="active",
            max_users=1_000_000,
            max_storage_gb=1_000_000,
        )
        db.add(tenant)
        await db.flush()

        await RoleService.seed_system_roles(db, tenant.id)

        admin = User(
            tenant_id=tenant.id,
            username=admin_email,
            email=admin_email,
            password_hash=get_password_hash(admin_password),
            first_name=env("ADMIN_FIRST_NAME", "Admin"),
            last_name=env("ADMIN_LAST_NAME", ""),
            # NOT a superadmin: that flag is only ever read by the cross-tenant
            # console, which the Community build does not ship. Everything this
            # administrator actually needs comes from the tenant_admin role.
            is_superadmin=False,
            is_active=True,
            must_change_password=True,
        )
        db.add(admin)
        await db.flush()

        await RoleService.assign_roles(db, admin.id, ["employee", "tenant_admin"], tenant.id)

        db.add(AppSettings(tenant_id=tenant.id))
        await db.flush()
        await SettingsService.seed_default_status_types(db, tenant.id)

        # A single-tenant self-hosted install has no public sign-up: accounts are
        # created by the administrator. Persisting registration_enabled=False makes
        # the public site-status endpoint report that, so the login page hides its
        # "Sign up" link (the signup route does not exist in this build anyway).
        db.add(SiteSettings(registration_enabled=False, maintenance_mode=False))
        await db.flush()

        await db.commit()

        line = "=" * 62
        print(line)
        print("  ursked Community Edition — first-run setup complete")
        print(line)
        print(f"  Organization : {tenant.name}")
        print(f"  Sign in as   : {admin_email}")
        if generated:
            print(f"  Password     : {admin_password}")
            print("")
            print("  This password was generated and is shown ONCE. Copy it now.")
            print("  Set ADMIN_PASSWORD in your .env to choose your own instead.")
        else:
            print("  Password     : as set in ADMIN_PASSWORD")
        print("")
        print("  You will be asked to change it on first sign-in.")
        print(line)


if __name__ == "__main__":
    asyncio.run(seed())
