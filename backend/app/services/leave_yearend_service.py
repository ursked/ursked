"""Year-end leave processing: carry-over, cash conversion, and expiry.

Runs on the 60-second scheduler tick via JobService, but each unit of work is
guarded by the JobRun ledger so it executes at most once per tenant per period,
regardless of how often the loop fires or how many processes run it.

Timezone handling: the "current date" for a tenant is computed in that tenant's
timezone (AppSettings.timezone, then Tenant.timezone, then UTC). So a tenant in
Kiritimati rolls into the new year ~14h before a tenant in Los Angeles, and each
gets its carry-over run at its own local Jan 1.

All money-adjacent output (cash conversion) is a computed leave-credit
adjustment with a stored rate/days in `meta`; the app never disburses money.
"""
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import AsyncSessionLocal
from app.models.attendance import LeaveCreditAdjustment
from app.models.leave import LeavePolicy, LeavePolicyEntitlement
from app.models.settings import AppSettings
from app.models.tenant import Tenant
from app.models.user import User
from app.services.leave_service import LeaveService

logger = logging.getLogger(__name__)

CARRY_OVER = "leave_carry_over"
EXPIRY = "carry_over_expiry"


def _add_months(d: date, months: int) -> date:
    """Add whole months to a date, clamping the day."""
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    # Clamp day to the last valid day of the target month.
    if month == 12:
        next_month_first = date(year + 1, 1, 1)
    else:
        next_month_first = date(year, month + 1, 1)
    last_day = (next_month_first - timedelta(days=1)).day
    return date(year, month, min(d.day, last_day))


@dataclass
class _Entitlement:
    """Normalized carry-over/cash config for one leave type (or the shared
    pool). leave_type is None for shared pools."""
    leave_type: Optional[str]
    carry_over_enabled: bool
    max_carry_over_days: float
    carry_over_expiry_months: int
    cash_convertible: bool
    cash_conversion_rate: float


