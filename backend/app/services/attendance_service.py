"""
Attendance Service

Records attendance for employees, derives tardiness/overtime/undertime from
what was worked against the day's PUBLISHED plan, then triggers the policy
engine for automated actions.

How a day is judged (2026-09):

  * The plan is the day's published shifts. A draft is a proposal, not a
    roster: it must not make anyone late, owe anyone overtime or count as a
    no-show.
  * Work segments are the published shifts whose status is in the 'work'
    category. A split day has several and every one of them counts; the old
    code compared against the first segment only, and against the schedule
    format's hours_per_day rather than the shift, so a 4-hour half day showed
    240 minutes of undertime.
  * Times are real datetimes. A 22:00 shift clocked in at 00:30 is 150 minutes
    late, not "early"; an end time before the start is the next morning.
  * What was worked comes from the clock's paired punches when the day has
    them (so the unpaid gap in a split day is not billed), else from the times
    someone entered. The policy engine runs only after those hours are known.
  * A day worked with no published work shift (a rostered rest day, or nothing
    rostered) is flagged as rest-day work.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Set, Tuple
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attendance import (
    AttendanceRecord, LeaveCreditAdjustment, OvertimeLog, TardinessRecord, TimePunch,
)
from app.models.configurable_types import ScheduleFormat
from app.models.leave import LeaveApplication
from app.models.schedule import Shift
from app.models.settings import AppSettings, ShiftStatusType
from app.models.user import User
from app.services.payroll_compute import Interval, interval_minutes, paid_minutes, span
from app.services.policy_engine_service import PolicyEngineService

# Status codes that are work when a tenant has not categorised them (no
# shift_status_types row). Anything else unknown is treated as not work, the
# same default the grid uses.
_DEFAULT_WORK_STATUSES = {"scheduled", "worked", "overtime", "ot"}


def _time_to_minutes(t: time) -> int:
    """Convert a time to minutes since midnight."""
    return t.hour * 60 + t.minute


def tenant_zone(settings: Optional[AppSettings]) -> ZoneInfo:
    try:
        return ZoneInfo((settings.timezone if settings else None) or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def to_local(instant: datetime, tz: ZoneInfo) -> datetime:
    """A stored instant as a naive wall-clock datetime in the tenant's zone."""
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    return instant.astimezone(tz).replace(tzinfo=None)


def _nearest(d: date, t: time, anchor: Optional[datetime]) -> datetime:
    """`t` on whichever of d-1, d, d+1 lies closest to `anchor`, so an entered
    00:30 against a 22:00 start means the next morning, and 23:55 against a
    00:30 start means the evening before."""
    if anchor is None:
        return datetime.combine(d, t)
    candidates = [datetime.combine(d + timedelta(days=k), t) for k in (-1, 0, 1)]
    return min(candidates, key=lambda c: abs((c - anchor).total_seconds()))


@dataclass
class DayPlan:
    shifts: List[Shift] = field(default_factory=list)
    # (start, end, shift) for each published work shift with times.
    segments: List[Tuple[datetime, datetime, Shift]] = field(default_factory=list)
    scheduled_minutes: int = 0

    @property
    def is_work_day(self) -> bool:
        return bool(self.segments)

    @property
    def first_shift(self) -> Optional[Shift]:
        if self.segments:
            return self.segments[0][2]
        return self.shifts[0] if self.shifts else None


@dataclass
class DayFacts:
    plan: DayPlan
    intervals: List[Interval]
    in_instants: List[datetime]
    fmt: Optional[ScheduleFormat]
    hours_per_day: float
    unpaid_break_minutes: int
    worked_minutes: int
    paid_worked_minutes: int
    metrics: dict


