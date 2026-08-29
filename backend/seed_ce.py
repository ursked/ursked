"""First-boot seed for the ursked Community Edition.

Creates exactly ONE organization and ONE administrator, then gets out of the way.
This is not seed_admin.py: that one builds a demo tenant with three known users and
published passwords, which is right for development and catastrophic on someone
else's server.

Run automatically from docker-entrypoint.sh after the alembic upgrade.

Environment:
  ORG_NAME        display name of the organization        (default "My Organization")
  ADMIN_EMAIL     the administrator's login               (default "admin@example.com")
  ADMIN_PASSWORD  their initial password                  (generated if unset)
  TZ              organization timezone                   (default "UTC")
"""
import asyncio
import os
import re
import secrets
import sys

from sqlalchemy import func, select

from app.database import AsyncSessionLocal
from app.middleware.auth import get_password_hash
from app.models.leave import LeavePolicy, LeavePolicyEntitlement, LeaveType
from app.models.payroll import SalaryGrade
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


def _password_strong(pw: str) -> bool:
    """Match the UI's change-password rules: ≥8 chars, upper, lower, digit."""
    return (
        len(pw) >= 8
        and bool(re.search(r"[A-Z]", pw))
        and bool(re.search(r"[a-z]", pw))
        and bool(re.search(r"\d", pw))
    )


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
        admin_email = env("ADMIN_EMAIL", "admin@example.com")

        # The seed writes straight to the database, bypassing the Pydantic
        # EmailStr validation every API path applies. An address the API would
        # reject (a bare host like "admin@localhost" has no dot after the @)
        # therefore creates an administrator that cannot afterwards be saved
        # through the user form — every update carrying the email field 422s.
        # Fail here instead, while it is still one env var to change.
        try:
            from email_validator import validate_email
            validate_email(admin_email, check_deliverability=False)
        except ImportError:
            pass
        except Exception as exc:
            print(
                f"[seed] ADMIN_EMAIL={admin_email!r} is not a valid email address "
                f"({exc}). The administrator account would be created but could "
                f"not be edited afterwards. Set a valid address and start again.",
                file=sys.stderr,
            )
            raise SystemExit(1)
        admin_password = env("ADMIN_PASSWORD")
        generated = not admin_password
        if generated:
            admin_password = secrets.token_urlsafe(12)
        elif not _password_strong(admin_password):
            print(
                "[seed] WARNING: ADMIN_PASSWORD does not meet strength requirements "
                "(min 8 chars, at least one uppercase, one lowercase, one digit). "
                "The account will still be created, but you should change the "
                "password on first sign-in."
            )

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

        # ── Leave types + default policy ─────────────────────────────────
        # Seed three common leave types and a default policy with one
        # approval level (employee → tenant_admin) so the leave module
        # works out of the box.
        leave_types = []
        for code, name, export_code, credits in [
            ("vacation", "Vacation", "VL", 15),
            ("sick", "Sick Leave", "SL", 10),
            ("personal", "Personal Leave", "PL", 5),
        ]:
            lt = LeaveType(
                tenant_id=tenant.id, code=code, name=name,
                export_code=export_code, is_system=True, sort_order=len(leave_types),
            )
            db.add(lt)
            leave_types.append((lt, credits))
        await db.flush()

        # Give each leave type a matching shift status type. Approving leave
        # writes the leave *code* into Shift.status, and the schedule grid
        # resolves colour/label from shift_status_types — without these rows an
        # approved sick leave renders as an unrecognised grey cell.
        for lt, _credits in leave_types:
            await SettingsService.ensure_status_type_for_leave_type(
                db, tenant.id, code=lt.code, label=lt.name, export_code=lt.export_code,
            )
        await db.flush()

        policy = LeavePolicy(
            tenant_id=tenant.id,
            name="Default",
            description="Standard leave policy seeded on first boot.",
            accrual_method="annual",
            pool_type="per_type",
            is_default=True,
            approval_mode="manual",
            required_approval_levels=1,
        )
        db.add(policy)
        await db.flush()

        for lt, credits in leave_types:
            db.add(LeavePolicyEntitlement(
                policy_id=policy.id,
                leave_type_id=lt.id,
                annual_credits=credits,
            ))
        await db.flush()

        # ── Default salary grade ─────────────────────────────────────────
        # One grade so the payroll module isn't dead on arrival. Admins
        # adjust the rate and add more grades as needed.
        db.add(SalaryGrade(
            tenant_id=tenant.id,
            code="STD",
            name="Standard",
            description="Default salary grade seeded on first boot.",
            monthly_rate=0,
            is_active=True,
        ))
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
