from datetime import datetime, date, timedelta
from typing import List, Optional
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.leave import LeavePolicy
from app.models.schedule import ScheduleChangeApprovalStep, ScheduleChangeRequest, Shift
from app.models.user import User
from app.services.leave_approval_service import LeaveApprovalService
from app.services.leave_service import LeaveService


class ScheduleChangeService:

    @staticmethod
    async def create_request(
        db: AsyncSession,
        tenant_id: UUID,
        requester_id: int,
        request_type: str,
        req_date: date,
        end_date: Optional[date],
        target_employee_id: Optional[int],
        requested_start_time=None,
        requested_end_time=None,
        requested_status: Optional[str] = None,
        requested_work_arrangement: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> ScheduleChangeRequest:
        """Create a schedule change or swap request with approval steps."""

        # Validate target employee for swap
        if request_type == "swap":
            if not target_employee_id:
                raise ValueError("target_employee_id is required for swap requests")
            target_result = await db.execute(
                select(User).where(User.id == target_employee_id, User.tenant_id == tenant_id)
            )
            if not target_result.scalar_one_or_none():
                raise ValueError("Target employee not found")

        # Snapshot requester's current shift for the date
        requester_shift = await db.execute(
            select(Shift).where(
                Shift.tenant_id == tenant_id,
                Shift.employee_id == requester_id,
                Shift.date == req_date,
            ).order_by(Shift.sequence_number).limit(1)
        )
        req_shift = requester_shift.scalar_one_or_none()

        # Build the request
        request = ScheduleChangeRequest(
            tenant_id=tenant_id,
            request_type=request_type,
            requester_id=requester_id,
            date=req_date,
            end_date=end_date,
            target_employee_id=target_employee_id,
            original_start_time=req_shift.start_time if req_shift else None,
            original_end_time=req_shift.end_time if req_shift else None,
            original_status=req_shift.status if req_shift else None,
            requested_start_time=requested_start_time,
            requested_end_time=requested_end_time,
            requested_status=requested_status,
            requested_work_arrangement=requested_work_arrangement,
            reason=reason,
            status="pending",
        )

        # Snapshot target's shift for swap
        if request_type == "swap" and target_employee_id:
            target_shift_result = await db.execute(
                select(Shift).where(
                    Shift.tenant_id == tenant_id,
                    Shift.employee_id == target_employee_id,
                    Shift.date == req_date,
                ).order_by(Shift.sequence_number).limit(1)
            )
            target_shift = target_shift_result.scalar_one_or_none()
            if target_shift:
                request.target_original_start_time = target_shift.start_time
                request.target_original_end_time = target_shift.end_time
                request.target_original_status = target_shift.status

        db.add(request)
        await db.flush()

        # Build approval chain
        steps: List[ScheduleChangeApprovalStep] = []
        step_order = 1

        # For swap: first step is peer approval from target employee
        if request_type == "swap" and target_employee_id:
            peer_step = ScheduleChangeApprovalStep(
                request_id=request.id,
                approver_id=target_employee_id,
                step_order=step_order,
                step_type="peer_approval",
                status="pending",
            )
            db.add(peer_step)
            steps.append(peer_step)
            step_order += 1

        # Resolve manager approval chain using existing leave approval rules
        requester_result = await db.execute(
            select(User).where(User.id == requester_id, User.tenant_id == tenant_id)
        )
        requester_user = requester_result.scalar_one_or_none()

        policy = await LeaveService.get_policy_for_employee(
            db, tenant_id, requester_user.employee_type if requester_user else None
        )

        if policy:
            chain = await LeaveApprovalService.resolve_approval_chain(
                db, tenant_id, requester_id, policy
            )
            for item in chain:
                # Skip if the approver is the target employee (already a peer step)
                if request_type == "swap" and item["approver_id"] == target_employee_id:
                    continue
                mgr_step = ScheduleChangeApprovalStep(
                    request_id=request.id,
                    approver_id=item["approver_id"],
                    step_order=step_order,
                    step_type="manager_approval",
                    status="pending",
                )
                db.add(mgr_step)
                steps.append(mgr_step)
                step_order += 1

        await db.flush()
        return request

    @staticmethod
    async def process_step_decision(
        db: AsyncSession,
        request: ScheduleChangeRequest,
        step: ScheduleChangeApprovalStep,
        action: str,
        notes: Optional[str],
        reviewer_id: int,
    ) -> str:
        """Process an approval/rejection for a step. Returns the new request status."""
        step.status = "approved" if action == "approve" else "rejected"
        step.decided_at = datetime.utcnow()
        step.notes = notes

        if action == "reject":
            request.status = "rejected"
            request.reviewed_by = reviewer_id
            request.reviewed_at = datetime.utcnow()
            request.reviewer_notes = notes
            await db.flush()
            return "rejected"

        # Check if all steps are now approved
        pending_result = await db.execute(
            select(func.count(ScheduleChangeApprovalStep.id)).where(
                ScheduleChangeApprovalStep.request_id == request.id,
                ScheduleChangeApprovalStep.status == "pending",
                ScheduleChangeApprovalStep.id != step.id,
            )
        )
        pending_count = pending_result.scalar() or 0

        if pending_count == 0:
            request.status = "approved"
            request.reviewed_by = reviewer_id
            request.reviewed_at = datetime.utcnow()
            request.reviewer_notes = notes
            await ScheduleChangeService._execute_change(db, request)
            await db.flush()
            return "approved"

        await db.flush()
        return "pending"

    @staticmethod
    async def _execute_change(db: AsyncSession, request: ScheduleChangeRequest):
        """Execute the approved swap or change by modifying shifts."""
        dates = [request.date]
        if request.end_date and request.end_date > request.date:
            current = request.date
            while current <= request.end_date:
                if current != request.date:
                    dates.append(current)
                current += timedelta(days=1)

        if request.request_type == "swap" and request.target_employee_id:
            await ScheduleChangeService._execute_swap(
                db, request.tenant_id, request.requester_id,
                request.target_employee_id, dates,
            )
        elif request.request_type == "change":
            await ScheduleChangeService._execute_schedule_change(
                db, request.tenant_id, request.requester_id, dates,
                request.requested_start_time, request.requested_end_time,
                request.requested_status, request.requested_work_arrangement,
            )

    @staticmethod
    async def _execute_swap(
        db: AsyncSession, tenant_id: UUID,
        requester_id: int, target_id: int,
        dates: List[date],
    ):
        """Swap shifts between two employees for the given dates."""
        for d in dates:
            req_shifts = await db.execute(
                select(Shift).where(
                    Shift.tenant_id == tenant_id,
                    Shift.employee_id == requester_id,
                    Shift.date == d,
                ).order_by(Shift.sequence_number)
            )
            tgt_shifts = await db.execute(
                select(Shift).where(
                    Shift.tenant_id == tenant_id,
                    Shift.employee_id == target_id,
                    Shift.date == d,
                ).order_by(Shift.sequence_number)
            )
            req_list = list(req_shifts.scalars().all())
            tgt_list = list(tgt_shifts.scalars().all())

            # Swap properties between corresponding shifts
            max_len = max(len(req_list), len(tgt_list))
            for i in range(max_len):
                if i < len(req_list) and i < len(tgt_list):
                    # Swap all schedule properties
                    r, t = req_list[i], tgt_list[i]
                    (r.start_time, t.start_time) = (t.start_time, r.start_time)
                    (r.end_time, t.end_time) = (t.end_time, r.end_time)
                    (r.status, t.status) = (t.status, r.status)
                    (r.work_arrangement, t.work_arrangement) = (t.work_arrangement, r.work_arrangement)
                    (r.color, t.color) = (t.color, r.color)
                    (r.notes, t.notes) = (t.notes, r.notes)
                    (r.role_name, t.role_name) = (t.role_name, r.role_name)

    @staticmethod
    async def _execute_schedule_change(
        db: AsyncSession, tenant_id: UUID,
        requester_id: int, dates: List[date],
        new_start_time=None, new_end_time=None,
        new_status: Optional[str] = None,
        new_work_arrangement: Optional[str] = None,
    ):
        """Update employee's shifts with new values for the given dates."""
        for d in dates:
            result = await db.execute(
                select(Shift).where(
                    Shift.tenant_id == tenant_id,
                    Shift.employee_id == requester_id,
                    Shift.date == d,
                ).order_by(Shift.sequence_number)
            )
            shifts = list(result.scalars().all())

            for shift in shifts:
                if new_start_time is not None:
                    shift.start_time = new_start_time
                if new_end_time is not None:
                    shift.end_time = new_end_time
                if new_status is not None:
                    shift.status = new_status
                if new_work_arrangement is not None:
                    shift.work_arrangement = new_work_arrangement

    @staticmethod
    async def get_pending_for_approver(
        db: AsyncSession, tenant_id: UUID, approver_id: int,
    ) -> List[ScheduleChangeRequest]:
        """Get requests where this user has a pending approval step
        and all previous steps are approved."""
        # Find all pending steps for this approver
        step_result = await db.execute(
            select(ScheduleChangeApprovalStep).where(
                ScheduleChangeApprovalStep.approver_id == approver_id,
                ScheduleChangeApprovalStep.status == "pending",
            )
        )
        pending_steps = list(step_result.scalars().all())

        request_ids = []
        for step in pending_steps:
            # Check all previous steps are approved
            prev_result = await db.execute(
                select(func.count(ScheduleChangeApprovalStep.id)).where(
                    ScheduleChangeApprovalStep.request_id == step.request_id,
                    ScheduleChangeApprovalStep.step_order < step.step_order,
                    ScheduleChangeApprovalStep.status != "approved",
                )
            )
            unapproved_prev = prev_result.scalar() or 0
            if unapproved_prev == 0:
                request_ids.append(step.request_id)

        if not request_ids:
            return []

        # Load the full requests
        result = await db.execute(
            select(ScheduleChangeRequest)
            .options(
                selectinload(ScheduleChangeRequest.requester),
                selectinload(ScheduleChangeRequest.target_employee),
                selectinload(ScheduleChangeRequest.approval_steps)
                .selectinload(ScheduleChangeApprovalStep.approver),
            )
            .where(
                ScheduleChangeRequest.id.in_(request_ids),
                ScheduleChangeRequest.tenant_id == tenant_id,
                ScheduleChangeRequest.status == "pending",
            )
            .order_by(ScheduleChangeRequest.created_at.desc())
        )
        return list(result.scalars().all())