class AttendanceService:

    # ── reference data ───────────────────────────────────────────────────

    @staticmethod
    async def _settings(db: AsyncSession, tenant_id: UUID) -> Optional[AppSettings]:
        return (
            await db.execute(select(AppSettings).where(AppSettings.tenant_id == tenant_id))
        ).scalar_one_or_none()

    @staticmethod
    async def _category_map(db: AsyncSession, tenant_id: UUID) -> Dict[str, str]:
        rows = (
            await db.execute(select(ShiftStatusType).where(ShiftStatusType.tenant_id == tenant_id))
        ).scalars().all()
        return {r.code: r.category for r in rows}

    @staticmethod
    def is_work_status(status: Optional[str], category_map: Dict[str, str]) -> bool:
        s = status or "scheduled"
        if s in category_map:
            return category_map[s] == "work"
        return s in _DEFAULT_WORK_STATUSES

    @staticmethod
    async def _schedule_format(
        db: AsyncSession, tenant_id: UUID, employee: Optional[User]
    ) -> Optional[ScheduleFormat]:
        if not employee or not employee.schedule_format:
            return None
        return (
            await db.execute(
                select(ScheduleFormat).where(
                    ScheduleFormat.tenant_id == tenant_id,
                    ScheduleFormat.code == employee.schedule_format,
                )
            )
        ).scalar_one_or_none()

    @staticmethod
    async def published_shifts(
        db: AsyncSession, tenant_id: UUID, employee_id: int, d: date
    ) -> List[Shift]:
        return list(
            (
                await db.execute(
                    select(Shift)
                    .where(
                        Shift.tenant_id == tenant_id,
                        Shift.employee_id == employee_id,
                        Shift.date == d,
                        Shift.is_published == True,  # noqa: E712
                    )
                    .order_by(Shift.sequence_number.asc())
                )
            ).scalars().all()
        )

    @staticmethod
    async def day_plan(
        db: AsyncSession, tenant_id: UUID, employee_id: int, d: date,
        fmt: Optional[ScheduleFormat] = None,
        category_map: Optional[Dict[str, str]] = None,
    ) -> DayPlan:
        """The day's published roster: its work segments and their paid length."""
        if category_map is None:
            category_map = await AttendanceService._category_map(db, tenant_id)
        shifts = await AttendanceService.published_shifts(db, tenant_id, employee_id, d)
        segments = []
        for s in shifts:
            if s.start_time and s.end_time and AttendanceService.is_work_status(s.status, category_map):
                a, b = span(d, s.start_time, s.end_time)
                segments.append((a, b, s))
        segments.sort(key=lambda x: x[0])
        total = interval_minutes((a, b) for a, b, _ in segments)
        scheduled = paid_minutes(
            total, len(segments),
            (fmt.unpaid_break_minutes if fmt else 0) or 0,
            fmt.unpaid_break_after_hours if fmt else None,
        )
        return DayPlan(shifts=shifts, segments=segments, scheduled_minutes=scheduled)

    @staticmethod
    async def punches_for(
        db: AsyncSession, tenant_id: UUID, employee_id: int, d: date
    ) -> List[TimePunch]:
        return list(
            (
                await db.execute(
                    select(TimePunch)
                    .where(
                        TimePunch.tenant_id == tenant_id,
                        TimePunch.employee_id == employee_id,
                        TimePunch.business_date == d,
                    )
                    .order_by(TimePunch.punched_at.asc())
                )
            ).scalars().all()
        )

    @staticmethod
    def punch_intervals(punches: List[TimePunch], tz: ZoneInfo) -> Tuple[List[Interval], List[datetime]]:
        """(closed in->out intervals, every clock-in instant), in tenant local time."""
        by_id = {p.id: p for p in punches}
        intervals: List[Interval] = []
        ins: List[datetime] = []
        for p in punches:
            if p.punch_type != "in":
                continue
            s = to_local(p.punched_at, tz)
            ins.append(s)
            partner = by_id.get(p.paired_punch_id) if p.paired_punch_id else None
            if partner is not None:
                e = to_local(partner.punched_at, tz)
                if e > s:
                    intervals.append((s, e))
        return intervals, ins

    @staticmethod
    async def approved_leave_on(
        db: AsyncSession, tenant_id: UUID, employee_id: int, d: date
    ) -> Optional[LeaveApplication]:
        return (
            await db.execute(
                select(LeaveApplication)
                .where(
                    LeaveApplication.tenant_id == tenant_id,
                    LeaveApplication.employee_id == employee_id,
                    LeaveApplication.status == "approved",
                    LeaveApplication.start_date <= d,
                    LeaveApplication.end_date >= d,
                )
                .order_by(LeaveApplication.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    # ── deriving a day ───────────────────────────────────────────────────

    @staticmethod
    async def _facts(
        db: AsyncSession, record: AttendanceRecord, employee: Optional[User],
        settings: Optional[AppSettings] = None,
    ) -> DayFacts:
        tenant_id = record.tenant_id
        if settings is None:
            settings = await AttendanceService._settings(db, tenant_id)
        tz = tenant_zone(settings)
        fmt = await AttendanceService._schedule_format(db, tenant_id, employee)
        plan = await AttendanceService.day_plan(db, tenant_id, record.employee_id, record.date, fmt)
        unpaid_break = (fmt.unpaid_break_minutes if fmt else 0) or 0
        hours_per_day = (
            (fmt.hours_per_day if fmt and fmt.hours_per_day else None)
            or (getattr(settings, "default_shift_duration_hours", None) if settings else None)
            or 8.0
        )

        # Paired punches when the day has them AND the record's times still
        # match them. Once someone corrects the times by hand, the correction
        # is what the day is judged on.
        intervals: List[Interval] = []
        ins: List[datetime] = []
        punches = await AttendanceService.punches_for(db, tenant_id, record.employee_id, record.date)
        use_punches = False
        if punches:
            p_int, p_ins = AttendanceService.punch_intervals(punches, tz)
            outs = [to_local(p.punched_at, tz) for p in punches if p.punch_type == "out"]
            first_in = min(p_ins).time() if p_ins else None
            last_out = max(outs).time() if outs else None

            def _same(a, b):
                return (a is None and b is None) or (
                    a is not None and b is not None
                    and a.hour == b.hour and a.minute == b.minute
                )

            if _same(first_in, record.actual_start_time) and _same(last_out, record.actual_end_time):
                intervals, ins, use_punches = p_int, p_ins, True
        if not use_punches and record.actual_start_time:
            anchor = plan.segments[0][0] if plan.segments else None
            s = _nearest(record.date, record.actual_start_time, anchor)
            ins = [s]
            if record.actual_end_time:
                e = datetime.combine(s.date(), record.actual_end_time)
                if e <= s:
                    e += timedelta(days=1)
                intervals = [(s, e)]

        worked = interval_minutes(intervals)
        paid = paid_minutes(
            worked, len(intervals), unpaid_break,
            fmt.unpaid_break_after_hours if fmt else None,
        )

        tardiness = 0
        if plan.segments and ins:
            starts = [a for a, _, _ in plan.segments]
            first_in_by_segment: Dict[int, datetime] = {}
            for t in ins:
                idx = min(range(len(starts)), key=lambda i: abs((t - starts[i]).total_seconds()))
                if idx not in first_in_by_segment or t < first_in_by_segment[idx]:
                    first_in_by_segment[idx] = t
            for idx, t in first_in_by_segment.items():
                late = int((t - starts[idx]).total_seconds() // 60)
                if late > 0:
                    tardiness += late

        overtime = 0
        undertime = 0
        if intervals:
            if plan.is_work_day:
                overtime = max(0, paid - plan.scheduled_minutes)
                undertime = max(0, plan.scheduled_minutes - paid)
            else:
                # Nothing rostered to measure against: the format's day length
                # is the only yardstick (and the day is flagged as rest-day work).
                overtime = max(0, int(paid - hours_per_day * 60))

        metrics = {
            "hours_worked": round(paid / 60.0, 2) if intervals else None,
            "tardiness_minutes": tardiness,
            "overtime_minutes": overtime,
            "undertime_minutes": undertime,
            "is_rest_day_work": bool(ins) and not plan.is_work_day,
        }
        return DayFacts(
            plan=plan, intervals=intervals, in_instants=ins, fmt=fmt,
            hours_per_day=hours_per_day, unpaid_break_minutes=unpaid_break,
            worked_minutes=worked, paid_worked_minutes=paid, metrics=metrics,
        )

    @staticmethod
    async def _apply_facts(db: AsyncSession, record: AttendanceRecord, facts: DayFacts) -> None:
        m = facts.metrics
        record.hours_worked = m["hours_worked"]
        record.tardiness_minutes = m["tardiness_minutes"]
        record.overtime_minutes = m["overtime_minutes"]
        record.undertime_minutes = m["undertime_minutes"]
        record.is_rest_day_work = m["is_rest_day_work"]
        plan = facts.plan
        first = plan.first_shift
        record.shift_id = first.id if first else None
        if plan.segments:
            record.scheduled_start_time = plan.segments[0][0].time()
            record.scheduled_end_time = plan.segments[-1][1].time()
        else:
            record.scheduled_start_time = first.start_time if first else None
            record.scheduled_end_time = first.end_time if first else None

        record.excused_by_leave_id = None
        if record.status_override:
            record.status = record.status_override
        elif not facts.in_instants:
            leave = await AttendanceService.approved_leave_on(
                db, record.tenant_id, record.employee_id, record.date
            )
            if leave is not None:
                record.status = "excused"
                record.excused_by_leave_id = leave.id
            else:
                record.status = "absent"
        elif m["tardiness_minutes"] > 0:
            record.status = "late"
        else:
            record.status = "present"

    @staticmethod
    async def rederive(
        db: AsyncSession, record: AttendanceRecord, employee: Optional[User] = None,
    ) -> AttendanceRecord:
        """Recompute every derived field of `record`, purge what the policy
        engine made from the old figures and run it again on the new ones."""
        if employee is None:
            employee = await db.get(User, record.employee_id)
        facts = await AttendanceService._facts(db, record, employee)
        await AttendanceService._apply_facts(db, record, facts)
        await db.flush()
        await AttendanceService._purge_engine_records(db, record)
        if employee:
            await AttendanceService._evaluate_policies(db, record.tenant_id, record, employee, facts)
        return record

    @staticmethod
    async def sync_from_punches(
        db: AsyncSession, tenant_id: UUID, employee_id: int, d: date,
        recorded_by: Optional[int] = None,
    ) -> Optional[AttendanceRecord]:
        """Rebuild the day's record from its punches (after a punch, a
        location fix or an automatic clock-out)."""
        punches = await AttendanceService.punches_for(db, tenant_id, employee_id, d)
        record = (
            await db.execute(
                select(AttendanceRecord).where(
                    AttendanceRecord.tenant_id == tenant_id,
                    AttendanceRecord.employee_id == employee_id,
                    AttendanceRecord.date == d,
                )
            )
        ).scalar_one_or_none()
        if not punches:
            return record
        settings = await AttendanceService._settings(db, tenant_id)
        tz = tenant_zone(settings)
        # The day's first clock-in and last clock-out by INSTANT, not by time
        # of day: on a night shift 01:00 comes after 22:00.
        ins = [to_local(p.punched_at, tz) for p in punches if p.punch_type == "in"]
        outs = [to_local(p.punched_at, tz) for p in punches if p.punch_type == "out"]
        if record is None:
            record = AttendanceRecord(
                tenant_id=tenant_id, employee_id=employee_id, date=d,
                recorded_by=recorded_by, self_reported=True,
            )
            db.add(record)
        else:
            record.self_reported = True
            if recorded_by is not None:
                record.recorded_by = recorded_by
            # A punch is fresh evidence; a no-show mark made before it is not.
            record.auto_marked = False
        record.actual_start_time = min(ins).time().replace(microsecond=0) if ins else None
        record.actual_end_time = max(outs).time().replace(microsecond=0) if outs else None
        await db.flush()
        for p in punches:
            p.attendance_record_id = record.id
        await AttendanceService.rederive(db, record)
        return record

    # ── writes ───────────────────────────────────────────────────────────

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
        employee = await db.get(User, employee_id)
        if not employee or employee.tenant_id != tenant_id:
            raise ValueError("Employee not found")

        record = AttendanceRecord(
            tenant_id=tenant_id,
            employee_id=employee_id,
            date=attendance_date,
            actual_start_time=actual_start,
            actual_end_time=actual_end,
            notes=notes,
            recorded_by=recorded_by,
            self_reported=self_reported,
        )
        db.add(record)
        await db.flush()
        await AttendanceService.rederive(db, record, employee)
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
        # Someone has now said what happened; it is no longer the no-show job's guess.
        existing.auto_marked = False
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
        payroll run are preserved; see _purge_engine_records.)

        `status` in `data` is a hand-picked status that sticks through later
        re-derivations; an empty string clears it and lets the times decide."""
        record = await AttendanceService.get_attendance(db, tenant_id, record_id)
        if not record:
            return None

        if "notes" in data:
            record.notes = data["notes"]
        for fld in ("actual_start_time", "actual_end_time"):
            if fld in data:
                setattr(record, fld, data[fld])
        if "status" in data:
            record.status_override = data["status"] or None

        await AttendanceService.rederive(db, record)
        return record

    @staticmethod
    async def _purge_engine_records(db: AsyncSession, record: AttendanceRecord) -> None:
        """Delete the OT logs, tardiness records and their derived leave-credit
        adjustments that a PREVIOUS engine run created for this attendance record,
        so an edit can be re-evaluated cleanly without duplicates or orphans.

        Overtime already paid by a finalized payroll run (payroll_period_id /
        paid_at set at finalize) is LEFT ALONE — those figures are locked; a
        correction must be posted through payroll instead. The engine then
        skips re-creating a log of the same kind (see PolicyEngineService)."""
        from sqlalchemy import delete
        ot_rows = (await db.execute(
            select(OvertimeLog).where(OvertimeLog.attendance_record_id == record.id)
        )).scalars().all()
        for ot in ot_rows:
            if ot.payroll_period_id is not None or ot.paid_at is not None:
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

    # ── policy engine ────────────────────────────────────────────────────

    @staticmethod
    async def _policy_context(
        db: AsyncSession, record: AttendanceRecord, employee: Optional[User], facts: DayFacts,
    ) -> dict:
        from app.services.holiday_calendar import holidays_between

        days = {record.date}
        for s, e in facts.intervals:
            cur = s.date()
            while cur <= e.date():
                days.add(cur)
                cur += timedelta(days=1)
        hols = await holidays_between(db, record.tenant_id, min(days), max(days))
        holiday_dates: Set[date] = {d for d in days if d in hols}
        is_special = any(hols[d].is_special for d in holiday_dates)
        first = facts.intervals[0] if facts.intervals else None
        last = facts.intervals[-1] if facts.intervals else None
        context = PolicyEngineService.build_context(
            attendance=record,
            schedule_format=employee.schedule_format if employee else None,
            employee_type=employee.employee_type if employee else None,
            is_holiday=bool(holiday_dates),
            is_special=is_special,
            shift_hours=(facts.plan.scheduled_minutes / 60.0) if facts.plan.is_work_day else None,
            actual_start_time=first[0].time() if first else record.actual_start_time,
            actual_end_time=last[1].time() if last else record.actual_end_time,
            holiday_dates=holiday_dates,
            attendance_date=record.date,
        )
        context["worked_intervals"] = list(facts.intervals)
        context["paid_ratio"] = (
            facts.paid_worked_minutes / facts.worked_minutes if facts.worked_minutes else 1.0
        )
        context["is_rest_day"] = bool(facts.metrics.get("is_rest_day_work"))
        return context

    @staticmethod
    async def _evaluate_policies(
        db: AsyncSession, tenant_id: UUID, record: AttendanceRecord, employee: User,
        facts: Optional[DayFacts] = None,
    ) -> None:
        """Build the policy context for an attendance record and run the engine."""
        if facts is None:
            facts = await AttendanceService._facts(db, record, employee)
        context = await AttendanceService._policy_context(db, record, employee, facts)
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

        settings = await AttendanceService._settings(db, tenant_id)
        effects: List[dict] = []
        for rec in records:
            employee = await db.get(User, rec.employee_id)
            facts = await AttendanceService._facts(db, rec, employee, settings)
            context = await AttendanceService._policy_context(db, rec, employee, facts)
            rec_effects = await PolicyEngineService.simulate_record(db, rec, context, rules)
            for e in rec_effects:
                effects.append({
                    "employee_id": rec.employee_id,
                    "employee_name": names.get(rec.employee_id),
                    "date": rec.date,
                    **e,
                })

        return {"records_evaluated": len(records), "effects": effects}

    # ── reads ────────────────────────────────────────────────────────────

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
        employee_ids: Optional[Iterable[int]] = None,
    ) -> Tuple[List[AttendanceRecord], int]:
        """List attendance records with optional filters. `employee_ids`
        (None = everyone) limits the list to the caller's teams."""
        base = select(AttendanceRecord).where(AttendanceRecord.tenant_id == tenant_id)

        if employee_id:
            base = base.where(AttendanceRecord.employee_id == employee_id)
        if employee_ids is not None:
            base = base.where(AttendanceRecord.employee_id.in_(list(employee_ids)))
        if start_date:
            base = base.where(AttendanceRecord.date >= start_date)
        if end_date:
            base = base.where(AttendanceRecord.date <= end_date)
        if status:
            base = base.where(AttendanceRecord.status == status)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await db.execute(count_stmt)).scalar() or 0

        stmt = base.order_by(AttendanceRecord.date.desc(), AttendanceRecord.id.desc())
        stmt = stmt.offset(skip).limit(limit)
        result = await db.execute(stmt)
        records = list(result.scalars().all())

        return records, total

    @staticmethod
    async def _get_shift(
        db: AsyncSession, tenant_id: UUID, employee_id: int, attendance_date: date
    ) -> Optional[Shift]:
        """The first PUBLISHED shift for an employee on a given date."""
        shifts = await AttendanceService.published_shifts(db, tenant_id, employee_id, attendance_date)
        return shifts[0] if shifts else None
