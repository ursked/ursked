import { ShiftStatus, WorkArrangement, ShiftStatusType } from '@/types';

// ── Status Labels ────────────────────────────────────────────────────

export const SHIFT_STATUS_LABELS: Record<string, string> = {
  scheduled: 'Scheduled',
  rest_day: 'Rest Day',
  sick_leave: 'Sick Leave',
  personal_leave: 'Personal Leave',
  emergency_leave: 'Emergency Leave',
  annual_vacation: 'Annual Vacation',
  holiday_off: 'Holiday Off',
  offset: 'Offset',
  bereavement_leave: 'Bereavement Leave',
  paternity_leave: 'Paternity Leave',
  maternity_leave: 'Maternity Leave',
  union_leave: 'Union Leave',
  fire_calamity_leave: 'Fire/Calamity Leave',
  solo_parent_leave: 'Solo Parent Leave',
  special_leave_women: 'Special Leave (Women)',
  vawc_leave: 'VAWC Leave',
  other: 'Other',
};

export const SHIFT_STATUS_SHORT: Record<string, string> = {
  scheduled: 'Sched',
  rest_day: 'Rest',
  sick_leave: 'SL',
  personal_leave: 'PL',
  emergency_leave: 'EL',
  annual_vacation: 'AV',
  holiday_off: 'HO',
  offset: 'OFF',
  bereavement_leave: 'BL',
  paternity_leave: 'PatL',
  maternity_leave: 'MatL',
  union_leave: 'UL',
  fire_calamity_leave: 'FCL',
  solo_parent_leave: 'SPL',
  special_leave_women: 'SLW',
  vawc_leave: 'VAWC',
  other: 'Oth',
};

// ── Status Colors ────────────────────────────────────────────────────

export const SHIFT_STATUS_COLORS: Record<string, string> = {
  scheduled: '#7c3aed',       // purple-600
  rest_day: '#6b7280',        // gray-500
  sick_leave: '#ef4444',      // red-500
  personal_leave: '#f59e0b',  // amber-500
  emergency_leave: '#dc2626', // red-600
  annual_vacation: '#3b82f6', // blue-500
  holiday_off: '#10b981',     // emerald-500
  offset: '#8b5cf6',          // violet-500
  bereavement_leave: '#374151', // gray-700
  paternity_leave: '#0ea5e9', // sky-500
  maternity_leave: '#ec4899', // pink-500
  union_leave: '#14b8a6',     // teal-500
  fire_calamity_leave: '#f97316', // orange-500
  solo_parent_leave: '#a855f7', // purple-500
  special_leave_women: '#d946ef', // fuchsia-500
  vawc_leave: '#e11d48',      // rose-600
  other: '#9ca3af',           // gray-400
};

export const SHIFT_STATUS_BG: Record<string, string> = {
  scheduled: 'bg-purple-100 text-purple-800',
  rest_day: 'bg-gray-100 text-gray-600',
  sick_leave: 'bg-red-100 text-red-800',
  personal_leave: 'bg-amber-100 text-amber-800',
  emergency_leave: 'bg-red-100 text-red-800',
  annual_vacation: 'bg-blue-100 text-blue-800',
  holiday_off: 'bg-emerald-100 text-emerald-800',
  offset: 'bg-violet-100 text-violet-800',
  bereavement_leave: 'bg-gray-200 text-gray-800',
  paternity_leave: 'bg-sky-100 text-sky-800',
  maternity_leave: 'bg-pink-100 text-pink-800',
  union_leave: 'bg-teal-100 text-teal-800',
  fire_calamity_leave: 'bg-orange-100 text-orange-800',
  solo_parent_leave: 'bg-purple-100 text-purple-800',
  special_leave_women: 'bg-fuchsia-100 text-fuchsia-800',
  vawc_leave: 'bg-rose-100 text-rose-800',
  other: 'bg-gray-100 text-gray-600',
};

// ── Work Arrangement Labels ──────────────────────────────────────────