class LeaveYearEndService:

    @staticmethod
    def _tenant_today(tz_name: Optional[str], now: Optional[datetime] = None) -> date:
        now = now or datetime.utcnow().replace(tzinfo=ZoneInfo("UTC"))
        if now.tzinfo is None:
            now = now.replace(tzinfo=ZoneInfo("UTC"))
        if tz_name:
            try:
                return now.astimezone(ZoneInfo(tz_name)).date()
            except (ZoneInfoNotFoundError, ValueError):
                pass
        return now.astimezone(ZoneInfo("UTC")).date()

    @staticmethod
    def _entitlements_for(policy: LeavePolicy) -> list[_Entitlement]:
        if policy.pool_type == "shared":
            return [_Entitlement(
                leave_type=None,
                carry_over_enabled=bool(policy.shared_carry_over_enabled),
                max_carry_over_days=policy.shared_max_carry_over_days or 0,
                carry_over_expiry_months=policy.shared_carry_over_expiry_months or 0,
                cash_convertible=bool(policy.shared_cash_convertible),
                cash_conversion_rate=policy.shared_cash_conversion_rate or 1.0,
            )]
        out = []
        for ent in policy.entitlements:
            out.append(_Entitlement(
                leave_type=ent.leave_type.code,
                carry_over_enabled=bool(ent.carry_over_enabled),
                max_carry_over_days=ent.max_carry_over_days or 0,
                carry_over_expiry_months=ent.carry_over_expiry_months or 0,
                cash_convertible=bool(ent.cash_convertible),
                cash_conversion_rate=ent.cash_conversion_rate or 1.0,
            ))
        return out

    # ── Public entry point ────────────────────────────────────────────

    @staticmethod
    async def run(job_service, now: Optional[datetime] = None) -> None:
        """Iterate tenants; run carry-over (yearly) and expiry (daily) as due."""
        async with AsyncSessionLocal() as db:
            tenants = (await db.execute(select(Tenant))).scalars().all()
            settings_rows = (await db.execute(select(AppSettings))).scalars().all()
            tz_by_tenant = {s.tenant_id: s.timezone for s in settings_rows}

        for tenant in tenants:
            tz = tz_by_tenant.get(tenant.id) or tenant.timezone
            today = LeaveYearEndService._tenant_today(tz, now)

            # Carry-over + cash conversion: once, on/after Jan 1, for the year
            # that just closed (today.year - 1).
            closing_year = today.year - 1
            claim = await job_service.claim(CARRY_OVER, str(closing_year), tenant.id)
            if claim is not None:
                try:
                    meta = await LeaveYearEndService._run_carry_over(
                        tenant.id, closing_year, today
                    )
                    await job_service.finish(claim, status="success", meta=meta)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Carry-over failed for tenant %s", tenant.id)
                    await job_service.finish(claim, status="failed", error=str(exc))

            # Expiry: daily.
            claim = await job_service.claim(EXPIRY, today.isoformat(), tenant.id)
            if claim is not None:
                try:
                    meta = await LeaveYearEndService._run_expiry(tenant.id, today)
                    await job_service.finish(claim, status="success", meta=meta)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Expiry failed for tenant %s", tenant.id)
                    await job_service.finish(claim, status="failed", error=str(exc))

    # ── Carry-over + cash conversion ──────────────────────────────────

    @staticmethod
    async def _run_carry_over(tenant_id, closing_year: int, today: date) -> dict:
        new_year_start = date(closing_year + 1, 1, 1)
        as_of_closing = date(closing_year, 12, 31)
        carried_count = 0
        converted_count = 0

        async with AsyncSessionLocal() as db:
            employees = (await db.execute(
                select(User).where(
                    User.tenant_id == tenant_id,
                    User.is_active == True,  # noqa: E712
                )
            )).scalars().all()

            # Cache policies per employee_type.
            policy_cache: dict[Optional[str], Optional[LeavePolicy]] = {}

            for emp in employees:
                etype = emp.employee_type
                if etype not in policy_cache:
                    policy_cache[etype] = await LeaveService.get_policy_for_employee(
                        db, tenant_id, etype
                    )
                policy = policy_cache[etype]
                if not policy:
                    continue

                # Closing-year balances (accrual as of Dec 31).
                balance_set = await LeaveService.compute_balances(
                    db, tenant_id, emp, year=closing_year, as_of=as_of_closing
                )
                ents = LeaveYearEndService._entitlements_for(policy)

                for ent in ents:
                    item = balance_set.for_type(ent.leave_type or "shared_pool")
                    remaining = item.available_days if item else 0.0
                    if remaining <= 0:
                        continue

                    carried = 0.0
                    if ent.carry_over_enabled and ent.max_carry_over_days > 0:
                        carried = min(remaining, ent.max_carry_over_days)

                    if carried > 0 and not await LeaveYearEndService._exists(
                        db, tenant_id, emp.id, "carry_over", ent.leave_type, new_year_start
                    ):
                        expires_on = None
                        if ent.carry_over_expiry_months > 0:
                            expires_on = _add_months(new_year_start, ent.carry_over_expiry_months)
                        db.add(LeaveCreditAdjustment(
                            tenant_id=tenant_id,
                            employee_id=emp.id,
                            adjustment_type="carry_over",
                            leave_type=ent.leave_type,
                            credits=round(carried, 2),
                            effective_date=new_year_start,
                            expires_on=expires_on,
                            source_type="job_run",
                            meta={"closing_year": closing_year, "carried": round(carried, 2)},
                            notes=f"Carried over from {closing_year}",
                        ))
                        carried_count += 1

                    # Cash conversion: the forfeitable remainder (what did NOT
                    # carry over) becomes a computed conversion line, if enabled.
                    forfeit = round(remaining - carried, 2)
                    if ent.cash_convertible and forfeit > 0 and not await LeaveYearEndService._exists(
                        db, tenant_id, emp.id, "cash_conversion", ent.leave_type, new_year_start
                    ):
                        db.add(LeaveCreditAdjustment(
                            tenant_id=tenant_id,
                            employee_id=emp.id,
                            adjustment_type="cash_conversion",
                            leave_type=ent.leave_type,
                            # Negative: these days are consumed by the payout.
                            credits=-forfeit,
                            effective_date=new_year_start,
                            source_type="job_run",
                            meta={
                                "closing_year": closing_year,
                                "days": forfeit,
                                "rate": ent.cash_conversion_rate,
                            },
                            notes=f"Cash conversion of {forfeit:g} day(s) from {closing_year}",
                        ))
                        converted_count += 1

            await db.commit()

        return {"carried": carried_count, "cash_converted": converted_count, "closing_year": closing_year}

    # ── Expiry ────────────────────────────────────────────────────────

    @staticmethod
    async def _run_expiry(tenant_id, today: date) -> dict:
        expired_count = 0
        async with AsyncSessionLocal() as db:
            # Carry-over rows that have lapsed and not yet been expired.
            due = (await db.execute(
                select(LeaveCreditAdjustment).where(
                    LeaveCreditAdjustment.tenant_id == tenant_id,
                    LeaveCreditAdjustment.adjustment_type == "carry_over",
                    LeaveCreditAdjustment.expires_on != None,  # noqa: E711
                    LeaveCreditAdjustment.expires_on <= today,
                )
            )).scalars().all()

            for row in due:
                # Skip if we already wrote an expiry for this carry-over row.
                if await LeaveYearEndService._expiry_exists(db, row.id):
                    continue

                # Expire the unused portion. Usage since the carry-over took
                # effect is approximated by the current available balance for
                # the row's year: if the employee still has >= carried credits
                # available, the full carried amount expires; otherwise only
                # what's left. FIFO (carried credits consumed first) is assumed.
                emp = await db.get(User, row.employee_id)
                if not emp:
                    continue
                balance_set = await LeaveService.compute_balances(
                    db, tenant_id, emp, year=row.effective_date.year, as_of=today
                )
                item = balance_set.for_type(row.leave_type or "shared_pool")
                available = item.available_days if item else 0.0
                expired = round(min(row.credits, max(0.0, available)), 2)
                if expired <= 0:
                    continue
                db.add(LeaveCreditAdjustment(
                    tenant_id=tenant_id,
                    employee_id=row.employee_id,
                    adjustment_type="carry_over_expiry",
                    leave_type=row.leave_type,
                    credits=-expired,
                    effective_date=row.effective_date,
                    source_type="job_run",
                    source_id=row.id,
                    meta={"expired_carry_over_id": row.id, "expired": expired},
                    notes=f"Expired carry-over from {row.effective_date.year}",
                ))
                expired_count += 1

            await db.commit()

        return {"expired": expired_count}

    # ── Idempotency helpers ───────────────────────────────────────────

    @staticmethod
    async def _exists(
        db: AsyncSession, tenant_id, employee_id: int, adj_type: str,
        leave_type: Optional[str], effective_date: date,
    ) -> bool:
        stmt = select(LeaveCreditAdjustment.id).where(
            LeaveCreditAdjustment.tenant_id == tenant_id,
            LeaveCreditAdjustment.employee_id == employee_id,
            LeaveCreditAdjustment.adjustment_type == adj_type,
            LeaveCreditAdjustment.effective_date == effective_date,
        )
        if leave_type is None:
            stmt = stmt.where(LeaveCreditAdjustment.leave_type.is_(None))
        else:
            stmt = stmt.where(LeaveCreditAdjustment.leave_type == leave_type)
        return (await db.execute(stmt.limit(1))).scalar_one_or_none() is not None

    @staticmethod
    async def _expiry_exists(db: AsyncSession, carry_over_id: int) -> bool:
        stmt = select(LeaveCreditAdjustment.id).where(
            LeaveCreditAdjustment.adjustment_type == "carry_over_expiry",
            LeaveCreditAdjustment.source_id == carry_over_id,
        )
        return (await db.execute(stmt.limit(1))).scalar_one_or_none() is not None
