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
from app.models.leave import LeaveType, OvertimeCategory


class OvertimeService:

    @staticmethod
    async def list_overtime_logs(
        db: AsyncSession,
        tenant_id: UUID,
        employee_id: Optional[int] = None,
        status: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
        employee_ids=None,
    ) -> Tuple[List[OvertimeLog], int]:
        base = select(OvertimeLog).where(OvertimeLog.tenant_id == tenant_id)

        if employee_id:
            base = base.where(OvertimeLog.employee_id == employee_id)
        if employee_ids is not None:
            base = base.where(OvertimeLog.employee_id.in_(list(employee_ids)))
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
    async def conversion_leave_types(db: AsyncSession, tenant_id: UUID) -> List[LeaveType]:
        """Leave types overtime can be converted into: the ones an active
        overtime category converts into, or every active type when no
        category names one."""
        targets = (await db.execute(
            select(LeaveType)
            .join(OvertimeCategory, OvertimeCategory.leave_credit_type_id == LeaveType.id)
            .where(
                LeaveType.tenant_id == tenant_id,
                LeaveType.is_active == True,  # noqa: E712
                OvertimeCategory.is_active == True,  # noqa: E712
            )
            .distinct()
            .order_by(LeaveType.sort_order, LeaveType.name)
        )).scalars().all()
        if targets:
            return list(targets)
        return list((await db.execute(
            select(LeaveType).where(
                LeaveType.tenant_id == tenant_id,
                LeaveType.is_active == True,  # noqa: E712
            ).order_by(LeaveType.sort_order, LeaveType.name)
        )).scalars().all())

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
        if log.paid_at is not None:
            raise ValueError(
                "This overtime has already been paid in a finalized payroll run, "
                "so it cannot also be converted to leave."
            )

        # Get category's leave credit rate
        leave_credit_rate = 8.0  # default: 8 hours of OT = 1 day credit
        category = None
        if log.overtime_category_id:
            stmt = select(OvertimeCategory).where(OvertimeCategory.id == log.overtime_category_id)
            result = await db.execute(stmt)
            category = result.scalar_one_or_none()
            if category and category.leave_credit_rate:
                leave_credit_rate = category.leave_credit_rate

        # The credit must say which leave it is: balances count ot_conversion
        # credits per leave type, and an untyped one was added to every type.
        if not leave_type and category is not None and category.leave_credit_type_id:
            lt = await db.get(LeaveType, category.leave_credit_type_id)
            leave_type = lt.code if lt else None
        if not leave_type:
            raise ValueError("Choose which leave type the overtime becomes.")
        chosen = (await db.execute(
            select(LeaveType).where(
                LeaveType.tenant_id == tenant_id,
                LeaveType.code == leave_type,
                LeaveType.is_active == True,  # noqa: E712
            )
        )).scalar_one_or_none()
        if chosen is None:
            raise ValueError(f"There is no active leave type with the code '{leave_type}'.")

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
