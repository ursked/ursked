"""
Overtime Service

Manages overtime logs: listing, approving, rejecting, and converting to leave credits.
"""

from datetime import datetime
from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attendance import OvertimeLog, LeaveCreditAdjustment
from app.models.leave import OvertimeCategory


class OvertimeService:

    @staticmethod
    async def list_overtime_logs(
        db: AsyncSession,
        tenant_id: UUID,
        employee_id: Optional[int] = None,
        status: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> Tuple[List[OvertimeLog], int]:
        base = select(OvertimeLog).where(OvertimeLog.tenant_id == tenant_id)

        if employee_id:
            base = base.where(OvertimeLog.employee_id == employee_id)
        if status:
            base = base.where(OvertimeLog.status == status)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await db.execute(count_stmt)).scalar() or 0

        stmt = base.order_by(OvertimeLog.date.desc(), OvertimeLog.id.desc())
        stmt = stmt.offset(skip).limit(limit)
        result = await db.execute(stmt)
        logs = list(result.scalars().all())

        return logs, total

    @staticmethod
    async def get_overtime_log(
        db: AsyncSession, tenant_id: UUID, log_id: int
    ) -> Optional[OvertimeLog]:
        stmt = select(OvertimeLog).where(
            OvertimeLog.tenant_id == tenant_id, OvertimeLog.id == log_id
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def approve_overtime(
        db: AsyncSession,
        tenant_id: UUID,
        log_id: int,
        approved_by: int,
        notes: Optional[str] = None,
    ) -> Optional[OvertimeLog]:
        log = await OvertimeService.get_overtime_log(db, tenant_id, log_id)
        if not log or log.status != "pending":
            return None

        log.status = "approved"
        log.approved_by = approved_by
        log.approved_at = datetime.utcnow()
        if notes:
            log.notes = notes

        await db.flush()
        return log

    @staticmethod
    async def reject_overtime(
        db: AsyncSession,
        tenant_id: UUID,
        log_id: int,
        approved_by: int,
        notes: Optional[str] = None,
    ) -> Optional[OvertimeLog]:
        log = await OvertimeService.get_overtime_log(db, tenant_id, log_id)
        if not log or log.status != "pending":
            return None

        log.status = "rejected"
        log.approved_by = approved_by
        log.approved_at = datetime.utcnow()
        if notes:
            log.notes = notes

        await db.flush()
        return log

    @staticmethod
    async def convert_to_leave(
        db: AsyncSession,
        tenant_id: UUID,
        log_id: int,
        converted_by: int,
        leave_type: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Optional[OvertimeLog]:
        """
        Convert approved OT to leave credits.
        Uses the OvertimeCategory.leave_credit_rate to determine credits.
        Formula: leave_credits = overtime_minutes / 60 / leave_credit_rate
        Example: 180 min OT / 60 = 3 hours / 8 rate = 0.375 day credit
        """
        log = await OvertimeService.get_overtime_log(db, tenant_id, log_id)
        if not log or log.status != "approved":
            return None

        # Get category's leave credit rate
        leave_credit_rate = 8.0  # default: 8 hours of OT = 1 day credit
        if log.overtime_category_id:
            stmt = select(OvertimeCategory).where(OvertimeCategory.id == log.overtime_category_id)
            result = await db.execute(stmt)
            category = result.scalar_one_or_none()
            if category and category.leave_credit_rate:
                leave_credit_rate = category.leave_credit_rate

        hours_ot = log.overtime_minutes / 60.0
        leave_credits = hours_ot / leave_credit_rate

        # Update log
        log.status = "converted"
        log.leave_credits_earned = leave_credits

        # Create leave credit adjustment
        adj = LeaveCreditAdjustment(
            tenant_id=tenant_id,
            employee_id=log.employee_id,
            adjustment_type="ot_conversion",
            leave_type=leave_type,
            credits=leave_credits,
            source_id=log.id,
            source_type="overtime_log",
            notes=notes or f"Converted {log.overtime_minutes}min OT to {leave_credits:.4f} day credits",
            created_by=converted_by,
        )
        db.add(adj)
        await db.flush()

        return log
