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

        await ScheduleChangeService.validate_request(
            db, tenant_id, requester_id, request_type, req_date, end_date,
            target_employee_id, requested_start_time, requested_end_time, requested_status,
        )

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
    async def _leave_category_codes(db: AsyncSession, tenant_id: UUID) -> set:
        from app.services.schedule_service import ScheduleService

        cats = await ScheduleService._get_category_map(db, tenant_id)
        return {code for code, cat in cats.items() if cat == "leave"}

    @staticmethod
    def _dates(req_date: date, end_date: Optional[date]) -> List[date]:
        out = [req_date]
        if end_date and end_date > req_date:
            d = req_date + timedelta(days=1)
            while d <= end_date:
                out.append(d)
                d += timedelta(days=1)
        return out

    @staticmethod
    async def _shifts_on(db, tenant_id, employee_id, d) -> List[Shift]:
        return list((await db.execute(
            select(Shift).where(
                Shift.tenant_id == tenant_id,
                Shift.employee_id == employee_id,
                Shift.date == d,
            ).order_by(Shift.sequence_number)
        )).scalars().all())

    @staticmethod
    async def validate_request(
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
    ) -> None:
        """Refuse, with a sentence the employee can act on, a request that
        could never be carried out as asked. Raises ValueError.

        Leave is not something a schedule change can grant or take away: it
        has its own request, balance and approver. So a change may not set a
        leave status, and neither a change nor a swap may touch a day that is
        already approved leave (approving one used to rewrite the leave day
        and leave the application standing)."""
        dates = ScheduleChangeService._dates(req_date, end_date)
        if request_type == "change":
            if requested_status and requested_status in await ScheduleChangeService._leave_category_codes(db, tenant_id):
                raise ValueError(
                    "Leave can't be requested as a schedule change. File a leave "
                    "request instead, so it is counted against your balance and "
                    "goes to the right approver."
                )
            wants_something = requested_status or (requested_start_time and requested_end_time)
            for d in dates:
                shifts = await ScheduleChangeService._shifts_on(db, tenant_id, requester_id, d)
                if any(s.leave_application_id for s in shifts):
                    raise ValueError(
                        f"{d.isoformat()} is an approved leave day. Change your leave "
                        "request instead of the schedule."
                    )
                if not shifts and not wants_something:
                    raise ValueError(
                        f"You have no shift on {d.isoformat()}. Say which shift you "
                        "want there (start and end time, or a status)."
                    )
        elif request_type == "swap" and target_employee_id:
            for d in dates:
                for emp in (requester_id, target_employee_id):
                    shifts = await ScheduleChangeService._shifts_on(db, tenant_id, emp, d)
                    if any(s.leave_application_id for s in shifts):
                        who = "You are" if emp == requester_id else "Your colleague is"
                        raise ValueError(
                            f"{who} on approved leave on {d.isoformat()}, so that day "
                            "can't be swapped."
                        )

    @staticmethod
    async def process_step_decision(
        db: AsyncSession,
        request: ScheduleChangeRequest,
        step: ScheduleChangeApprovalStep,
        action: str,
        notes: Optional[str],
        reviewer_id: int,
        *,
        force: bool = False,
        actor=None,
    ) -> str:
        """Process an approval/rejection for a step. Returns the new request status.

        The final approval applies the change through ScheduleService's
        validator and write path (leave, guardrails, hour rules, domain
        events). A conflict raises ScheduleConflictError and nothing is
        saved; ValueError when the change cannot be applied as asked."""
        if action == "reject":
            step.status = "rejected"
            step.decided_at = datetime.utcnow()
            step.notes = notes
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

        # The change is applied (or refused) before anything about the step is
        # recorded, so a refusal leaves the request exactly as it was and the
        # approver can retry, e.g. with force.
        if pending_count == 0:
            await ScheduleChangeService._execute_change(db, request, force=force, actor=actor)
        step.status = "approved"
        step.decided_at = datetime.utcnow()
        step.notes = notes

        if pending_count == 0:
            request.status = "approved"
            request.reviewed_by = reviewer_id
            request.reviewed_at = datetime.utcnow()
            request.reviewer_notes = notes
            await db.flush()
            return "approved"

        await db.flush()
        return "pending"

    @staticmethod
    async def _execute_change(db: AsyncSession, request: ScheduleChangeRequest, *, force=False, actor=None):
        """Execute the approved swap or change by modifying shifts."""
        dates = ScheduleChangeService._dates(request.date, request.end_date)
        if request.request_type == "swap" and request.target_employee_id:
            await ScheduleChangeService._execute_swap(
                db, request.tenant_id, request.requester_id,
                request.target_employee_id, dates, force=force, actor=actor,
            )
        elif request.request_type == "change":
            await ScheduleChangeService._execute_schedule_change(
                db, request.tenant_id, request.requester_id, dates,
                request.requested_start_time, request.requested_end_time,
                request.requested_status, request.requested_work_arrangement,
                force=force, actor=actor,
            )

    @staticmethod
    async def _execute_swap(
        db: AsyncSession, tenant_id: UUID,
        requester_id: int, target_id: int,
        dates: List[date],
        *,
        force: bool = False,
        actor=None,
    ):
        """Swap two employees' days: each takes the other's shifts (every
        segment, not just the first), rows and all, so publish state, work site
        and notes travel with the shift. Refused if either side holds approved
        leave (the leave belongs to the person, not the day), and validated
        against both people's schedules as they will be."""
        from app.services.schedule_service import ScheduleConflictError, ScheduleService

        plan = []
        placements = []
        ignore = set()
        for d in dates:
            req = await ScheduleChangeService._shifts_on(db, tenant_id, requester_id, d)
            tgt = await ScheduleChangeService._shifts_on(db, tenant_id, target_id, d)
            if any(s.leave_application_id for s in req + tgt):
                raise ValueError(
                    f"{d.isoformat()} is now an approved leave day for one of the two "
                    "employees, so it can't be swapped. Reject this request."
                )
            plan.append((d, req, tgt))
            ignore.update(s.id for s in req + tgt)
            placements += [
                {"employee_id": target_id, "date": d, "status": s.status,
                 "start_time": s.start_time, "end_time": s.end_time} for s in req
            ] + [
                {"employee_id": requester_id, "date": d, "status": s.status,
                 "start_time": s.start_time, "end_time": s.end_time} for s in tgt
            ]
        conflicts = await ScheduleService.validate_placements(
            db, tenant_id, placements, force=force, ignore_shift_ids=ignore,
        )
        if conflicts:
            raise ScheduleConflictError(conflicts)

        keys = [(e, d) for d in dates for e in (requester_id, target_id)]
        await ScheduleService._before(db, tenant_id, actor, keys)
        for d, req, tgt in plan:
            # Two steps so the (employee, date, sequence) unique key never
            # collides mid-swap: park the requester's rows on high sequence
            # numbers under the target, then renumber.
            for i, s in enumerate(req):
                s.employee_id = target_id
                s.sequence_number = 1000 + i
                s.holiday_remark_id = None
            await db.flush()
            for i, s in enumerate(tgt):
                s.employee_id = requester_id
                s.sequence_number = i + 1
                s.holiday_remark_id = None
            await db.flush()
            for i, s in enumerate(req):
                s.sequence_number = i + 1
            await db.flush()
        await ScheduleService._after(db, tenant_id, actor, keys)

    @staticmethod
    async def _execute_schedule_change(
        db: AsyncSession, tenant_id: UUID,
        requester_id: int, dates: List[date],
        new_start_time=None, new_end_time=None,
        new_status: Optional[str] = None,
        new_work_arrangement: Optional[str] = None,
        *,
        force: bool = False,
        actor=None,
    ):
        """Apply a change to the employee's shifts on each date. A date with no
        shift gets one built from the request (it used to be marked approved
        while nothing happened); a request that does not say enough to build
        one is refused with ValueError."""
        from app.services.schedule_service import ScheduleConflictError, ScheduleService

        category_map = await ScheduleService._get_category_map(db, tenant_id)
        if new_status and category_map.get(new_status) == "leave":
            raise ValueError(
                "Leave can't be granted through a schedule change. Reject this "
                "request and ask for a leave request instead."
            )

        plan = []  # (date, existing shifts or None, placement)
        placements = []
        ignore = set()
        for d in dates:
            shifts = await ScheduleChangeService._shifts_on(db, tenant_id, requester_id, d)
            if any(s.leave_application_id for s in shifts):
                raise ValueError(
                    f"{d.isoformat()} is now an approved leave day, so the schedule "
                    "can't be changed there. Reject this request."
                )
            if not shifts:
                status = new_status or "scheduled"
                is_work = category_map.get(status, "leave") == "work"
                if is_work and not (new_start_time and new_end_time):
                    raise ValueError(
                        f"There is no shift on {d.isoformat()} and the request does not "
                        "give a start and end time to create one. Reject it and ask for "
                        "the times."
                    )
                p = {"employee_id": requester_id, "date": d, "status": status,
                     "start_time": new_start_time if is_work else None,
                     "end_time": new_end_time if is_work else None}
                plan.append((d, None, p))
                placements.append(p)
                continue
            for s in shifts:
                status = new_status or s.status
                is_work = category_map.get(status, "leave") == "work"
                p = {"employee_id": requester_id, "date": d, "status": status,
                     "start_time": (new_start_time or s.start_time) if is_work else None,
                     "end_time": (new_end_time or s.end_time) if is_work else None}
                plan.append((d, s, p))
                placements.append(p)
                ignore.add(s.id)

        conflicts = await ScheduleService.validate_placements(
            db, tenant_id, placements, force=force, ignore_shift_ids=ignore,
            category_map=category_map,
        )
        if conflicts:
            raise ScheduleConflictError(conflicts)

        keys = [(requester_id, d) for d in dates]
        await ScheduleService._before(db, tenant_id, actor, keys)
        now = datetime.utcnow()
        for d, shift, p in plan:
            if shift is None:
                # Approved by the chain, so it is published straight away: the
                # employee asked for it and should see it.
                db.add(Shift(
                    tenant_id=tenant_id, employee_id=requester_id, date=d,
                    start_time=p["start_time"], end_time=p["end_time"],
                    sequence_number=1, status=p["status"],
                    work_arrangement=new_work_arrangement,
                    is_published=True, published_at=now,
                ))
                continue
            shift.status = p["status"]
            shift.start_time = p["start_time"]
            shift.end_time = p["end_time"]
            if new_work_arrangement is not None:
                shift.work_arrangement = new_work_arrangement
            shift.holiday_remark_id = None
        await db.flush()
        await ScheduleService._after(db, tenant_id, actor, keys)

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
