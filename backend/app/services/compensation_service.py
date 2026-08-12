"""Compensation ledger: bonuses, incentives, allowances, salary adjustments,
leave-cash. Append-only — the amount paid in any run is a SUM over rows.
"""
from datetime import date
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.compensation import CompensationItem
from app.services.payout_schedule_service import PayoutScheduleService

VALID_KINDS = {"bonus", "incentive", "allowance", "salary_adjustment", "leave_cash", "correction"}


class CompensationService:
    @staticmethod
    async def add_item(db: AsyncSession, tenant_id: UUID, data: dict, *, created_by: Optional[int] = None) -> CompensationItem:
        """Create one compensation line. Resolves payout_date from the active
        payout schedule unless an explicit payout_date is supplied."""
        earned_on: date = data["earned_on"]
        payout_date = data.get("payout_date")
        if payout_date is None:
            payout_date = await PayoutScheduleService.resolve(db, tenant_id, earned_on)
        # If no schedule is configured, fall back to paying on the earned date so
        # the item is never orphaned; the UI warns when this happens.
        if payout_date is None:
            payout_date = earned_on

        item = CompensationItem(
            tenant_id=tenant_id,
            employee_id=data["employee_id"],
            kind=data["kind"],
            amount=float(data["amount"]),
            earned_on=earned_on,
            payout_date=payout_date,
            recurrence=data.get("recurrence", "once"),
            template_id=data.get("template_id"),
            status=data.get("status", "scheduled"),
            reason=data["reason"],
            meta=data.get("meta"),
            source_type=data.get("source_type"),
            source_id=data.get("source_id"),
            created_by=created_by,
        )
        db.add(item)
        await db.flush()
        await db.refresh(item)
        return item

    @staticmethod
    async def list_items(
        db: AsyncSession, tenant_id: UUID, *,
        employee_id: Optional[int] = None, kind: Optional[str] = None,
        status: Optional[str] = None, date_from: Optional[date] = None,
        date_to: Optional[date] = None,
    ) -> List[CompensationItem]:
        stmt = select(CompensationItem).where(CompensationItem.tenant_id == tenant_id)
        if employee_id is not None:
            stmt = stmt.where(CompensationItem.employee_id == employee_id)
        if kind:
            stmt = stmt.where(CompensationItem.kind == kind)
        if status:
            stmt = stmt.where(CompensationItem.status == status)
        if date_from:
            stmt = stmt.where(CompensationItem.payout_date >= date_from)
        if date_to:
            stmt = stmt.where(CompensationItem.payout_date <= date_to)
        stmt = stmt.order_by(CompensationItem.payout_date, CompensationItem.id)
        res = await db.execute(stmt)
        return list(res.scalars().all())

    @staticmethod
    async def void_item(db: AsyncSession, tenant_id: UUID, item_id: int, reason: str) -> Optional[CompensationItem]:
        """Void a not-yet-paid item. Paid items are immutable — a correction row
        must be added instead (see add_item kind='correction')."""
        item = await db.get(CompensationItem, item_id)
        if not item or item.tenant_id != tenant_id:
            return None
        if item.status == "paid":
            return None  # caller should post a correction instead
        item.status = "void"
        meta = dict(item.meta or {})
        meta["void_reason"] = reason
        item.meta = meta
        await db.flush()
        await db.refresh(item)
        return item

    @staticmethod
    async def earnings_for_payout(
        db: AsyncSession, tenant_id: UUID, payout_date: date,
        employee_id: Optional[int] = None,
    ) -> List[CompensationItem]:
        """Scheduled (unpaid) items due on a given payout date."""
        stmt = select(CompensationItem).where(
            CompensationItem.tenant_id == tenant_id,
            CompensationItem.payout_date == payout_date,
            CompensationItem.status == "scheduled",
        )
        if employee_id is not None:
            stmt = stmt.where(CompensationItem.employee_id == employee_id)
        res = await db.execute(stmt)
        return list(res.scalars().all())

    @staticmethod
    async def expand_recurring(
        db: AsyncSession, tenant_id: UUID, horizon_start: date, horizon_end: date,
    ) -> int:
        """Materialize recurring allowance/incentive templates into concrete
        scheduled rows for each payout in [horizon_start, horizon_end].

        A template is a CompensationItem with recurrence in {monthly, per_cutoff}
        and template_id IS NULL. It spawns recurrence='once' rows (template_id set)
        so the payout sweep treats them like any other line. Idempotent: skips a
        payout_date already materialized for that template.
        """
        sched = await PayoutScheduleService.get_active(db, tenant_id)
        if not sched or not sched.cutoffs:
            return 0

        res = await db.execute(
            select(CompensationItem).where(
                CompensationItem.tenant_id == tenant_id,
                CompensationItem.template_id.is_(None),
                CompensationItem.recurrence.in_(["monthly", "per_cutoff"]),
                CompensationItem.status != "void",
            )
        )
        templates = list(res.scalars().all())
        created = 0
        for tpl in templates:
            # Candidate earned_on dates within the horizon.
            earned_dates = CompensationService._recurring_earned_dates(
                tpl, sched.cutoffs, horizon_start, horizon_end,
            )
            for ed in earned_dates:
                payout = await PayoutScheduleService.resolve(db, tenant_id, ed, sched)
                if payout is None:
                    continue
                # idempotency: has this template already produced a row for payout?
                exists = await db.execute(
                    select(CompensationItem.id).where(
                        CompensationItem.tenant_id == tenant_id,
                        CompensationItem.template_id == tpl.id,
                        CompensationItem.payout_date == payout,
                    )
                )
                if exists.first():
                    continue
                db.add(CompensationItem(
                    tenant_id=tenant_id,
                    employee_id=tpl.employee_id,
                    kind=tpl.kind,
                    amount=tpl.amount,
                    earned_on=ed,
                    payout_date=payout,
                    recurrence="once",
                    template_id=tpl.id,
                    status="scheduled",
                    reason=tpl.reason,
                    meta=tpl.meta,
                    created_by=tpl.created_by,
                ))
                created += 1
        await db.flush()
        return created

    @staticmethod
    def _recurring_earned_dates(tpl, cutoffs: list, start: date, end: date) -> list:
        """Earned-on anchor dates for a template across a horizon: the 1st of each
        month for 'monthly', or each cutoff's start day for 'per_cutoff'."""
        out = []
        y, m = start.year, start.month
        while date(y, m, 1) <= end:
            if tpl.recurrence == "monthly":
                d = date(y, m, 1)
                if start <= d <= end:
                    out.append(d)
            else:  # per_cutoff
                for c in cutoffs:
                    day = int(c.get("cutoff_start_day", 1))
                    try:
                        d = date(y, m, day)
                    except ValueError:
                        continue
                    if start <= d <= end:
                        out.append(d)
            m += 1
            if m > 12:
                m = 1
                y += 1
        return out
