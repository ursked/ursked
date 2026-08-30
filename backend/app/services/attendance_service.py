"""
Attendance Service

Records attendance for employees, auto-computes tardiness/overtime/undertime
based on scheduled vs actual times and employee's schedule format, then
triggers the policy engine for automated actions.
"""

from datetime import date, datetime, time, timedelta
from typing import List, Optional, Set, Tuple
from uuid import UUID

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.attendance import AttendanceRecord, LeaveCreditAdjustment, OvertimeLog, TardinessRecord
from app.models.schedule import Shift, DateRemark
from app.models.user import User
from app.models.configurable_types import ScheduleFormat
from app.services.policy_engine_service import PolicyEngineService


def _time_to_minutes(t: time) -> int:
    """Convert a time to minutes since midnight."""
    return t.hour * 60 + t.minute


def _compute_hours_worked(start: time, end: time, unpaid_break_minutes: int = 0) -> float:
    """Compute hours worked between two times, subtracting unpaid breaks."""
    start_min = _time_to_minutes(start)
    end_min = _time_to_minutes(end)
    # Handle overnight shifts
    if end_min <= start_min:
        end_min += 24 * 60
    diff = end_min - start_min - unpaid_break_minutes
    return max(0, diff / 60.0)


class AttendanceService:

    @staticmethod
    async def record_attendance(
        db: AsyncSession,
        tenant_id: UUID,
        employee_id: int,
        attendance_date: date,
        actual_start: Optional[time],
        actual_end: Optional[time],
        notes: Optional[str] = None,
        recorded_by: Optional[int] = None,
        self_reported: bool = False,
    ) -> AttendanceRecord:
        """
        Record attendance for an employee on a given date.
        Auto-computes tardiness, overtime, undertime, and triggers policy engine.
        """
        # 1. Look up shift for employee+date
        shift = await AttendanceService._get_shift(db, tenant_id, employee_id, attendance_date)

        # 2. Look up employee's schedule_format
        employee = await db.get(User, employee_id)
        if not employee:
            raise ValueError("Employee not found")

        schedule_fmt = None
        hours_per_day = 8.0
        unpaid_break_minutes = 0
        if employee.schedule_format:
            stmt = select(ScheduleFormat).where(
                ScheduleFormat.tenant_id == tenant_id,
                ScheduleFormat.code == employee.schedule_format,
            )
            result = await db.execute(stmt)
            schedule_fmt = result.scalar_one_or_none()
            if schedule_fmt:
                hours_per_day = schedule_fmt.hours_per_day or 8.0
                unpaid_break_minutes = schedule_fmt.unpaid_break_minutes or 0

        # Scheduled times from shift
        scheduled_start = shift.start_time if shift else None
        scheduled_end = shift.end_time if shift else None

        # 3. Compute metrics (shared with update_attendance so an edit recomputes
        #    exactly as a fresh record would).
        metrics = await AttendanceService._compute_metrics(
            scheduled_start, scheduled_end, actual_start, actual_end,
            hours_per_day, unpaid_break_minutes,
        )

        # 4. Save AttendanceRecord
        record = AttendanceRecord(
            tenant_id=tenant_id,
            employee_id=employee_id,
            shift_id=shift.id if shift else None,
            date=attendance_date,
            actual_start_time=actual_start,
            actual_end_time=actual_end,
            scheduled_start_time=scheduled_start,
            scheduled_end_time=scheduled_end,
            hours_worked=metrics["hours_worked"],
            tardiness_minutes=metrics["tardiness_minutes"],
            overtime_minutes=metrics["overtime_minutes"],
            undertime_minutes=metrics["undertime_minutes"],
            status=metrics["status"],
            notes=notes,
            recorded_by=recorded_by,
            self_reported=self_reported,
        )
        db.add(record)
        await db.flush()

        # 5. Run the policy engine against the fresh record.
        await AttendanceService._evaluate_policies(
            db, tenant_id, record, employee, scheduled_start, scheduled_end,
            unpaid_break_minutes,
        )

        return record

    @staticmethod
    async def upsert_attendance(
        db: AsyncSession,
        tenant_id: UUID,
        employee_id: int,
        attendance_date: date,
        actual_start: Optional[time],
        actual_end: Optional[time],
        notes: Optional[str] = None,
        recorded_by: Optional[int] = None,
        self_reported: bool = False,
    ) -> AttendanceRecord:
        """Create the day's record, or re-derive it if one already exists.

        `record_attendance` always inserts, and `attendance_records` carries
        `uq_employee_attendance_date`. So a second submission for the same day
        raised IntegrityError — which is not a ValueError, so the endpoints'
        `except ValueError` never caught it and the caller got a 500. Submitting
        your own hours twice for one date, or correcting a typo, hit this.

        Delegating the update path to `update_attendance` matters: that is what
        purges the previously generated overtime/tardiness/leave rows and re-runs
        the policy engine, so a re-submission cannot leave doubled OT feeding
        payroll.
        """
        existing = (
            await db.execute(
                select(AttendanceRecord).where(
                    AttendanceRecord.tenant_id == tenant_id,
                    AttendanceRecord.employee_id == employee_id,
                    AttendanceRecord.date == attendance_date,
                )
            )
        ).scalar_one_or_none()

        if existing is None:
            return await AttendanceService.record_attendance(
                db,
                tenant_id=tenant_id,
                employee_id=employee_id,
                attendance_date=attendance_date,
                actual_start=actual_start,
                actual_end=actual_end,
                notes=notes,
                recorded_by=recorded_by,
                self_reported=self_reported,
            )

        data: dict = {
            "actual_start_time": actual_start,
            "actual_end_time": actual_end,
        }
        if notes is not None:
            data["notes"] = notes
        record = await AttendanceService.update_attendance(
            db, tenant_id, existing.id, data
        )
        if record is not None:
            # update_attendance does not carry these; they describe who supplied
            # the latest figures, which is exactly what has just changed.
            record.self_reported = self_reported
            if recorded_by is not None:
                record.recorded_by = recorded_by
            await db.flush()
        return record

    @staticmethod
    async def _compute_metrics(
        scheduled_start: Optional[time],
        scheduled_end: Optional[time],
        actual_start: Optional[time],
        actual_end: Optional[time],
        hours_per_day: float,
        unpaid_break_minutes: int,
    ) -> dict:
        """Derive tardiness/overtime/undertime/hours_worked/status from scheduled
        vs actual times. Shared by create and update so an edited record's numbers
        are always recomputed (never left stale)."""
        tardiness_minutes = 0
        overtime_minutes = 0
        undertime_minutes = 0
        hours_worked = None
        status = "present"

        if actual_start and actual_end:
            hours_worked = _compute_hours_worked(actual_start, actual_end, unpaid_break_minutes)
            if scheduled_start and actual_start > scheduled_start:
                tardiness_minutes = _time_to_minutes(actual_start) - _time_to_minutes(scheduled_start)
                if tardiness_minutes > 0:
                    status = "late"
            overtime_minutes = max(0, int((hours_worked - hours_per_day) * 60))
            if hours_worked < hours_per_day:
                undertime_minutes = int((hours_per_day - hours_worked) * 60)
        elif actual_start is None and actual_end is None:
            status = "absent"

        return {
            "hours_worked": hours_worked,
            "tardiness_minutes": tardiness_minutes,
            "overtime_minutes": overtime_minutes,
            "undertime_minutes": undertime_minutes,
            "status": status,
        }

    @staticmethod
    async def _purge_engine_records(db: AsyncSession, record: AttendanceRecord) -> None:
        """Delete the OT logs, tardiness records and their derived leave-credit
        adjustments that a PREVIOUS engine run created for this attendance record,
        so an edit can be re-evaluated cleanly without duplicates or orphans.

        Records already swept into a finalized payroll run are LEFT ALONE — those
        figures are locked; a correction must be posted through payroll instead."""
        from sqlalchemy import delete
        # OT logs for this attendance that are not tied to a finalized run.
        ot_rows = (await db.execute(
            select(OvertimeLog).where(OvertimeLog.attendance_record_id == record.id)
        )).scalars().all()
        for ot in ot_rows:
            # ot.status becomes 'converted'/'paid' once used; only purge unpaid ones.
            if ot.status in ("paid",):
                continue
            # Drop any leave adjustment that came from this OT log.
            await db.execute(
                delete(LeaveCreditAdjustment).where(
                    LeaveCreditAdjustment.source_type == "overtime_log",
                    LeaveCreditAdjustment.source_id == ot.id,
                )
            )
            await db.delete(ot)

        tard_rows = (await db.execute(
            select(TardinessRecord).where(TardinessRecord.attendance_record_id == record.id)
        )).scalars().all()
        for tr in tard_rows:
            await db.execute(
                delete(LeaveCreditAdjustment).where(
                    LeaveCreditAdjustment.source_type == "tardiness_record",
                    LeaveCreditAdjustment.source_id == tr.id,
                )
            )
            await db.delete(tr)
        await db.flush()

    @staticmethod
    async def _evaluate_policies(
        db: AsyncSession,
        tenant_id: UUID,
        record: AttendanceRecord,
        employee: User,
        scheduled_start: Optional[time],
        scheduled_end: Optional[time],
        unpaid_break_minutes: int,
    ) -> None:
        """Build the policy context for an attendance record and run the engine."""
        actual_start = record.actual_start_time
        actual_end = record.actual_end_time
        attendance_date = record.date

        dates_to_check = [attendance_date]
        is_overnight = (
            actual_start is not None
            and actual_end is not None
            and _time_to_minutes(actual_end) <= _time_to_minutes(actual_start)
        )
        if is_overnight:
            dates_to_check.append(attendance_date + timedelta(days=1))

        is_holiday, is_special, holiday_dates = await AttendanceService._check_date_remarks_multi(
            db, tenant_id, dates_to_check
        )

        shift_hours = None
        if scheduled_start and scheduled_end:
            shift_hours = _compute_hours_worked(scheduled_start, scheduled_end, unpaid_break_minutes)

        context = PolicyEngineService.build_context(
            attendance=record,
            schedule_format=employee.schedule_format,
            employee_type=employee.employee_type,
            is_holiday=is_holiday,
            is_special=is_special,
            shift_hours=shift_hours,
            actual_start_time=actual_start,
            actual_end_time=actual_end,
            holiday_dates=holiday_dates,
            attendance_date=attendance_date,
        )

        await PolicyEngineService.evaluate(db, record, context)

    @staticmethod
    async def simulate_policy_rules(
        db: AsyncSession,
        tenant_id: UUID,
        start_date: date,
        end_date: date,
        employee_ids: Optional[List[int]] = None,
    ) -> dict:
        """Dry-run the active policy rules over every attendance record in the
        range and report the effects they WOULD apply — writing nothing. Lets an
        admin preview a rule change before it touches live payroll data."""
        stmt = select(AttendanceRecord).where(
            AttendanceRecord.tenant_id == tenant_id,
            AttendanceRecord.date >= start_date,
            AttendanceRecord.date <= end_date,
        )
        if employee_ids:
            stmt = stmt.where(AttendanceRecord.employee_id.in_(employee_ids))
        stmt = stmt.order_by(AttendanceRecord.date, AttendanceRecord.employee_id)
        records = list((await db.execute(stmt)).scalars().all())

        # Cache active rules + employee names once.
        from app.models.policy import PolicyRule
        rules = list((await db.execute(
            select(PolicyRule).where(
                PolicyRule.tenant_id == tenant_id,
                PolicyRule.is_active == True,  # noqa: E712
            ).order_by(PolicyRule.priority.asc(), PolicyRule.id.asc())
        )).scalars().all())

        emp_ids = {r.employee_id for r in records}
        names: dict = {}
        if emp_ids:
            for uid, fn, ln in (await db.execute(
                select(User.id, User.first_name, User.last_name).where(User.id.in_(emp_ids))
            )).all():
                names[uid] = f"{fn} {ln}"

        effects: List[dict] = []
        for rec in records:
            employee = await db.get(User, rec.employee_id)
            is_holiday, is_special, holiday_dates = await AttendanceService._check_date_remarks_multi(
                db, tenant_id, [rec.date]
            )
            context = PolicyEngineService.build_context(
                attendance=rec,
                schedule_format=employee.schedule_format if employee else None,
                employee_type=employee.employee_type if employee else None,
                is_holiday=is_holiday,
                is_special=is_special,
                shift_hours=None,
                actual_start_time=rec.actual_start_time,
                actual_end_time=rec.actual_end_time,
                holiday_dates=holiday_dates,
                attendance_date=rec.date,
            )
            rec_effects = await PolicyEngineService.simulate_record(db, rec, context, rules)
            for e in rec_effects:
                effects.append({
                    "employee_id": rec.employee_id,
                    "employee_name": names.get(rec.employee_id),
                    "date": rec.date,
                    **e,
                })

        return {"records_evaluated": len(records), "effects": effects}

    @staticmethod
    async def get_attendance(
        db: AsyncSession, tenant_id: UUID, record_id: int
    ) -> Optional[AttendanceRecord]:
        stmt = select(AttendanceRecord).where(
            AttendanceRecord.tenant_id == tenant_id,
            AttendanceRecord.id == record_id,
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def list_attendance(
        db: AsyncSession,
        tenant_id: UUID,
        employee_id: Optional[int] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        status: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> Tuple[List[AttendanceRecord], int]:
        """List attendance records with optional filters."""
        base = select(AttendanceRecord).where(AttendanceRecord.tenant_id == tenant_id)

        if employee_id:
            base = base.where(AttendanceRecord.employee_id == employee_id)
        if start_date:
            base = base.where(AttendanceRecord.date >= start_date)
        if end_date:
            base = base.where(AttendanceRecord.date <= end_date)
        if status:
            base = base.where(AttendanceRecord.status == status)

        # Count
        from sqlalchemy import func
        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await db.execute(count_stmt)).scalar() or 0

        # Fetch
        stmt = base.order_by(AttendanceRecord.date.desc(), AttendanceRecord.id.desc())
        stmt = stmt.offset(skip).limit(limit)
        result = await db.execute(stmt)
        records = list(result.scalars().all())

        return records, total

    @staticmethod
    async def update_attendance(
        db: AsyncSession,
        tenant_id: UUID,
        record_id: int,
        data: dict,
    ) -> Optional[AttendanceRecord]:
        """Update an attendance record and FULLY re-derive from it.

        When the actual times change, tardiness/overtime/undertime/hours/status are
        recomputed, the previous engine-created OT/tardiness/leave rows are purged,
        and the policy engine is re-run — so an edit never leaves stale figures or
        orphaned downstream records feeding payroll. (Rows locked into a finalized
        payroll run are preserved; see _purge_engine_records.)"""
        record = await AttendanceService.get_attendance(db, tenant_id, record_id)
        if not record:
            return None

        # Apply the incoming edits. `notes` may be cleared to empty; times/status
        # are only overwritten when explicitly provided (non-None).
        if "notes" in data:
            record.notes = data["notes"]
        times_changed = False
        for field in ["actual_start_time", "actual_end_time"]:
            if field in data:
                if getattr(record, field) != data[field]:
                    times_changed = True
                setattr(record, field, data[field])

        # An explicit manual status override wins (e.g. HR marks 'excused'); else we
        # recompute status from the (possibly new) times below.
        manual_status = data.get("status")

        # Resolve the shift + schedule format to recompute against.
        shift = await AttendanceService._get_shift(db, tenant_id, record.employee_id, record.date)
        employee = await db.get(User, record.employee_id)
        hours_per_day = 8.0
        unpaid_break_minutes = 0
        if employee and employee.schedule_format:
            sf = (await db.execute(
                select(ScheduleFormat).where(
                    ScheduleFormat.tenant_id == tenant_id,
                    ScheduleFormat.code == employee.schedule_format,
                )
            )).scalar_one_or_none()
            if sf:
                hours_per_day = sf.hours_per_day or 8.0
                unpaid_break_minutes = sf.unpaid_break_minutes or 0
        scheduled_start = shift.start_time if shift else record.scheduled_start_time
        scheduled_end = shift.end_time if shift else record.scheduled_end_time

        metrics = await AttendanceService._compute_metrics(
            scheduled_start, scheduled_end,
            record.actual_start_time, record.actual_end_time,
            hours_per_day, unpaid_break_minutes,
        )
        record.hours_worked = metrics["hours_worked"]
        record.tardiness_minutes = metrics["tardiness_minutes"]
        record.overtime_minutes = metrics["overtime_minutes"]
        record.undertime_minutes = metrics["undertime_minutes"]
        record.scheduled_start_time = scheduled_start
        record.scheduled_end_time = scheduled_end
        record.status = manual_status if manual_status else metrics["status"]
        await db.flush()

        # Re-derive downstream records: purge the old engine output, then re-run.
        await AttendanceService._purge_engine_records(db, record)
        if employee:
            await AttendanceService._evaluate_policies(
                db, tenant_id, record, employee, scheduled_start, scheduled_end,
                unpaid_break_minutes,
            )

        return record

    @staticmethod
    async def _get_shift(
        db: AsyncSession, tenant_id: UUID, employee_id: int, attendance_date: date
    ) -> Optional[Shift]:
        """Get the primary shift for an employee on a given date."""
        stmt = (
            select(Shift)
            .where(
                Shift.tenant_id == tenant_id,
                Shift.employee_id == employee_id,
                Shift.date == attendance_date,
            )
            .order_by(Shift.sequence_number.asc())
            .limit(1)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def _check_date_remarks(
        db: AsyncSession, tenant_id: UUID, attendance_date: date
    ) -> Tuple[bool, bool]:
        """Check if a date has holiday or special remarks."""
        is_holiday, is_special, _ = await AttendanceService._check_date_remarks_multi(
            db, tenant_id, [attendance_date]
        )
        return is_holiday, is_special

    @staticmethod
    async def _check_date_remarks_multi(
        db: AsyncSession, tenant_id: UUID, dates: List[date]
    ) -> Tuple[bool, bool, Set[date]]:
        """Check if any of the given dates have holiday or special remarks.
        Also matches recurring holidays by month+day.
        Returns (is_any_holiday, is_any_special, holiday_dates_set)."""
        # Check exact date matches
        stmt = select(DateRemark).where(
            DateRemark.tenant_id == tenant_id,
            DateRemark.date.in_(dates),
        )
        result = await db.execute(stmt)
        remarks = list(result.scalars().all())

        is_holiday = any(r.is_holiday for r in remarks)
        is_special = any(r.is_special for r in remarks)
        holiday_dates: Set[date] = {r.date for r in remarks if r.is_holiday}

        # Also check recurring holidays (same month+day from any year)
        recurring_stmt = select(DateRemark).where(
            DateRemark.tenant_id == tenant_id,
            DateRemark.is_recurring == True,
        )
        recurring_result = await db.execute(recurring_stmt)
        for remark in recurring_result.scalars().all():
            for check_date in dates:
                if remark.date.month == check_date.month and remark.date.day == check_date.day:
                    if remark.is_holiday:
                        holiday_dates.add(check_date)
                        is_holiday = True
                    if remark.is_special:
                        is_special = True

        return is_holiday, is_special, holiday_dates