export const WORK_ARRANGEMENT_LABELS: Record<string, string> = {
  wfh: 'WFH',
  onsite: 'On-site',
  hybrid: 'Hybrid',
  ob: 'OB',
};

export const WORK_ARRANGEMENT_BADGE: Record<string, string> = {
  wfh: 'bg-blue-50 text-blue-700',
  onsite: 'bg-green-50 text-green-700',
  hybrid: 'bg-amber-50 text-amber-700',
  ob: 'bg-purple-50 text-purple-700',
};

// ── All Status Options for Dropdowns ─────────────────────────────────

export const ALL_STATUSES: { value: ShiftStatus; label: string }[] = [
  { value: 'scheduled', label: 'Scheduled' },
  { value: 'rest_day', label: 'Rest Day' },
  { value: 'sick_leave', label: 'Sick Leave' },
  { value: 'personal_leave', label: 'Personal Leave' },
  { value: 'emergency_leave', label: 'Emergency Leave' },
  { value: 'annual_vacation', label: 'Annual Vacation' },
  { value: 'holiday_off', label: 'Holiday Off' },
  { value: 'offset', label: 'Offset' },
  { value: 'bereavement_leave', label: 'Bereavement Leave' },
  { value: 'paternity_leave', label: 'Paternity Leave' },
  { value: 'maternity_leave', label: 'Maternity Leave' },
  { value: 'union_leave', label: 'Union Leave' },
  { value: 'fire_calamity_leave', label: 'Fire/Calamity Leave' },
  { value: 'solo_parent_leave', label: 'Solo Parent Leave' },
  { value: 'special_leave_women', label: 'Special Leave (Women)' },
  { value: 'vawc_leave', label: 'VAWC Leave' },
  { value: 'other', label: 'Other' },
];

export const ALL_WORK_ARRANGEMENTS: { value: WorkArrangement; label: string }[] = [
  { value: 'onsite', label: 'On-site' },
  { value: 'wfh', label: 'Work From Home' },
  { value: 'hybrid', label: 'Hybrid' },
  { value: 'ob', label: 'Official Business' },
];

// ── Dynamic Status Maps (built from tenant's ShiftStatusType[]) ─────

export interface StatusMaps {
  labels: Record<string, string>;
  short: Record<string, string>;
  colors: Record<string, string>;
  bgClasses: Record<string, string>;
  categories: Record<string, string>;
  allStatuses: { value: string; label: string }[];
}

export function buildStatusMaps(types: ShiftStatusType[]): StatusMaps {
  const labels: Record<string, string> = {};
  const short: Record<string, string> = {};
  const colors: Record<string, string> = {};
  const bgClasses: Record<string, string> = {};
  const categories: Record<string, string> = {};
  const allStatuses: { value: string; label: string }[] = [];

  for (const t of types) {
    labels[t.code] = t.label;
    short[t.code] = t.short_label;
    colors[t.code] = t.color;
    bgClasses[t.code] = t.bg_class;
    categories[t.code] = t.category;
    allStatuses.push({ value: t.code, label: t.label });
  }

  return { labels, short, colors, bgClasses, categories, allStatuses };
}

// ── Date Helpers (timezone-safe) ─────────────────────────────────────

