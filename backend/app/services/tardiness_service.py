"""
Tardiness Service

Manages tardiness records: listing and manual resolution.
"""

from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attendance import TardinessRecord, LeaveCreditAdjustment


class TardinessService:

    @staticmethod
    async def list_tardiness_records(
        db: AsyncSession,
        tenant_id: UUID,
        employee_id: Optional[int] = None,
        resolution_type: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
        employee_ids=None,
    ) -> Tuple[List[TardinessRecord], int]:
        base = select(TardinessRecord).where(TardinessRecord.tenant_id == tenant_id)

        if employee_id:
            base = base.where(TardinessRecord.employee_id == employee_id)
        if employee_ids is not None:
            base = base.where(TardinessRecord.employee_id.in_(list(employee_ids)))
        if resolution_type:
            base = base.where(TardinessRecord.resolution_type == resolution_type)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await db.execute(count_stmt)).scalar() or 0

        stmt = base.order_by(TardinessRecord.date.desc(), TardinessRecord.id.desc())
        stmt = stmt.offset(skip).limit(limit)
        result = await db.execute(stmt)
        records = list(result.scalars().all())

        return records, total

    @staticmethod
    async def get_tardiness_record(
        db: AsyncSession, tenant_id: UUID, record_id: int
    ) -> Optional[TardinessRecord]:
        stmt = select(TardinessRecord).where(
            TardinessRecord.tenant_id == tenant_id, TardinessRecord.id == record_id
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def default_deduction(
        db: AsyncSession, tenant_id: UUID, employee_id: int, minutes: int, on_date,
    ) -> Optional[float]:
        """Minutes late x the employee's per-minute rate, derived exactly as
        payroll derives its hourly rate (monthly / working days / shift hours,
        unless the grade sets daily or hourly rates). None when the employee
        has no salary on that date, so the caller can say so."""
        from app.services.payroll_service import PayrollService

        rates = await PayrollService.employee_rates(db, tenant_id, employee_id, on_date)
        if rates is None:
            return None
        return round(rates["hourly"] / 60.0 * (minutes or 0), 2)

    @staticmethod
    async def resolve_tardiness(
        db: AsyncSession,
        tenant_id: UUID,
        record_id: int,
        resolution_type: str,
        resolved_by: int,
        deduction_amount: Optional[float] = None,
        leave_type: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Optional[TardinessRecord]:
        """Manually resolve a tardiness record."""
        record = await TardinessService.get_tardiness_record(db, tenant_id, record_id)
        if not record:
            return None

        from sqlalchemy import delete

        # Re-resolving replaces the previous outcome. Before, switching from a
        # leave deduction to anything else (or re-saving one) left the old
        # leave debit behind, so the employee lost credits twice.
        await db.execute(
            delete(LeaveCreditAdjustment).where(
                LeaveCreditAdjustment.tenant_id == tenant_id,
                LeaveCreditAdjustment.source_type == "tardiness_record",
                LeaveCreditAdjustment.source_id == record.id,
            )
        )
        record.deduction_amount = None
        record.leave_credits_deducted = None

        record.resolution_type = resolution_type
        record.recorded_by = resolved_by
        if notes:
            record.notes = notes

        if resolution_type == "salary_deduction":
            # An amount typed in the resolve dialog wins; otherwise the
            # employee's rate x minutes late. Payroll deducts whatever is here.
            if deduction_amount is None:
                deduction_amount = await TardinessService.default_deduction(
                    db, tenant_id, record.employee_id, record.tardiness_minutes, record.date
                )
            record.deduction_amount = round(deduction_amount, 2) if deduction_amount is not None else None

        elif resolution_type == "leave_deduction":
            # Convert tardiness to leave credit deduction
            hours = record.tardiness_minutes / 60.0
            credits_to_deduct = hours / 8.0  # 8 hours = 1 day
            record.leave_credits_deducted = credits_to_deduct

            adj = LeaveCreditAdjustment(
                tenant_id=tenant_id,
                employee_id=record.employee_id,
                adjustment_type="tardiness_deduction",
                leave_type=leave_type,
                credits=-credits_to_deduct,
                source_id=record.id,
                source_type="tardiness_record",
                notes=notes or f"Manual tardiness deduction for {record.tardiness_minutes}min on {record.date}",
                created_by=resolved_by,
            )
            db.add(adj)

        await db.flush()
        return record
