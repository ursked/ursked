from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.configurable_types import EmployeeType, ScheduleFormat


# Generic, country-neutral employment classifications. Tenants can add their
# own (e.g. jurisdiction-specific categories) via the configurable-types API.
SEED_EMPLOYEE_TYPES = [
    {"code": "full_time", "name": "Full-Time", "is_system": True, "sort_order": 0},
    {"code": "part_time", "name": "Part-Time", "is_system": True, "sort_order": 1},
    {"code": "probationary", "name": "Probationary", "sort_order": 2},
    {"code": "contractor", "name": "Contractor", "sort_order": 3},
    {"code": "intern", "name": "Intern", "sort_order": 4},
    {"code": "temporary", "name": "Temporary", "sort_order": 5},
]

SEED_SCHEDULE_FORMATS = [
    {"code": "4_hour", "name": "4-Hour Shift", "hours_per_day": 4, "hours_per_week": 20, "is_flexible": False, "paid_break_minutes": 15, "unpaid_break_minutes": 0, "paid_break_after_hours": 2.0, "unpaid_break_after_hours": 0, "sort_order": 0},
    {"code": "8_hour", "name": "8-Hour Shift", "hours_per_day": 8, "hours_per_week": 40, "is_flexible": False, "paid_break_minutes": 15, "unpaid_break_minutes": 60, "paid_break_after_hours": 4.0, "unpaid_break_after_hours": 4.0, "sort_order": 1},
    {"code": "9_hour", "name": "9-Hour Shift", "hours_per_day": 9, "hours_per_week": 45, "is_flexible": False, "paid_break_minutes": 15, "unpaid_break_minutes": 60, "paid_break_after_hours": 4.0, "unpaid_break_after_hours": 4.0, "sort_order": 2},
    {"code": "12_hour", "name": "12-Hour Shift", "hours_per_day": 12, "hours_per_week": 60, "is_flexible": False, "paid_break_minutes": 30, "unpaid_break_minutes": 60, "paid_break_after_hours": 4.0, "unpaid_break_after_hours": 6.0, "sort_order": 3},
    {"code": "flexible", "name": "Flexible Shift", "hours_per_day": None, "hours_per_week": 40, "is_flexible": True, "paid_break_minutes": 0, "unpaid_break_minutes": 0, "paid_break_after_hours": 0, "unpaid_break_after_hours": 0, "sort_order": 4},
]


class ConfigurableTypeService:

    @staticmethod
    async def seed_defaults(db: AsyncSession, tenant_id: UUID) -> None:
        """Seed default employee types and schedule formats for a new tenant."""
        for et in SEED_EMPLOYEE_TYPES:
            db.add(EmployeeType(
                tenant_id=tenant_id,
                code=et["code"],
                name=et["name"],
                is_system=et.get("is_system", False),
                sort_order=et["sort_order"],
            ))

        for sf in SEED_SCHEDULE_FORMATS:
            db.add(ScheduleFormat(
                tenant_id=tenant_id,
                code=sf["code"],
                name=sf["name"],
                hours_per_day=sf["hours_per_day"],
                hours_per_week=sf["hours_per_week"],
                is_flexible=sf["is_flexible"],
                paid_break_minutes=sf["paid_break_minutes"],
                unpaid_break_minutes=sf["unpaid_break_minutes"],
                paid_break_after_hours=sf["paid_break_after_hours"],
                unpaid_break_after_hours=sf["unpaid_break_after_hours"],
                is_system=True,
                sort_order=sf["sort_order"],
            ))

        await db.flush()

    @staticmethod
    async def active_employee_type_codes(
        db: AsyncSession, tenant_id: UUID
    ) -> set:
        """Return the set of active EmployeeType codes for a tenant."""
        result = await db.execute(
            select(EmployeeType.code).where(
                EmployeeType.tenant_id == tenant_id,
                EmployeeType.is_active == True,  # noqa: E712
            )
        )
        return {row[0] for row in result.all()}

    @staticmethod
    async def validate_employee_type(
        db: AsyncSession, tenant_id: UUID, code: Optional[str]
    ) -> bool:
        """True if `code` is None/empty or a known active employee type.

        Used to reject free-text employee_type values that don't map to a
        configured type (closing the "untyped string" integrity gap).
        """
        if not code:
            return True
        return code in await ConfigurableTypeService.active_employee_type_codes(
            db, tenant_id
        )

    @staticmethod
    async def backfill_missing_types(
        db: AsyncSession, tenant_id: UUID, extra_codes: Optional[set] = None
    ) -> int:
        """Ensure the tenant has the generic seed types plus any codes already
        in use (e.g. legacy `users.employee_type` values). Returns the number
        of types created. Idempotent."""
        # Include inactive rows in the existence check to avoid duplicate codes.
        all_result = await db.execute(
            select(EmployeeType.code).where(EmployeeType.tenant_id == tenant_id)
        )
        all_codes = {row[0] for row in all_result.all()}

        created = 0
        for et in SEED_EMPLOYEE_TYPES:
            if et["code"] not in all_codes:
                db.add(EmployeeType(
                    tenant_id=tenant_id,
                    code=et["code"],
                    name=et["name"],
                    is_system=et.get("is_system", False),
                    sort_order=et["sort_order"],
                ))
                all_codes.add(et["code"])
                created += 1

        for code in sorted((extra_codes or set()) - all_codes):
            if not code:
                continue
            db.add(EmployeeType(
                tenant_id=tenant_id,
                code=code,
                name=code.replace("_", " ").title(),
                is_system=False,
                sort_order=100,
            ))
            all_codes.add(code)
            created += 1

        if created:
            await db.flush()
        return created