/** Format a Date to 'YYYY-MM-DD' using **local** year/month/day (NOT UTC). */
export function toLocalDateStr(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

// ── Utility Functions ────────────────────────────────────────────────

export function isLeaveStatus(status: string, dynamicCategories?: Record<string, string>): boolean {
  if (dynamicCategories) {
    const cat = dynamicCategories[status];
    return cat === 'leave' || cat === 'rest' || !cat;
  }
  return status.includes('leave') || status === 'rest_day' || status === 'holiday_off' || status === 'offset' || status === 'other';
}

export function isWorkStatus(status: string, dynamicCategories?: Record<string, string>): boolean {
  if (dynamicCategories) {
    return dynamicCategories[status] === 'work';
  }
  return status === 'scheduled';
}

export function isNonScheduledStatus(status: string): boolean {
  return status !== 'scheduled';
}

export function formatShiftTime(startTime?: string | null, endTime?: string | null): string {
  if (!startTime && !endTime) return '';
  const fmt = (t: string) => t.substring(0, 5); // "HH:MM:SS" → "HH:MM"
  if (startTime && endTime) return `${fmt(startTime)}-${fmt(endTime)}`;
  if (startTime) return fmt(startTime);
  if (endTime) return `–${fmt(endTime)}`;
  return '';
}

// ── Status resolution ────────────────────────────────────────────────
//
// One place decides how a status code is presented. Everything else in the
// grid reads through it.
//
// This exists because the three sources of truth had drifted: the backend
// writes a leave type's own code into Shift.status on approval, while the grid
// only knew the long-form codes ('sick_leave'), and the tenant's
// shift_status_types table only carried 'scheduled' and 'rest_day'. Both
// lookups missed and every approved leave silently fell back to grey with a
// four-character truncation of its code.
//
// Resolution order:
//   1. the tenant's own shift_status_types (authoritative, admin-editable)
//   2. the built-in constants (tenants seeded before the backfill migration)
//   3. an explicitly "unknown" presentation
//
// Step 3 is the important one. The old fallback was indistinguishable from a
// legitimately grey status, so a broken mapping looked like a working one. An
// unresolved code now renders as visibly unrecognised instead.

export const UNKNOWN_STATUS_COLOR = '#94a3b8'; // slate-400
export const UNKNOWN_STATUS_BG = 'bg-slate-100 text-slate-700';

export interface ResolvedStatus {
  code: string;
  label: string;
  short: string;
  color: string;
  bgClass: string;
  category: string;
  /** False when neither the tenant's types nor the built-ins knew this code. */
  known: boolean;
}

export function resolveStatus(status: string, maps?: StatusMaps): ResolvedStatus {
  const known =
    maps?.colors?.[status] !== undefined || SHIFT_STATUS_COLORS[status] !== undefined;

  return {
    code: status,
    label:
      maps?.labels?.[status] ??
      SHIFT_STATUS_LABELS[status] ??
      status.replace(/_/g, ' '),
    short:
      maps?.short?.[status] ??
      SHIFT_STATUS_SHORT[status] ??
      // Initialise a multi-word code ("study_leave" -> "SL") rather than
      // slicing it mid-word ("stud"), matching how the backend derives
      // short_label when it provisions a status type.
      (status.includes('_')
        ? status.split('_').map((w) => w[0]).join('').toUpperCase().slice(0, 4)
        : status.slice(0, 4)),
    color: maps?.colors?.[status] ?? SHIFT_STATUS_COLORS[status] ?? UNKNOWN_STATUS_COLOR,
    bgClass: maps?.bgClasses?.[status] ?? SHIFT_STATUS_BG[status] ?? UNKNOWN_STATUS_BG,
    // Unknown codes count as leave, matching the backend's stats fallback in
    // schedule_service.get_schedule_grid.
    category: maps?.categories?.[status] ?? 'leave',
    known,
  };
}

// The four accessors below are kept so existing call sites keep working, but
// they are now thin views over resolveStatus rather than independent lookups.
// Prefer resolveStatus directly when you need more than one field.

export function getStatusColor(status: string, dynamicColors?: Record<string, string>): string {
  return dynamicColors?.[status] ?? SHIFT_STATUS_COLORS[status] ?? UNKNOWN_STATUS_COLOR;
}

export function getStatusLabel(status: string, dynamicLabels?: Record<string, string>): string {
  return dynamicLabels?.[status] ?? SHIFT_STATUS_LABELS[status] ?? status.replace(/_/g, ' ');
}

export function getStatusShort(status: string, dynamicShort?: Record<string, string>): string {
  return resolveStatus(status, dynamicShort ? ({ short: dynamicShort } as StatusMaps) : undefined).short;
}

export function getStatusBgClass(status: string, dynamicBg?: Record<string, string>): string {
  return dynamicBg?.[status] ?? SHIFT_STATUS_BG[status] ?? UNKNOWN_STATUS_BG;
}
