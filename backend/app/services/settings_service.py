import zlib
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import AppSettings, ShiftStatusType, UserPreferences


SYSTEM_DEFAULTS = [
    {
        "code": "scheduled",
        "label": "Scheduled",
        "short_label": "Sched",
        "color": "#7c3aed",
        "bg_class": "bg-purple-100 text-purple-800",
        "category": "work",
        "is_system": True,
        "sort_order": 0,
    },
    {
        "code": "rest_day",
        "label": "Rest Day",
        "short_label": "Rest",
        "color": "#6b7280",
        "bg_class": "bg-gray-100 text-gray-600",
        "category": "rest",
        "is_system": True,
        "sort_order": 1,
    },
    {
        # A holiday the employee does not work. Categorised as "rest", not
        # "leave": it consumes no leave credit, so counting it under leave would
        # overstate leave usage in the grid stats.
        "code": "holiday_off",
        "label": "Holiday Off",
        "short_label": "HO",
        "color": "#10b981",
        "bg_class": "bg-emerald-100 text-emerald-800",
        "category": "rest",
        "is_system": True,
        "sort_order": 2,
    },
]


# Presentation for status codes the product has always shipped, mirrored from
# the frontend's SHIFT_STATUS_COLORS / SHIFT_STATUS_BG so a tenant that gets a
# status type provisioned for one of these codes sees the colour the UI has
# always used for it.
KNOWN_STATUS_PRESENTATION = {
    "sick_leave": ("#ef4444", "bg-red-100 text-red-800", "SL"),
    "personal_leave": ("#f59e0b", "bg-amber-100 text-amber-800", "PL"),
    "emergency_leave": ("#dc2626", "bg-red-100 text-red-800", "EL"),
    "annual_vacation": ("#3b82f6", "bg-blue-100 text-blue-800", "AV"),
    "offset": ("#8b5cf6", "bg-violet-100 text-violet-800", "OFF"),
    "bereavement_leave": ("#374151", "bg-gray-200 text-gray-800", "BL"),
    "paternity_leave": ("#0ea5e9", "bg-sky-100 text-sky-800", "PatL"),
    "maternity_leave": ("#ec4899", "bg-pink-100 text-pink-800", "MatL"),
    "union_leave": ("#14b8a6", "bg-teal-100 text-teal-800", "UL"),
    "fire_calamity_leave": ("#f97316", "bg-orange-100 text-orange-800", "FCL"),
    "solo_parent_leave": ("#a855f7", "bg-purple-100 text-purple-800", "SPL"),
    "special_leave_women": ("#d946ef", "bg-fuchsia-100 text-fuchsia-800", "SLW"),
    "vawc_leave": ("#e11d48", "bg-rose-100 text-rose-800", "VAWC"),
    # Codes the CE first-boot seed uses (seed_ce.py). Same presentation as their
    # long-form equivalents above so both vocabularies look identical on screen.
    "sick": ("#ef4444", "bg-red-100 text-red-800", "SL"),
    "personal": ("#f59e0b", "bg-amber-100 text-amber-800", "PL"),
    "vacation": ("#3b82f6", "bg-blue-100 text-blue-800", "VL"),
}

# Colours for leave codes we have never seen (tenant-defined types). Chosen to
# be distinguishable from each other and from the system defaults. Assignment is
# by CRC of the code, so a given code always lands on the same colour on every
# install — Python's built-in hash() is salted per process and would not.
FALLBACK_PALETTE = [
    ("#0891b2", "bg-cyan-100 text-cyan-800"),
    ("#65a30d", "bg-lime-100 text-lime-800"),
    ("#c026d3", "bg-fuchsia-100 text-fuchsia-800"),
    ("#ea580c", "bg-orange-100 text-orange-800"),
    ("#4f46e5", "bg-indigo-100 text-indigo-800"),
    ("#be123c", "bg-rose-100 text-rose-800"),
    ("#0d9488", "bg-teal-100 text-teal-800"),
    ("#7c2d12", "bg-amber-100 text-amber-900"),
]


# App-settings columns where NULL is a meaningful admin choice rather than
# "leave unchanged". Keep this list minimal and deliberate.
#   data_retention_days     -> null = retain records indefinitely
#   night_shift_start/_end  -> null = no night window, so no night differential
NULLABLE_APP_SETTINGS = {
    "data_retention_days",
    "night_shift_start",
    "night_shift_end",
}


