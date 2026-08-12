"""Pure payroll computation helpers.

Kept free of DB/session so they can be unit-tested with plain values. The
service layer loads rows and calls these.
"""
import calendar
from datetime import date, time, timedelta
from typing import Optional


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
    if calc == "fixed":
        amount = ded.default_amount or 0.0
    elif calc == "percentage":
        amount = round(basis * (ded.default_rate or 0.0), 2)
    elif calc == "tiered":
        amount, matched = bracket_amount(brackets, basis)
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
    return round(amount, 2), entry


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
