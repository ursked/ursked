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
]


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
            if value is not None and hasattr(settings, key):
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
        """Seed 'scheduled' and 'rest_day' system types for a new tenant."""
        for d in SYSTEM_DEFAULTS:
            status_type = ShiftStatusType(tenant_id=tenant_id, **d)
            db.add(status_type)
        await db.flush()

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
