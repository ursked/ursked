"""Pure payroll computation helpers.

Kept free of DB/session so they can be unit-tested with plain values. The
service layer loads rows and calls these.
"""
import calendar
from datetime import date, datetime, time, timedelta
from typing import Iterable, Optional, Tuple


def bracket_amount(brackets: list, basis: float) -> tuple[float, Optional[dict]]:
    """Compute a tiered deduction from bracket rows for a basis value.

    Each bracket is an object/dict with over_amount, up_to_amount (None=inf),
    base_amount, rate, rate_basis ("excess"|"full"). The matching band is the
    one whose [over_amount, up_to_amount) contains `basis`.
        amount = base_amount + rate * (basis if rate_basis=="full"
                                       else max(0, basis - over_amount))
    Returns (amount, matched_bracket_dict_or_None).
    """
    def g(b, k, default=None):
        return getattr(b, k, None) if not isinstance(b, dict) else b.get(k, default)

    match = None
    for b in brackets:
        over = g(b, "over_amount") or 0.0
        up_to = g(b, "up_to_amount")
        if basis >= over and (up_to is None or basis < up_to):
            match = b
            break
    if match is None:
        return 0.0, None
    base = g(match, "base_amount") or 0.0
    rate = g(match, "rate") or 0.0
    rate_basis = g(match, "rate_basis") or "excess"
    over = g(match, "over_amount") or 0.0
    portion = basis if rate_basis == "full" else max(0.0, basis - over)
    amount = base + rate * portion
    return round(amount, 2), {
        "over_amount": over,
        "up_to_amount": g(match, "up_to_amount"),
        "base_amount": base,
        "rate": rate,
        "rate_basis": rate_basis,
    }


def deduction_amount(ded, gross_pay: float, base_pay: float, brackets: list) -> tuple[float, dict]:
    """Resolve one deduction's amount. Returns (amount, breakdown_entry)."""
    calc = getattr(ded, "calculation_type", "fixed")
    basis_kind = getattr(ded, "calculation_basis", "gross")
    basis = base_pay if basis_kind == "base" else gross_pay

    matched = None
    warning = None
    if calc == "fixed":
        amount = ded.default_amount or 0.0
    elif calc == "percentage":
        amount = round(basis * (ded.default_rate or 0.0), 2)
    elif calc == "tiered":
        # A tiered deduction with no table used to come out as 0 on every
        # payslip with nothing to say so, which is how statutory contributions
        # went unpaid. Say it, on the payslip line and in the run's warnings.
        if not brackets:
            amount = 0.0
            warning = (
                f"{ded.name} is a tiered deduction with no brackets, so nothing was "
                "deducted. Add its brackets under Finances, Deductions, then compute again."
            )
        else:
            amount, matched = bracket_amount(brackets, basis)
            if matched is None:
                warning = (
                    f"{ded.name}: no bracket covers {basis:,.2f}, so nothing was deducted. "
                    "Check its brackets under Finances, Deductions."
                )
    else:
        amount = ded.default_amount or 0.0

    entry = {
        "code": ded.code,
        "name": ded.name,
        "type": calc,
        "basis": basis_kind,
        "amount": round(amount, 2),
        "is_employer": ded.is_employer_contribution,
    }
    if matched is not None:
        entry["bracket"] = matched
    if warning:
        entry["warning"] = warning
    return round(amount, 2), entry


def validate_brackets(brackets: list) -> list:
    """Sort a tiered table and reject one that cannot be applied.

    Bands must run upwards without gaps or overlaps, and only the last may be
    open-ended: a basis falling in a gap matched nothing and deducted 0.
    Returns the sorted list; raises ValueError with a readable sentence.
    """
    def g(b, k, default=None):
        return b.get(k, default) if isinstance(b, dict) else getattr(b, k, default)

    ordered = sorted(brackets, key=lambda b: g(b, "over_amount", 0) or 0)
    for i, b in enumerate(ordered):
        over = g(b, "over_amount", 0) or 0
        up_to = g(b, "up_to_amount")
        row = i + 1
        if over < 0:
            raise ValueError(f"Row {row}: 'From' cannot be negative.")
        if (g(b, "rate", 0) or 0) < 0 or (g(b, "base_amount", 0) or 0) < 0:
            raise ValueError(f"Row {row}: amounts and rates cannot be negative.")
        if up_to is not None and up_to <= over:
            raise ValueError(f"Row {row}: 'To' must be more than 'From'.")
        if up_to is None and i != len(ordered) - 1:
            raise ValueError(f"Row {row}: only the last row can have no upper limit.")
        if i > 0:
            prev_up = g(ordered[i - 1], "up_to_amount")
            if over < prev_up:
                raise ValueError(f"Rows {row - 1} and {row} overlap: row {row} starts before row {row - 1} ends.")
            if over > prev_up:
                raise ValueError(
                    f"There is a gap between rows {row - 1} and {row}: nothing covers "
                    f"{prev_up:,.2f} to {over:,.2f}. Start row {row} where row {row - 1} ends."
                )
    return ordered


