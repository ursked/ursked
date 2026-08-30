"""Clock in / clock out.

Punches are events. After each one the day's AttendanceRecord is re-derived from
the punches that belong to it, so tardiness, overtime and the policy engine keep
working exactly as they do for a manually entered timesheet.
"""

from datetime import date as date_cls, datetime, time as time_cls, timedelta, timezone
from typing import List, Optional, Tuple
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attendance import AttendanceRecord, TimePunch
from app.models.schedule import Shift
from app.models.settings import AppSettings
from app.models.work_site import WorkArrangementRule, WorkSite
from app.services.attendance_service import AttendanceService
from app.services.geo_service import evaluate_geofence

# Statuses meaning "no location was supplied with the punch".
_MISSING_LOCATION = {"denied", "unavailable", "timeout", "insecure_context"}

# Shift statuses that are not work, so a punch should not be matched to them.
_NON_WORK = {"rest_day", "holiday_off"}


class TimeclockError(Exception):
    """Raised for a punch that contradicts the employee's current state."""

    def __init__(self, message: str, current_state: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.current_state = current_state


def _minutes(t: time_cls) -> int:
    return t.hour * 60 + t.minute


async def _settings(db: AsyncSession, tenant_id: UUID) -> Optional[AppSettings]:
    return (
        await db.execute(select(AppSettings).where(AppSettings.tenant_id == tenant_id))
    ).scalar_one_or_none()


def _tenant_now(tz_name: str) -> Tuple[datetime, datetime]:
    """(utc_instant, tenant_local_instant). The server clock is authoritative."""
    utc_now = datetime.now(timezone.utc)
    try:
        local = utc_now.astimezone(ZoneInfo(tz_name))
    except (ZoneInfoNotFoundError, ValueError):
        local = utc_now
    return utc_now, local


class TimeclockService:

    # ── reads ────────────────────────────────────────────────────────────────

    @staticmethod
    async def open_punch(db: AsyncSession, tenant_id: UUID, employee_id: int) -> Optional[TimePunch]:
        """The clock-in that has not been closed yet, if any."""
        return (
            await db.execute(
                select(TimePunch)
                .where(
                    TimePunch.tenant_id == tenant_id,
                    TimePunch.employee_id == employee_id,
                    TimePunch.punch_type == "in",
                    TimePunch.paired_punch_id.is_(None),
                )
                .order_by(TimePunch.punched_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    @staticmethod
    async def punches_for_day(
        db: AsyncSession, tenant_id: UUID, employee_id: int, business_date: date_cls
    ) -> List[TimePunch]:
        return list(
            (
                await db.execute(
                    select(TimePunch)
                    .where(
                        TimePunch.tenant_id == tenant_id,
                        TimePunch.employee_id == employee_id,
                        TimePunch.business_date == business_date,
                    )
                    .order_by(TimePunch.punched_at.asc())
                )
            ).scalars().all()
        )

    # ── helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    async def _arrangement_mode(db: AsyncSession, tenant_id: UUID, code: Optional[str]) -> str:
        """Geofence expectation for a work_arrangement code.

        `shifts.work_arrangement` has never been validated, so live data holds
        whatever anyone typed. Unknown codes deliberately FAIL OPEN: a typo must
        not become a false "outside the geofence" on a timesheet.
        """
        if not code:
            return "any_location"
        rule = (
            await db.execute(
                select(WorkArrangementRule).where(
                    WorkArrangementRule.tenant_id == tenant_id,
                    WorkArrangementRule.code == code.strip().lower(),
                    WorkArrangementRule.is_active == True,  # noqa: E712
                )
            )
        ).scalar_one_or_none()
        return rule.geofence_mode if rule else "any_location"

    @staticmethod
    async def _day_shifts(
        db: AsyncSession, tenant_id: UUID, employee_id: int, business_date: date_cls
    ) -> List[Shift]:
        return list(
            (
                await db.execute(
                    select(Shift)
                    .where(
                        Shift.tenant_id == tenant_id,
                        Shift.employee_id == employee_id,
                        Shift.date == business_date,
                    )
                    .order_by(Shift.sequence_number.asc())
                )
            ).scalars().all()
        )

    @staticmethod
    def _match_shift(shifts: List[Shift], local_time: time_cls, punch_type: str) -> Optional[Shift]:
        """Pick the shift a punch belongs to.

        A split-shift day carries two shifts with different arrangements, so the
        nearest boundary decides: clock-ins compare against start times, clock-outs
        against end times. Non-work statuses are skipped so clocking in on a rest
        day does not silently attach to it.
        """
        working = [
            s for s in shifts
            if (s.status or "").lower() not in _NON_WORK and s.start_time and s.end_time
        ]
        if not working:
            return None
        target = _minutes(local_time)

        def distance(shift: Shift) -> int:
            anchor = shift.start_time if punch_type == "in" else shift.end_time
            delta = abs(target - _minutes(anchor))
            # A punch at 23:50 against an 00:10 boundary is 20 minutes away, not
            # 1420 — compare around the clock.
            return min(delta, 24 * 60 - delta)

        return min(working, key=distance)

    @staticmethod
    async def _resolve_business_date(
        db: AsyncSession, tenant_id: UUID, employee_id: int,
        local_dt: datetime, punch_type: str, open_punch: Optional[TimePunch],
    ) -> date_cls:
        """Which attendance day this punch belongs to.

        A clock-OUT always inherits the day from the clock-in it closes. That single
        rule is what makes overnight work correct: the 06:05 exit from a 22:00-06:00
        shift is attributed to the day the shift started, with no heuristics.

        A clock-IN normally uses today, unless the previous day holds an overnight
        shift that is still running — someone starting a night shift late, or
        clocking in just after midnight, still belongs to yesterday.
        """
        if punch_type == "out" and open_punch is not None:
            return open_punch.business_date

        local_date = local_dt.date()
        yesterday = local_date - timedelta(days=1)
        prev_shifts = await TimeclockService._day_shifts(db, tenant_id, employee_id, yesterday)
        now_min = _minutes(local_dt.time())
        for shift in prev_shifts:
            if not shift.start_time or not shift.end_time:
                continue
            if (shift.status or "").lower() in _NON_WORK:
                continue
            crosses_midnight = _minutes(shift.end_time) <= _minutes(shift.start_time)
            if crosses_midnight and now_min < _minutes(shift.end_time):
                return yesterday
        return local_date

    @staticmethod
    def _derive_times(punches: List[TimePunch]) -> Tuple[Optional[time_cls], Optional[time_cls], Optional[float]]:
        """Daily start/end plus worked hours summed over PAIRED intervals.

        First-in to last-out would bill the unpaid gap between the two halves of a
        split shift, so paired intervals are summed instead. Hours stay None until
        at least one pair is closed, which keeps a day that is still open from
        reporting undertime.
        """
        ins = [p for p in punches if p.punch_type == "in"]
        outs = [p for p in punches if p.punch_type == "out"]
        start = min((p.local_time for p in ins), default=None)
        end = max((p.local_time for p in outs), default=None)

        total_minutes = 0
        closed_any = False
        by_id = {p.id: p for p in punches}
        for p in ins:
            partner = by_id.get(p.paired_punch_id) if p.paired_punch_id else None
            if partner is None:
                continue
            closed_any = True
            delta = (partner.punched_at - p.punched_at).total_seconds() / 60.0
            if delta < 0:
                delta = 0
            total_minutes += delta
        hours = round(total_minutes / 60.0, 2) if closed_any else None
        return start, end, hours

    # ── the punch ────────────────────────────────────────────────────────────

    @staticmethod
    async def punch(
        db: AsyncSession,
        tenant_id: UUID,
        employee_id: int,
        punch_type: str,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        accuracy_m: Optional[float] = None,
        location_error: Optional[str] = None,
        client_time: Optional[datetime] = None,
        notes: Optional[str] = None,
        source: str = "web",
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        recorded_by: Optional[int] = None,
    ) -> TimePunch:
        settings = await _settings(db, tenant_id)
        if settings is None or not settings.timeclock_enabled:
            raise TimeclockError("The time clock is not enabled for this organisation.")
        if punch_type not in ("in", "out"):
            raise TimeclockError("punch_type must be 'in' or 'out'.")

        tz_name = settings.timezone or "UTC"
        utc_now, local_dt = _tenant_now(tz_name)

        open_punch = await TimeclockService.open_punch(db, tenant_id, employee_id)
        if punch_type == "in" and open_punch is not None:
            raise TimeclockError(
                "You are already clocked in. Clock out before starting again.",
                current_state="clocked_in",
            )
        if punch_type == "out" and open_punch is None:
            raise TimeclockError(
                "You are not clocked in, so there is nothing to close.",
                current_state="clocked_out",
            )

        business_date = await TimeclockService._resolve_business_date(
            db, tenant_id, employee_id, local_dt, punch_type, open_punch
        )

        shifts = await TimeclockService._day_shifts(db, tenant_id, employee_id, business_date)
        matched = TimeclockService._match_shift(shifts, local_dt.time(), punch_type)
        arrangement = matched.work_arrangement if matched else None
        mode = await TimeclockService._arrangement_mode(db, tenant_id, arrangement)

        # Location. A punch is never refused because of it.
        if latitude is not None and longitude is not None:
            location_status = "captured"
        elif not settings.timeclock_require_location:
            location_status = "not_required"
        else:
            location_status = location_error if location_error in _MISSING_LOCATION else "unavailable"

        recapture_deadline = None
        if location_status in _MISSING_LOCATION and (settings.timeclock_location_grace_minutes or 0) > 0:
            recapture_deadline = utc_now + timedelta(minutes=settings.timeclock_location_grace_minutes)

        sites = list(
            (
                await db.execute(select(WorkSite).where(WorkSite.tenant_id == tenant_id))
            ).scalars().all()
        )
        geofence_status, site_id, distance_m = evaluate_geofence(
            sites, latitude, longitude, accuracy_m, mode,
            pinned_site_id=getattr(matched, "work_site_id", None) if matched else None,
            default_radius_m=settings.timeclock_default_radius_m or 200,
        )

        skew = None
        if client_time is not None:
            if client_time.tzinfo is None:
                client_time = client_time.replace(tzinfo=timezone.utc)
            skew = int((client_time - utc_now).total_seconds())

        punch = TimePunch(
            tenant_id=tenant_id,
            employee_id=employee_id,
            business_date=business_date,
            punch_type=punch_type,
            shift_id=matched.id if matched else None,
            sequence_number=matched.sequence_number if matched else 1,
            work_arrangement=arrangement,
            punched_at=utc_now,
            local_time=local_dt.time().replace(microsecond=0),
            client_reported_at=client_time,
            clock_skew_seconds=skew,
            latitude=latitude,
            longitude=longitude,
            accuracy_m=accuracy_m,
            location_status=location_status,
            location_captured_at=utc_now if location_status == "captured" else None,
            recapture_deadline=recapture_deadline,
            geofence_status=geofence_status,
            work_site_id=site_id,
            distance_m=distance_m,
            source=source,
            ip_address=ip_address,
            user_agent=(user_agent or None) and user_agent[:255],
            notes=notes,
            recorded_by=recorded_by,
        )
        db.add(punch)
        await db.flush()

        if punch_type == "out" and open_punch is not None:
            open_punch.paired_punch_id = punch.id
            punch.paired_punch_id = open_punch.id
            await db.flush()

        await TimeclockService._rederive_day(db, tenant_id, employee_id, business_date, recorded_by)
        return punch

    @staticmethod
    async def _rederive_day(
        db: AsyncSession, tenant_id: UUID, employee_id: int,
        business_date: date_cls, recorded_by: Optional[int],
    ) -> Optional[AttendanceRecord]:
        """Rebuild the day's AttendanceRecord from its punches."""
        punches = await TimeclockService.punches_for_day(db, tenant_id, employee_id, business_date)
        start, end, hours = TimeclockService._derive_times(punches)

        record = await AttendanceService.upsert_attendance(
            db,
            tenant_id=tenant_id,
            employee_id=employee_id,
            attendance_date=business_date,
            actual_start=start,
            actual_end=end,
            recorded_by=recorded_by,
            self_reported=True,
        )
        if record is not None:
            # Paired-interval hours, not first-in-to-last-out. Only override once a
            # pair has closed; an open day keeps whatever upsert derived (None).
            if hours is not None:
                record.hours_worked = hours
            for p in punches:
                p.attendance_record_id = record.id
            await db.flush()
        return record

    @staticmethod
    async def attach_location(
        db: AsyncSession, tenant_id: UUID, employee_id: int, punch_id: int,
        latitude: float, longitude: float, accuracy_m: Optional[float] = None,
    ) -> TimePunch:
        """Attach a location to a punch that could not supply one at the time."""
        punch = (
            await db.execute(
                select(TimePunch).where(
                    TimePunch.id == punch_id,
                    TimePunch.tenant_id == tenant_id,
                    TimePunch.employee_id == employee_id,
                )
            )
        ).scalar_one_or_none()
        if punch is None:
            raise TimeclockError("Punch not found.")
        if punch.latitude is not None:
            raise TimeclockError("That punch already has a location.")
        if punch.recapture_deadline is None:
            raise TimeclockError("This punch cannot be updated with a location.")

        now = datetime.now(timezone.utc)
        deadline = punch.recapture_deadline
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        if now > deadline:
            raise TimeclockError(
                f"The window to add a location closed at "
                f"{deadline.astimezone(timezone.utc).strftime('%H:%M UTC')}."
            )

        settings = await _settings(db, tenant_id)
        mode = await TimeclockService._arrangement_mode(db, tenant_id, punch.work_arrangement)
        sites = list(
            (await db.execute(select(WorkSite).where(WorkSite.tenant_id == tenant_id))).scalars().all()
        )
        geofence_status, site_id, distance_m = evaluate_geofence(
            sites, latitude, longitude, accuracy_m, mode,
            pinned_site_id=None,
            default_radius_m=(settings.timeclock_default_radius_m if settings else 200) or 200,
        )

        punch.latitude = latitude
        punch.longitude = longitude
        punch.accuracy_m = accuracy_m
        # Stays 'recaptured' permanently. It is weaker evidence than a location
        # given at the moment of the punch — an employee can decline, travel, and
        # then supply a position — so a reviewer must always be able to tell the
        # two apart.
        punch.location_status = "recaptured"
        punch.location_captured_at = now
        punch.geofence_status = geofence_status
        punch.work_site_id = site_id
        punch.distance_m = distance_m
        await db.flush()
        return punch

    @staticmethod
    async def seed_arrangement_rules(db: AsyncSession, tenant_id: UUID) -> None:
        """Idempotently create the default arrangement rules for a tenant.

        Mirrors the vocabulary the scheduler already offers. Only `onsite` implies
        a place to be; work-from-home and official business record a location
        without judging it.
        """
        defaults = [
            ("onsite", "On-site", "require_site", 1),
            ("wfh", "Work From Home", "any_location", 2),
            ("hybrid", "Hybrid", "any_location", 3),
            ("ob", "Official Business", "any_location", 4),
        ]
        existing = {
            c for (c,) in (
                await db.execute(
                    select(WorkArrangementRule.code).where(
                        WorkArrangementRule.tenant_id == tenant_id
                    )
                )
            ).all()
        }
        for code, label, mode, order in defaults:
            if code in existing:
                continue
            db.add(WorkArrangementRule(
                tenant_id=tenant_id, code=code, label=label,
                geofence_mode=mode, sort_order=order,
            ))
        await db.flush()