class SettingsService:
    # ── App Settings ─────────────────────────────────────────────────

    @staticmethod
    async def get_or_create_app_settings(
        db: AsyncSession,
        tenant_id: UUID,
    ) -> AppSettings:
        stmt = select(AppSettings).where(AppSettings.tenant_id == tenant_id)
        result = await db.execute(stmt)
        settings = result.scalar_one_or_none()

        if not settings:
            settings = AppSettings(tenant_id=tenant_id)
            db.add(settings)
            await db.flush()
            await db.refresh(settings)

        return settings

    @staticmethod
    async def update_app_settings(
        db: AsyncSession,
        tenant_id: UUID,
        data: dict,
    ) -> AppSettings:
        settings = await SettingsService.get_or_create_app_settings(db, tenant_id)
        for key, value in data.items():
            if not hasattr(settings, key):
                continue
            # Callers pass exclude_unset=True, so a key being present means the
            # client sent it. For most fields None still means "no change", but
            # for NULLABLE_FIELDS None is a real value the admin chose (e.g.
            # clearing the retention policy back to "keep records indefinitely"),
            # and dropping it would make that choice impossible to save.
            if value is None and key not in NULLABLE_APP_SETTINGS:
                continue
            setattr(settings, key, value)
        await db.flush()
        await db.refresh(settings)
        return settings

    # ── Shift Status Types ───────────────────────────────────────────

    @staticmethod
    async def get_status_types(
        db: AsyncSession,
        tenant_id: UUID,
    ) -> List[ShiftStatusType]:
        stmt = (
            select(ShiftStatusType)
            .where(
                ShiftStatusType.tenant_id == tenant_id,
                ShiftStatusType.is_active == True,
            )
            .order_by(ShiftStatusType.sort_order, ShiftStatusType.code)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_all_status_types(
        db: AsyncSession,
        tenant_id: UUID,
    ) -> List[ShiftStatusType]:
        """Get all status types including inactive ones (for admin management)."""
        stmt = (
            select(ShiftStatusType)
            .where(ShiftStatusType.tenant_id == tenant_id)
            .order_by(ShiftStatusType.sort_order, ShiftStatusType.code)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def create_status_type(
        db: AsyncSession,
        tenant_id: UUID,
        data: dict,
    ) -> ShiftStatusType:
        # Check code uniqueness
        existing = await db.execute(
            select(ShiftStatusType).where(
                ShiftStatusType.tenant_id == tenant_id,
                ShiftStatusType.code == data["code"],
            )
        )
        if existing.scalar_one_or_none():
            raise ValueError(f"Status type with code '{data['code']}' already exists")

        status_type = ShiftStatusType(tenant_id=tenant_id, **data)
        db.add(status_type)
        await db.flush()
        await db.refresh(status_type)
        return status_type

    @staticmethod
    async def update_status_type(
        db: AsyncSession,
        status_id: int,
        tenant_id: UUID,
        data: dict,
    ) -> Optional[ShiftStatusType]:
        stmt = select(ShiftStatusType).where(
            ShiftStatusType.id == status_id,
            ShiftStatusType.tenant_id == tenant_id,
        )
        result = await db.execute(stmt)
        status_type = result.scalar_one_or_none()

        if not status_type:
            return None

        for key, value in data.items():
            if value is not None and hasattr(status_type, key):
                # System types: prevent changing category
                if status_type.is_system and key == "category":
                    continue
                setattr(status_type, key, value)

        await db.flush()
        await db.refresh(status_type)
        return status_type

    @staticmethod
    async def delete_status_type(
        db: AsyncSession,
        status_id: int,
        tenant_id: UUID,
    ) -> bool:
        """Delete a status type. Returns False if not found, raises ValueError if system type."""
        stmt = select(ShiftStatusType).where(
            ShiftStatusType.id == status_id,
            ShiftStatusType.tenant_id == tenant_id,
        )
        result = await db.execute(stmt)
        status_type = result.scalar_one_or_none()

        if not status_type:
            return False

        if status_type.is_system:
            raise ValueError("Cannot delete system status types")

        await db.delete(status_type)
        await db.flush()
        return True

    @staticmethod
    async def seed_default_status_types(
        db: AsyncSession,
        tenant_id: UUID,
    ) -> None:
        """Seed the system status types ('scheduled', 'rest_day', 'holiday_off')."""
        for d in SYSTEM_DEFAULTS:
            status_type = ShiftStatusType(tenant_id=tenant_id, **d)
            db.add(status_type)
        await db.flush()

    @staticmethod
    async def ensure_status_type_for_leave_type(
        db: AsyncSession,
        tenant_id: UUID,
        code: str,
        label: str,
        export_code: Optional[str] = None,
    ) -> Optional[ShiftStatusType]:
        """Guarantee the schedule grid can render a leave type.

        When a leave is approved, `overlay_leave_on_shifts` writes the leave
        type's *code* into `Shift.status`. The grid resolves colour and label by
        looking that code up in `shift_status_types`. Without a matching row the
        lookup misses and the cell falls back to grey with a truncated label, so
        approved sick leave was indistinguishable from an unknown status.

        Provisioning here rather than hardcoding a code translation keeps the two
        tables in step for tenant-defined leave types too, and routes all
        presentation through the existing admin UI so it stays editable.

        Idempotent: an existing row for the code is returned untouched, so an
        admin's colour choices are never overwritten and the
        `uq_tenant_status_code` constraint is never violated.
        """
        existing = await db.execute(
            select(ShiftStatusType).where(
                ShiftStatusType.tenant_id == tenant_id,
                ShiftStatusType.code == code,
            )
        )
        found = existing.scalar_one_or_none()
        if found:
            return found

        known = KNOWN_STATUS_PRESENTATION.get(code)
        if known:
            color, bg_class, short = known
        else:
            idx = zlib.crc32(code.encode()) % len(FALLBACK_PALETTE)
            color, bg_class = FALLBACK_PALETTE[idx]
            short = None

        # short_label is NOT NULL and capped at 10 chars, and is what the grid
        # badge shows. Prefer the tenant's own export_code (already the
        # abbreviation they use on printed schedules); otherwise initialise a
        # multi-word label ("Study Leave" -> "SL") rather than truncating it
        # mid-word ("Study Leav"). Not required to be unique, and the admin can
        # edit it under the status-type settings.
        short_label = export_code or short
        if not short_label:
            words = (label or code).replace("_", " ").split()
            if len(words) > 1:
                short_label = "".join(w[0] for w in words).upper()[:10]
            else:
                short_label = (label or code)[:10]

        status_type = ShiftStatusType(
            tenant_id=tenant_id,
            code=code,
            label=label or code,
            short_label=short_label,
            color=color,
            bg_class=bg_class,
            category="leave",
            is_system=False,
            sort_order=50,
        )
        db.add(status_type)
        await db.flush()
        return status_type

    # ── User Preferences ──────────────────────────────────────────

    @staticmethod
    async def get_user_preferences(
        db: AsyncSession,
        user_id: int,
        tenant_id: UUID,
    ) -> UserPreferences:
        """Get or create preferences row for the given user."""
        stmt = select(UserPreferences).where(UserPreferences.user_id == user_id)
        result = await db.execute(stmt)
        prefs = result.scalar_one_or_none()

        if not prefs:
            prefs = UserPreferences(user_id=user_id, tenant_id=tenant_id, preferences={})
            db.add(prefs)
            await db.flush()
            await db.refresh(prefs)

        return prefs

    @staticmethod
    async def get_tenant_timezone(db: AsyncSession, tenant_id: UUID) -> str:
        """The tenant's configured timezone (source of truth), default UTC."""
        stmt = select(AppSettings.timezone).where(AppSettings.tenant_id == tenant_id)
        tz = (await db.execute(stmt)).scalar_one_or_none()
        return tz or "UTC"

    @staticmethod
    async def get_tenant_currency(db: AsyncSession, tenant_id: UUID) -> str:
        """The tenant's master currency code (ISO 4217), default PHP."""
        stmt = select(AppSettings.currency_code).where(AppSettings.tenant_id == tenant_id)
        code = (await db.execute(stmt)).scalar_one_or_none()
        return code or "PHP"

    @staticmethod
    async def update_user_preferences(
        db: AsyncSession,
        user_id: int,
        tenant_id: UUID,
        data: dict,
    ) -> UserPreferences:
        """Merge provided keys into the existing preferences JSONB."""
        prefs = await SettingsService.get_user_preferences(db, user_id, tenant_id)
        # Shallow merge: update only the keys provided
        merged = {**(prefs.preferences or {}), **data}
        prefs.preferences = merged
        await db.flush()
        await db.refresh(prefs)
        return prefs