def period_fraction(period_type: str) -> float:
    """Fraction of a monthly salary paid for one period of the given type."""
    return {
        "monthly": 1.0,
        "semi_monthly": 0.5,
        "semimonthly": 0.5,
        "biweekly": 12.0 / 26.0,
        "weekly": 12.0 / 52.0,
        "daily": 1.0 / 22.0,
    }.get(period_type, 1.0)


def derive_rates(grade, working_days_per_month: int, shift_hours: float) -> tuple[float, float]:
    """Return (daily_rate, hourly_rate), using explicit grade rates when set,
    otherwise deriving from the monthly rate."""
    monthly = grade.monthly_rate if grade else 0.0
    wdpm = working_days_per_month or 22
    shift_hours = shift_hours or 8
    daily = grade.daily_rate if (grade and grade.daily_rate) else (monthly / wdpm if wdpm else 0.0)
    hourly = grade.hourly_rate if (grade and grade.hourly_rate) else (daily / shift_hours if shift_hours else 0.0)
    return round(daily, 4), round(hourly, 4)


def _overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> int:
    """Plain overlap in minutes between two absolute [start, end) intervals."""
    return max(0, min(a_end, b_end) - max(a_start, b_start))


def night_diff_minutes(start: time, end: time, night_start: time, night_end: time) -> int:
    """Minutes of a shift that fall within the (possibly midnight-wrapping)
    night window. Both the shift and the window are expanded onto an absolute
    minute axis so a shift on any day intersects the night windows anchored on
    the day it starts and the next day."""
    if not (start and end and night_start and night_end):
        return 0
    s = start.hour * 60 + start.minute
    e = end.hour * 60 + end.minute
    if e <= s:  # shift crosses midnight
        e += 1440
    ns = night_start.hour * 60 + night_start.minute
    ne = night_end.hour * 60 + night_end.minute
    if ns == ne:
        return 0

    # Concrete night intervals on the absolute axis. A wrapping window
    # (ns > ne) becomes [ns, ne+1440]. Anchor on the previous, current, and next
    # day so an early-morning shift catches the prior night's window and a late
    # shift catches the following morning's. The windows are ≥1440 apart, so a
    # ≤24h shift overlaps at most one, avoiding any double count.
    windows: list[tuple[int, int]] = []
    for day in (-1, 0, 1):
        base = day * 1440
        if ns < ne:
            windows.append((base + ns, base + ne))
        else:
            windows.append((base + ns, base + ne + 1440))

    total = 0
    for ws, we in windows:
        total += _overlap(s, e, ws, we)
    return total


# ── Worked time ──────────────────────────────────────────────────────────
#
# Premiums and attendance metrics work on real datetimes, never on times of
# day subtracted on one date: `end - start` for a 22:00-06:00 shift is -16
# hours, and until 2026-09 that is exactly why every overnight shift earned no
# holiday or night premium at all.

Interval = Tuple[datetime, datetime]


def span(d: date, start: time, end: time) -> Interval:
    """(start, end) of a shift or worked stretch that begins on `d`. An end at
    or before the start is on the following day."""
    s = datetime.combine(d, start)
    e = datetime.combine(d, end)
    if e <= s:
        e += timedelta(days=1)
    return s, e


