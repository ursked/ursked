/**
 * Display-only timezone conversion for the schedule grid.
 *
 * Shifts are stored as naive wall-clock (date + "HH:MM") in the TENANT timezone,
 * which stays the source of truth for payroll/leave/guardrails. These helpers
 * convert ONLY what a viewer SEES to their chosen timezone. Nothing stored is
 * changed. If from/to tz match (or are missing), the input is returned as-is.
 */

/** Offset (minutes) of `tz` from UTC at the given UTC instant. */
function tzOffsetMinutes(tz: string, at: Date): number {
  // Format the instant in the target tz, read the wall-clock back, and diff.
  const dtf = new Intl.DateTimeFormat('en-US', {
    timeZone: tz,
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
    hour12: false,
  });
  const parts = dtf.formatToParts(at);
  const get = (t: string) => Number(parts.find((p) => p.type === t)?.value);
  let hour = get('hour');
  if (hour === 24) hour = 0; // some engines emit 24 for midnight
  const asUTC = Date.UTC(get('year'), get('month') - 1, get('day'), hour, get('minute'), get('second'));
  return Math.round((asUTC - at.getTime()) / 60000);
}

/** Interpret (dateStr, "HH:MM") as wall-clock in `fromTz` → the UTC instant. */
function wallTimeToInstant(dateStr: string, timeStr: string, fromTz: string): Date {
  const [y, m, d] = dateStr.split('-').map(Number);
  const [hh, mm] = timeStr.split(':').map(Number);
  // Start from the guess that the wall time is UTC, then correct by the tz
  // offset at that instant (DST-safe enough for schedule display).
  const guess = new Date(Date.UTC(y, m - 1, d, hh, mm));
  const off = tzOffsetMinutes(fromTz, guess);
  return new Date(guess.getTime() - off * 60000);
}

export interface ConvertedTime {
  time: string;      // "HH:MM" in the viewer tz
  dayShift: number;  // -1 / 0 / +1 if the local day rolled over
}

/**
 * Convert a shift's wall-clock time from the org tz to the viewer tz.
 * Returns null when there's nothing to convert (no time, or same tz).
 */
export function convertShiftTime(
  dateStr: string,
  timeStr: string | undefined | null,
  fromTz: string | undefined | null,
  toTz: string | undefined | null,
): ConvertedTime | null {
  if (!timeStr) return null;
  const from = fromTz || 'UTC';
  const to = toTz || from;
  if (from === to) return null;

  const instant = wallTimeToInstant(dateStr, timeStr.slice(0, 5), from);
  const dtf = new Intl.DateTimeFormat('en-US', {
    timeZone: to,
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hour12: false,
  });
  const parts = dtf.formatToParts(instant);
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? '';
  let hh = get('hour');
  if (hh === '24') hh = '00';
  const outTime = `${hh}:${get('minute')}`;

  // Did the calendar day change vs the original date?
  const [oy, om, od] = dateStr.split('-').map(Number);
  const outDay = Number(get('day'));
  const outMonth = Number(get('month'));
  const outYear = Number(get('year'));
  const origUTC = Date.UTC(oy, om - 1, od);
  const newUTC = Date.UTC(outYear, outMonth - 1, outDay);
  const dayShift = Math.round((newUTC - origUTC) / 86400000);

  return { time: outTime, dayShift };
}

/** A short, curated list of common IANA zones for the picker. */
export const COMMON_TIMEZONES: string[] = [
  'UTC',
  'Asia/Manila',
  'Asia/Singapore',
  'Asia/Tokyo',
  'Asia/Kolkata',
  'Asia/Dubai',
  'Australia/Sydney',
  'Europe/London',
  'Europe/Paris',
  'Europe/Berlin',
  'America/New_York',
  'America/Chicago',
  'America/Denver',
  'America/Los_Angeles',
];
