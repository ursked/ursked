"""Keep a tenant's public holidays up to date from a live calendar feed.

Holidays used to be typed in by hand, once, and forgotten: the live install
had 79 holiday-off shifts on 16 dates and zero registered holidays. Holidays
also move (Eid follows the moon, governments proclaim extra days at short
notice), so a list entered in January is wrong by June.

officeholidays.com publishes a free iCal feed per country, no key needed:
https://www.officeholidays.com/ics/<country-slug>. An admin can also point at
any other https iCal URL. This module fetches it, parses it with a small
tolerant iCal reader, works out which days are holidays and of what kind, and
merges them into date_remarks:

  * national holidays always; regional ones only for the regions the admin
    ticked (a Cebu charter day is not a holiday in Manila);
  * "Regular holiday" -> regular, anything saying "Special" -> special, and
    anything else is saved as regular with needs_review, because guessing
    "special" would underpay and guessing wrong silently is worse than asking;
  * "Date to be confirmed" -> is_tentative;
  * rows keep `source='feed'`. A feed row an admin edits is never overwritten
    again (locally_modified); one they delete becomes a tombstone the sync
    will not re-add (is_suppressed); a manual holiday on the same date wins;
  * past holidays are never removed (payroll history depends on them); a
    future feed holiday that disappeared from the feed is removed, unless it
    was edited here.

A dry run returns exactly what a sync would add, change and remove, and
writes nothing. `run_due` is the scheduler entry point.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
import socket
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional
from urllib.parse import urlparse
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.schedule import DateRemark, HolidaySource

logger = logging.getLogger(__name__)

OFFICEHOLIDAYS_URL = "https://www.officeholidays.com/ics/{slug}"
FETCH_TIMEOUT_S = 15
MAX_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 3
SYNC_EVERY = timedelta(hours=24)
RETRY_AFTER_FAILURE = timedelta(hours=1)

# Countries offered in the picker (slug as officeholidays.com spells it,
# display name, ISO 3166-1 alpha-2). Checked against the live site on
# 2026-09-28: note "usa" and "uae", not "united-states" / "united-arab-emirates".
COUNTRIES = [
    ("philippines", "Philippines", "PH"),
    ("usa", "United States", "US"),
    ("singapore", "Singapore", "SG"),
    ("malaysia", "Malaysia", "MY"),
    ("indonesia", "Indonesia", "ID"),
    ("australia", "Australia", "AU"),
    ("united-kingdom", "United Kingdom", "GB"),
    ("canada", "Canada", "CA"),
    ("india", "India", "IN"),
    ("japan", "Japan", "JP"),
    ("hong-kong", "Hong Kong", "HK"),
    ("uae", "United Arab Emirates", "AE"),
    ("saudi-arabia", "Saudi Arabia", "SA"),
    ("new-zealand", "New Zealand", "NZ"),
    ("germany", "Germany", "DE"),
    ("ireland", "Ireland", "IE"),
    ("thailand", "Thailand", "TH"),
    ("vietnam", "Vietnam", "VN"),
    ("south-korea", "South Korea", "KR"),
]

_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
# 2026-02-24PH-CEB3707regregion@...  -> PH-CEB. Subdivision codes are letters
# (PH-CEB, US-LA, GB-SCT) or exactly two digits (PH-00, MY-10, JP-13), then
# the site's own numeric id.
_REGION_RE = re.compile(r"^\d{4}-\d{2}-\d{2}([A-Z]{2}-(?:[A-Z]{1,3}|\d{2}))\d")


class HolidayFeedError(Exception):
    """A readable sentence for the admin about why the feed could not be used."""


def suggest_country_slug(country: Optional[str]) -> Optional[str]:
    """The picker default for a tenant whose country is set (free text: a
    name like "Philippines" or a code like "PH")."""
    if not country:
        return None
    c = country.strip().lower()
    for slug, name, iso2 in COUNTRIES:
        if c in (slug, name.lower(), iso2.lower()):
            return slug
    return None


# ── Fetching ──────────────────────────────────────────────────────────


def feed_url_for(source: HolidaySource) -> str:
    if source.provider == "officeholidays":
        slug = (source.country_slug or "").strip().lower()
        if not _SLUG_RE.match(slug):
            raise HolidayFeedError("Choose a country for the holiday calendar.")
        return OFFICEHOLIDAYS_URL.format(slug=slug)
    url = (source.feed_url or "").strip()
    if not url:
        raise HolidayFeedError("Enter the address of the iCal feed.")
    return url


def _address_is_public(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return not (
        addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_multicast
        or addr.is_reserved or addr.is_unspecified or not addr.is_global
    )


async def assert_public_https_url(url: str) -> None:
    """Refuse anything but https to a publicly routable host.

    A custom feed URL is fetched by the server, so without this an admin (or
    anyone who takes over an admin session) could make it read internal
    services: the database host, the cloud metadata endpoint at
    169.254.169.254, a router's admin page. The host is resolved and every
    address it resolves to must be public."""
    parts = urlparse(url)
    if parts.scheme != "https":
        raise HolidayFeedError("The calendar address must start with https://.")
    host = parts.hostname
    if not host:
        raise HolidayFeedError("That calendar address has no host name.")
    try:
        infos = await asyncio.get_running_loop().run_in_executor(
            None, lambda: socket.getaddrinfo(host, parts.port or 443, type=socket.SOCK_STREAM)
        )
    except socket.gaierror:
        raise HolidayFeedError(f"Could not find the server {host}.")
    ips = {info[4][0] for info in infos}
    if not ips or not all(_address_is_public(ip) for ip in ips):
        raise HolidayFeedError(
            "That calendar address points to a private or local network, which is not allowed."
        )


async def fetch_feed(url: str, *, guard: bool = True) -> str:
    """Download the calendar: https only, 15 s, at most 2 MB, redirects
    followed by hand so each hop is checked again."""
    current = url
    async with httpx.AsyncClient(
        timeout=FETCH_TIMEOUT_S, follow_redirects=False,
        headers={"User-Agent": "Ursked holiday sync (+https://www.officeholidays.com)",
                 "Accept": "text/calendar, */*;q=0.5"},
    ) as client:
        for _ in range(MAX_REDIRECTS + 1):
            if guard:
                await assert_public_https_url(current)
            try:
                async with client.stream("GET", current) as resp:
                    if resp.is_redirect:
                        current = str(resp.next_request.url) if resp.next_request else ""
                        continue
                    if resp.status_code == 404:
                        raise HolidayFeedError(
                            "No holiday calendar was found at that address. Check the country "
                            "(or the link) and try again."
                        )
                    if resp.status_code >= 400:
                        raise HolidayFeedError(
                            f"The holiday calendar could not be downloaded (the server answered {resp.status_code})."
                        )
                    body = bytearray()
                    async for chunk in resp.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > MAX_BYTES:
                            raise HolidayFeedError("The holiday calendar is larger than 2 MB, so it was not used.")
            except httpx.TimeoutException:
                raise HolidayFeedError("The holiday calendar did not answer within 15 seconds.")
            except httpx.HTTPError as exc:
                raise HolidayFeedError(f"The holiday calendar could not be reached ({exc.__class__.__name__}).")
            text = body.decode("utf-8", errors="replace").lstrip("﻿")
            if "BEGIN:VCALENDAR" not in text[:2000]:
                raise HolidayFeedError(
                    "That address did not return a calendar. Check the country (or the link)."
                )
            return text
    raise HolidayFeedError("The calendar address redirected too many times.")


# ── Parsing ───────────────────────────────────────────────────────────


@dataclass
class IcsEvent:
    uid: str
    summary: str
    description: str
    start: date
    end: date  # exclusive


def _unescape(v: str) -> str:
    out, i = [], 0
    while i < len(v):
        ch = v[i]
        if ch == "\\" and i + 1 < len(v):
            nxt = v[i + 1]
            out.append("\n" if nxt in "nN" else nxt)
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _parse_dt(value: str, params: str):
    """(date, is_date_only, has_time_after_midnight)."""
    v = value.strip()
    if "VALUE=DATE" in params.upper() and "DATE-TIME" not in params.upper() or len(v) == 8:
        return datetime.strptime(v[:8], "%Y%m%d").date(), True, False
    d = datetime.strptime(v[:8], "%Y%m%d").date()
    t = v[9:15] if len(v) >= 15 else "000000"
    return d, False, t != "000000"


def parse_ics(text: str) -> List[IcsEvent]:
    """A small, forgiving iCal reader: unfolds continuation lines, reads
    VEVENTs, understands DATE and DATE-TIME starts and multi-day ends, and
    skips anything it cannot read rather than failing the whole feed."""
    lines: List[str] = []
    for raw in re.split(r"\r\n|\n|\r", text):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)

    events: List[IcsEvent] = []
    cur: Optional[dict] = None
    for line in lines:
        if line == "BEGIN:VEVENT":
            cur = {}
            continue
        if line == "END:VEVENT":
            if cur is not None and "start" in cur:
                start = cur["start"]
                end = cur.get("end") or start + timedelta(days=1)
                if end <= start:
                    end = start + timedelta(days=1)
                end = min(end, start + timedelta(days=31))  # a runaway DTEND is not a month of holidays
                events.append(IcsEvent(
                    uid=cur.get("UID", ""), summary=cur.get("SUMMARY", "").strip(),
                    description=cur.get("DESCRIPTION", ""), start=start, end=end,
                ))
            cur = None
            continue
        if cur is None or ":" not in line:
            continue
        head, value = line.split(":", 1)
        name, _, params = head.partition(";")
        name = name.upper()
        try:
            if name == "DTSTART":
                cur["start"], cur["start_is_date"], _ = _parse_dt(value, params)
            elif name == "DTEND":
                d, is_date, has_time = _parse_dt(value, params)
                # A DATE end is exclusive; a DATE-TIME end at 00:00 is too, one
                # later in the day includes that day.
                cur["end"] = d if (is_date or not has_time) else d + timedelta(days=1)
            elif name in ("UID", "SUMMARY", "DESCRIPTION"):
                cur[name] = _unescape(value)
        except ValueError:
            continue
    return events


# ── Classifying ───────────────────────────────────────────────────────


@dataclass
class FeedHoliday:
    date: date
    title: str
    is_special: bool
    needs_review: bool
    is_tentative: bool
    region: Optional[str]
    region_label: str
    uid: str
    note: str


def _note_of(description: str, provider: str) -> str:
    """officeholidays descriptions are "<blurb>\\n\\n<note>\\n\\nInformation
    provided by ...". The note carries the type ("Regular holiday", "Special
    non-working day"), the region, or "Date to be confirmed". Reading the
    blurb instead would find "special" in ordinary prose."""
    paras = [p.strip() for p in description.split("\n\n")]
    if provider == "officeholidays":
        paras = [p for p in paras if not p.lower().startswith("information provided by")]
        return paras[1] if len(paras) >= 2 else ""
    return description.strip()


_NOT_A_PLACE = re.compile(
    r"holiday|non-working|\bday\b|in lieu|\d|monday|tuesday|wednesday|thursday|friday|"
    r"saturday|sunday|january|february|march|april|may|june|july|august|september|"
    r"october|november|december",
    re.I,
)


def _region_label(note: str) -> str:
    """A place name from the note ("Cebu. Special Non-Working..." -> "Cebu",
    "Manila only. For the..." -> "Manila"). Notes that are really a date rule
    ("First Friday of November") are not a place and give no label."""
    first = note.split(".")[0].strip()
    first = re.sub(r"\s+only$", "", first, flags=re.I)
    if not first or _NOT_A_PLACE.search(first):
        return ""
    return first[:80]


def classify(events: Iterable[IcsEvent], provider: str) -> List[FeedHoliday]:
    events = list(events)
    notes = {id(ev): _note_of(ev.description, provider) for ev in events}

    def type_text(ev) -> str:
        return (notes[id(ev)] if provider == "officeholidays" else f"{ev.summary}\n{notes[id(ev)]}").lower()

    # Regular vs special is a distinction some countries' law makes (the
    # Philippines pays them differently) and most do not. When the feed never
    # uses it, every holiday is simply a holiday: saved as regular, nothing to
    # review. When it does, a holiday it does not label is saved as regular
    # and flagged, because silently guessing either way can misstate pay.
    feed_classifies = any(
        "regular holiday" in type_text(ev) or "special" in type_text(ev) for ev in events
    )
    out: List[FeedHoliday] = []
    for ev in events:
        note = notes[id(ev)]
        text = type_text(ev)
        if "regular holiday" in text:
            is_special, needs_review = False, False
        elif "special" in text:
            is_special, needs_review = True, False
        else:
            is_special, needs_review = False, feed_classifies
        tentative = "to be confirmed" in (note + " " + ev.description).lower()

        title = ev.summary
        regional = False
        if provider == "officeholidays":
            title = re.sub(r"^[^:]{2,60}:\s+", "", title)  # "Philippines: Labor Day"
            regional = "(regional holiday)" in title.lower() or ev.uid.split("@")[0].endswith("region")
            title = re.sub(r"\s*\(Regional Holiday\)\s*$", "", title, flags=re.I)
        title = (title or "Holiday").strip()[:200]

        region, label = None, ""
        if regional:
            m = _REGION_RE.match(ev.uid)
            label = _region_label(note)
            if m:
                region = m.group(1)
            else:
                # Some regional holidays name no region ("Several states").
                slug = re.sub(r"[^a-z0-9]+", "-", (label or "unspecified").lower()).strip("-")
                region = f"other:{slug}"[:100]

        d = ev.start
        while d < ev.end:
            out.append(FeedHoliday(
                date=d, title=title, is_special=is_special, needs_review=needs_review,
                is_tentative=tentative, region=region, region_label=label, uid=ev.uid, note=note,
            ))
            d += timedelta(days=1)
    return out


def discover_regions(holidays: Iterable[FeedHoliday]) -> List[dict]:
    """The regions in the feed, for the region picker: code, a readable label
    (the most common one the feed used), how many holidays, and examples."""
    counts: Counter = Counter()
    labels: Dict[str, Counter] = defaultdict(Counter)
    samples: Dict[str, list] = defaultdict(list)
    for h in holidays:
        if not h.region:
            continue
        counts[h.region] += 1
        if h.region_label:
            labels[h.region][h.region_label] += 1
        if h.title not in samples[h.region] and len(samples[h.region]) < 3:
            samples[h.region].append(h.title)
    out = []
    for code, n in counts.items():
        label = labels[code].most_common(1)[0][0] if labels[code] else ""
        if not label:
            label = "Unspecified regions" if code.startswith("other:") else code
        out.append({"code": code, "label": label, "count": n, "samples": samples[code]})
    return sorted(out, key=lambda r: r["label"].lower())


def desired_by_date(holidays: Iterable[FeedHoliday], include_regions: Iterable[str]) -> Dict[date, dict]:
    """What the calendar should say per date. One row per date is allowed
    (uq_date_remark_tenant_date), so two feed holidays on a day are merged; a
    regular holiday on the day makes the day regular (it pays more)."""
    wanted = set(include_regions or [])
    by_date: Dict[date, list] = defaultdict(list)
    for h in holidays:
        if h.region and h.region not in wanted:
            continue
        by_date[h.date].append(h)
    out: Dict[date, dict] = {}
    for d, hs in by_date.items():
        titles = list(dict.fromkeys(h.title for h in hs))
        notes = list(dict.fromkeys(h.note for h in hs if h.note))
        national = [h for h in hs if not h.region]
        out[d] = {
            "date": d,
            "title": " / ".join(titles)[:200],
            "description": "; ".join(notes)[:2000] or None,
            "is_special": all(h.is_special for h in hs),
            "needs_review": any(h.needs_review for h in hs) and not any(
                not h.is_special and not h.needs_review for h in hs
            ),
            "is_tentative": any(h.is_tentative for h in hs),
            "region": None if national else ",".join(sorted({h.region for h in hs}))[:100],
            "external_uid": " ".join(sorted({h.uid for h in hs}))[:4000],
        }
    return out


# ── Syncing ───────────────────────────────────────────────────────────

_COMPARED = ("title", "description", "is_special", "needs_review", "is_tentative", "region", "external_uid")


def _item(d: dict, reason: Optional[str] = None, before: Optional[DateRemark] = None) -> dict:
    out = {
        "date": d["date"].isoformat(),
        "title": d["title"],
        "is_special": d["is_special"],
        "is_tentative": d["is_tentative"],
        "needs_review": d["needs_review"],
        "region": d["region"],
    }
    if reason:
        out["reason"] = reason
    if before is not None:
        out["before"] = {
            "title": before.title,
            "is_special": bool(before.is_special),
            "is_tentative": bool(before.is_tentative),
        }
    return out


def _row_item(r: DateRemark) -> dict:
    return {
        "date": r.date.isoformat(), "title": r.title, "is_special": bool(r.is_special),
        "is_tentative": bool(r.is_tentative), "needs_review": bool(r.needs_review), "region": r.region,
    }


async def apply_feed(
    db: AsyncSession,
    tenant_id: UUID,
    holidays: List[FeedHoliday],
    include_regions: Iterable[str],
    *,
    dry_run: bool,
    actor=None,
    today: Optional[date] = None,
) -> dict:
    """Merge parsed feed holidays into the tenant's calendar (or, with
    dry_run, only report what that would do)."""
    from app.services.schedule_service import ScheduleService

    today = today or date.today()
    desired = desired_by_date(holidays, include_regions)
    rows = {
        r.date: r for r in (await db.execute(
            select(DateRemark).where(DateRemark.tenant_id == tenant_id)
        )).scalars().all()
    }

    added, changed, skipped, removed, review = [], [], [], [], []
    to_add, to_change, to_remove = [], [], []
    for d in sorted(desired):
        want = desired[d]
        row = rows.get(d)
        if row is None:
            added.append(_item(want))
            to_add.append(want)
        elif row.is_suppressed:
            skipped.append(_item(want, "Deleted here earlier, so it is not added back."))
            continue
        elif row.source != "feed":
            skipped.append(_item(want, f"You already have \"{row.title}\" on this date; it is kept."))
            continue
        elif row.locally_modified:
            skipped.append(_item(want, "Edited here, so the feed does not overwrite it."))
            continue
        elif not row.is_holiday or any(getattr(row, k) != want[k] for k in _COMPARED):
            changed.append(_item(want, before=row))
            to_change.append((row, want))
        else:
            continue
        if want["needs_review"]:
            review.append(_item(want))

    feed_last = max(desired) if desired else None
    for d, row in sorted(rows.items()):
        if (
            row.source == "feed" and not row.is_suppressed and not row.locally_modified
            and row.is_holiday and d > today and feed_last is not None and d <= feed_last
            and d not in desired
        ):
            removed.append(_row_item(row))
            to_remove.append(row)

    result = {
        "dry_run": dry_run, "added": added, "changed": changed, "removed": removed,
        "skipped": skipped, "needs_review": review,
        "regions": discover_regions(holidays), "holiday_off_created": 0,
    }
    if dry_run:
        return result

    touched: set = set()
    for row in to_remove:
        await ScheduleService.remove_generated_holiday_off(db, tenant_id, row.id, None, actor)
        touched.add(row.date)
        await db.delete(row)
    for row, want in to_change:
        for k in _COMPARED:
            setattr(row, k, want[k])
        row.is_holiday = True
        touched.add(row.date)
    new_rows = []
    for want in to_add:
        row = DateRemark(
            tenant_id=tenant_id, date=want["date"], title=want["title"],
            description=want["description"], is_holiday=True, is_special=want["is_special"],
            is_recurring=False, source="feed", external_uid=want["external_uid"],
            is_tentative=want["is_tentative"], region=want["region"],
            needs_review=want["needs_review"],
        )
        db.add(row)
        new_rows.append(row)
        touched.add(row.date)
    await db.flush()

    for row in new_rows:
        result["holiday_off_created"] += await ScheduleService.apply_holiday_off(
            db, tenant_id, row, {row.date}, actor
        )
    await ScheduleService._emit_holiday_changed(db, tenant_id, actor, touched)
    return result


async def get_source(db: AsyncSession, tenant_id: UUID, *, lock: bool = False) -> Optional[HolidaySource]:
    stmt = select(HolidaySource).where(HolidaySource.tenant_id == tenant_id)
    if lock:
        stmt = stmt.with_for_update(skip_locked=True)
    return (await db.execute(stmt)).scalar_one_or_none()


async def fetch_holidays(source: HolidaySource) -> List[FeedHoliday]:
    # The private-network guard runs for every hop, officeholidays included:
    # its address is ours, but a redirect it answers with is not.
    text = await fetch_feed(feed_url_for(source))
    events = parse_ics(text)
    if not events:
        raise HolidayFeedError("The calendar has no holidays in it, so nothing was changed.")
    return classify(events, source.provider)


async def sync_tenant(
    db: AsyncSession,
    tenant_id: UUID,
    *,
    dry_run: bool = False,
    actor=None,
    holidays: Optional[List[FeedHoliday]] = None,
) -> dict:
    """Fetch the tenant's feed and apply it. Raises HolidayFeedError with a
    sentence for the admin. A dry run writes nothing at all, not even the
    status. `holidays` skips the fetch (tests, and a feed already read)."""
    source = await get_source(db, tenant_id)
    if source is None:
        raise HolidayFeedError("Set up a holiday calendar source first.")
    now = datetime.now(timezone.utc)
    try:
        if holidays is None:
            holidays = await fetch_holidays(source)
        result = await apply_feed(
            db, tenant_id, holidays, source.include_regions or [], dry_run=dry_run, actor=actor,
        )
    except HolidayFeedError as exc:
        if not dry_run:
            source.last_attempt_at = now
            source.last_status = "error"
            source.last_error = str(exc)
            await db.flush()
        raise
    if not dry_run:
        source.last_attempt_at = now
        source.last_synced_at = now
        source.last_status = "ok"
        source.last_error = None
        source.last_counts = {
            k: len(result[k]) for k in ("added", "changed", "removed", "skipped", "needs_review")
        }
        source.discovered_regions = result["regions"]
        await db.flush()
    return result


async def run_due(db: AsyncSession) -> dict:
    """Scheduler entry point: sync every tenant with auto_sync on whose last
    successful sync is over 24 hours old (a failing feed is retried hourly).

    Idempotent (a second sync of an unchanged feed changes nothing) and safe to
    call every minute from several workers: each source row is claimed with
    SKIP LOCKED. Never raises; failures are recorded on the source."""
    stats = {"due": 0, "synced": 0, "failed": 0}
    try:
        now = datetime.now(timezone.utc)
        sources = (await db.execute(
            select(HolidaySource.id, HolidaySource.tenant_id, HolidaySource.last_synced_at,
                   HolidaySource.last_attempt_at, HolidaySource.last_status,
                   ).where(HolidaySource.auto_sync == True)  # noqa: E712
        )).all()
        await db.rollback()

        def aware(t):
            return t if t is None or t.tzinfo else t.replace(tzinfo=timezone.utc)

        for sid, tenant_id, synced, attempted, last_status in sources:
            synced, attempted = aware(synced), aware(attempted)
            if synced and now - synced < SYNC_EVERY:
                continue
            if last_status == "error" and attempted and now - attempted < RETRY_AFTER_FAILURE:
                continue
            stats["due"] += 1
            try:
                claimed = await get_source(db, tenant_id, lock=True)
                if claimed is None:  # another worker has it
                    await db.rollback()
                    continue
                await sync_tenant(db, tenant_id)
                await db.commit()
                stats["synced"] += 1
            except Exception as exc:  # noqa: BLE001 - recorded, never raised
                await db.rollback()
                stats["failed"] += 1
                message = str(exc) if isinstance(exc, HolidayFeedError) else (
                    "The holiday sync failed unexpectedly; it will be retried in an hour."
                )
                if not isinstance(exc, HolidayFeedError):
                    logger.exception("holiday sync failed for tenant %s", tenant_id)
                try:
                    src = await get_source(db, tenant_id)
                    if src is not None:
                        src.last_attempt_at = now
                        src.last_status = "error"
                        src.last_error = message
                        await db.commit()
                except Exception:  # noqa: BLE001
                    await db.rollback()
    except Exception:  # noqa: BLE001
        logger.exception("holiday run_due failed")
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass
    return stats