def interval_minutes(intervals: Iterable[Interval]) -> int:
    return int(sum(max(0.0, (e - s).total_seconds()) for s, e in intervals) // 60)


def paid_minutes(
    total_minutes: int, pieces: int, unpaid_break_minutes: int = 0,
    unpaid_break_after_hours: Optional[float] = None,
) -> int:
    """Minutes that count as work once the unpaid break is taken off.

    The schedule format's unpaid break applies to a day worked in ONE stretch
    that is long enough to need a break. On a split day the gap between the
    stretches is the break, so taking the format's break off again would
    count it twice.
    """
    if total_minutes <= 0:
        return 0
    brk = unpaid_break_minutes or 0
    if brk <= 0 or pieces != 1:
        return total_minutes
    if unpaid_break_after_hours and total_minutes <= unpaid_break_after_hours * 60:
        return total_minutes
    return max(0, total_minutes - brk)


def minutes_on_dates(intervals: Iterable[Interval], dates) -> dict:
    """{date: minutes of `intervals` that fall on that calendar date}, for the
    dates in `dates` only. An overnight stretch into a holiday counts only the
    part after midnight."""
    wanted = set(dates or ())
    out: dict = {}
    if not wanted:
        return out
    for s, e in intervals:
        cur = s.date()
        while cur <= e.date():
            if cur in wanted:
                day_start = datetime.combine(cur, time(0, 0))
                day_end = day_start + timedelta(days=1)
                lo, hi = max(s, day_start), min(e, day_end)
                if hi > lo:
                    out[cur] = out.get(cur, 0) + int((hi - lo).total_seconds() // 60)
            cur += timedelta(days=1)
    return out


def night_minutes_in(intervals: Iterable[Interval], night_start: Optional[time],
                     night_end: Optional[time]) -> int:
    """Minutes of `intervals` inside the nightly window, which may wrap
    midnight (22:00-06:00). Every night window touching an interval counts."""
    if not (night_start and night_end) or night_start == night_end:
        return 0
    total = 0
    for s, e in intervals:
        cur = s.date() - timedelta(days=1)
        while cur <= e.date():
            ws, we = span(cur, night_start, night_end)
            lo, hi = max(s, ws), min(e, we)
            if hi > lo:
                total += int((hi - lo).total_seconds() // 60)
            cur += timedelta(days=1)
    return total


# ── Payout scheduling ────────────────────────────────────────────────────

def _clamp_day(year: int, month: int, day: int) -> date:
    """Return date(year, month, day), clamping day to the month's last day and
    rolling month/year forward when month > 12."""
    while month > 12:
        month -= 12
        year += 1
    while month < 1:
        month += 12
        year -= 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(day, last))


def _add_months(d: date, months: int) -> date:
    """Add whole months to a date, clamping the day to the target month length."""
    return _clamp_day(d.year, d.month + months, d.day)


def resolve_payout_date(earned_on: date, cutoffs: list, *, adjust: str = "none",
                        holidays: Optional[set] = None) -> Optional[date]:
    """Map an ``earned_on`` date to the payout date its tenant pays it on.

    ``cutoffs`` is a list of dicts, each:
        {cutoff_start_day, cutoff_end_day, payout_day, payout_month_offset}
    The matching cutoff is the one whose [start_day, end_day] range (within the
    earned_on month) contains earned_on.day. The payout date is
    ``payout_day`` of the earned_on month shifted by ``payout_month_offset``
    months (clamped to month length).

    ``adjust`` optionally moves a payout landing on a weekend (or a date in
    ``holidays``) to the previous/next business day.

    Returns None if no cutoff matches (misconfigured schedule).
    """
    if not cutoffs:
        return None
    day = earned_on.day
    match = None
    for c in cutoffs:
        start = int(c.get("cutoff_start_day", 1))
        end = int(c.get("cutoff_end_day", 31))
        if start <= day <= end:
            match = c
            break
    if match is None:
        # Last cutoff often ends at 31; catch end-of-month days beyond its stated
        # end by falling back to the cutoff with the highest end_day.
        match = max(cutoffs, key=lambda c: int(c.get("cutoff_end_day", 31)))

    payout_day = int(match.get("payout_day", 15))
    offset = int(match.get("payout_month_offset", 0))
    base = _clamp_day(earned_on.year, earned_on.month, payout_day)
    payout = _add_months(base, offset)
    return _adjust_business_day(payout, adjust, holidays or set())


def _adjust_business_day(d: date, adjust: str, holidays: set) -> date:
    """Shift d off weekends/holidays per the adjust rule."""
    if adjust not in ("prev_business_day", "next_business_day"):
        return d
    step = 1 if adjust == "next_business_day" else -1
    cur = d
    # Bound the walk so a bad holidays set can't loop forever.
    for _ in range(14):
        if cur.weekday() < 5 and cur not in holidays:
            return cur
        cur = cur + timedelta(days=step)
    return d
