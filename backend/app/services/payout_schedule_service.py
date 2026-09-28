"""Payout schedule CRUD + the DB-facing wrapper around the pure resolver."""
from datetime import date
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.compensation import PayoutSchedule
from app.services.payroll_compute import resolve_payout_date


# Sensible presets a tenant can start from (the UI also offers these).
PRESET_CUTOFFS = {
    "semi_monthly_15_30": [
        {"cutoff_start_day": 1, "cutoff_end_day": 15, "payout_day": 15, "payout_month_offset": 1},
        {"cutoff_start_day": 16, "cutoff_end_day": 31, "payout_day": 30, "payout_month_offset": 1},
    ],
    "semi_monthly_5_20": [
        {"cutoff_start_day": 1, "cutoff_end_day": 15, "payout_day": 20, "payout_month_offset": 0},
        {"cutoff_start_day": 16, "cutoff_end_day": 31, "payout_day": 5, "payout_month_offset": 1},
    ],
    "monthly_30": [
        {"cutoff_start_day": 1, "cutoff_end_day": 31, "payout_day": 30, "payout_month_offset": 0},
    ],
}


class PayoutScheduleService:
    @staticmethod
    async def list_schedules(db: AsyncSession, tenant_id: UUID) -> List[PayoutSchedule]:
        res = await db.execute(
            select(PayoutSchedule)
            .where(PayoutSchedule.tenant_id == tenant_id)
            .order_by(PayoutSchedule.is_active.desc(), PayoutSchedule.id)
        )
        return list(res.scalars().all())

    @staticmethod
    async def get_active(db: AsyncSession, tenant_id: UUID) -> Optional[PayoutSchedule]:
        res = await db.execute(
            select(PayoutSchedule).where(
                PayoutSchedule.tenant_id == tenant_id,
                PayoutSchedule.is_active == True,  # noqa: E712
            ).order_by(PayoutSchedule.id.desc())
        )
        return res.scalars().first()

    @staticmethod
    async def create(db: AsyncSession, tenant_id: UUID, data: dict) -> PayoutSchedule:
        # Only one active schedule per tenant: deactivate others when this is active.
        if data.get("is_active", True):
            await PayoutScheduleService._deactivate_all(db, tenant_id)
        sched = PayoutSchedule(
            tenant_id=tenant_id,
            name=data["name"],
            frequency=data.get("frequency", "semi_monthly"),
            cutoffs=data.get("cutoffs") or [],
            payout_day_adjust=data.get("payout_day_adjust", "none"),
            is_active=data.get("is_active", True),
        )
        db.add(sched)
        await db.flush()
        await db.refresh(sched)
        return sched

    @staticmethod
    async def update(db: AsyncSession, tenant_id: UUID, schedule_id: int, data: dict) -> Optional[PayoutSchedule]:
        sched = await db.get(PayoutSchedule, schedule_id)
        if not sched or sched.tenant_id != tenant_id:
            return None
        if data.get("is_active") is True and not sched.is_active:
            await PayoutScheduleService._deactivate_all(db, tenant_id)
        for k in ("name", "frequency", "cutoffs", "payout_day_adjust", "is_active"):
            if k in data and data[k] is not None:
                setattr(sched, k, data[k])
        await db.flush()
        await db.refresh(sched)
        return sched

    @staticmethod
    async def delete(db: AsyncSession, tenant_id: UUID, schedule_id: int) -> bool:
        """Delete a schedule no payroll period uses. A period records which
        schedule set its payout date; deleting it would leave that run with
        no explanation of when it pays, so that is refused with the names of
        the periods (ValueError)."""
        from app.models.payroll import PayrollPeriod

        sched = await db.get(PayoutSchedule, schedule_id)
        if not sched or sched.tenant_id != tenant_id:
            return False
        used = (await db.execute(
            select(PayrollPeriod.name).where(
                PayrollPeriod.tenant_id == tenant_id,
                PayrollPeriod.schedule_id == schedule_id,
            ).order_by(PayrollPeriod.start_date.desc())
        )).scalars().all()
        if used:
            names = ", ".join(f'"{n}"' for n in used[:3])
            more = f" and {len(used) - 3} more" if len(used) > 3 else ""
            raise ValueError(
                f"This schedule is used by the payroll period{'s' if len(used) > 1 else ''} "
                f"{names}{more}, so it cannot be deleted. Switch it off instead by "
                "making another schedule active."
            )
        await db.delete(sched)
        await db.flush()
        return True

    @staticmethod
    async def _deactivate_all(db: AsyncSession, tenant_id: UUID) -> None:
        res = await db.execute(
            select(PayoutSchedule).where(
                PayoutSchedule.tenant_id == tenant_id,
                PayoutSchedule.is_active == True,  # noqa: E712
            )
        )
        for s in res.scalars().all():
            s.is_active = False
        await db.flush()

    @staticmethod
    async def resolve(
        db: AsyncSession, tenant_id: UUID, earned_on: date,
        schedule: Optional[PayoutSchedule] = None,
    ) -> Optional[date]:
        """Resolve the payout date for an earned_on using the active (or given)
        schedule, loading tenant holidays only when a business-day adjust is set."""
        if schedule is None:
            schedule = await PayoutScheduleService.get_active(db, tenant_id)
        if not schedule or not schedule.cutoffs:
            return None
        holidays: set = set()
        if schedule.payout_day_adjust in ("prev_business_day", "next_business_day"):
            # Through holiday_calendar so a recurring holiday moves the payout
            # every year, not only in the year it was entered. The payout can
            # land a year past earned_on (month offset up to 12) plus the walk.
            from datetime import timedelta

            from app.services.holiday_calendar import holidays_between

            holidays = set((await holidays_between(
                db, tenant_id, earned_on, earned_on + timedelta(days=400)
            )).keys())
        return resolve_payout_date(
            earned_on, schedule.cutoffs,
            adjust=schedule.payout_day_adjust, holidays=holidays,
        )
