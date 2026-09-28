'use client';

import React, { Suspense, useState, useMemo, useCallback, useEffect } from 'react';
import dynamic from 'next/dynamic';
import { useSearchParams, useRouter } from 'next/navigation';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import DashboardLayout from '@/components/layout/DashboardLayout';
import { useAuth } from '@/contexts/AuthContext';
import { usePermissions } from '@/contexts/PermissionsContext';
import { api, isScheduleConflictError } from '@/lib/api';
import { ScheduleGrid, Shift, AppSettings, ShiftStatusType, UserPreferences, OrgTreeNode, ShiftActuals, ShiftBulkDeleteResult, PublishRangeResult, UnpublishRangeResult } from '@/types';
import { buildStatusMaps, requestableStatuses, toLocalDateStr } from './scheduleHelpers';
import { useToast } from '@/components/ui/Toast';
import { ErrorMessage } from '@/components/ui/ErrorBoundary';

export interface ClipboardShift {
  status: string;
  start_time?: string;
  end_time?: string;
  work_arrangement?: string;
  role_name?: string;
  color?: string;
  notes?: string;
  remarks?: string;
}

export interface SelectedCell {
  employeeId: number;
  dateStr: string;
  shift?: Shift;
}

import ScheduleToolbar, { ViewMode, RangeMode } from './ScheduleToolbar';
import StatsBar from './StatsBar';
import LinearGridView from './LinearGridView';
import CalendarView from './CalendarView';
import DayView from './DayView';
// Modals are only mounted once opened, so their code is fetched on demand
// rather than shipped in the page's initial bundle.
const ShiftModal = dynamic(() => import('./ShiftModal'));
const SwapRequestModal = dynamic(() => import('./SwapRequestModal'));
const ChangeRequestModal = dynamic(() => import('./ChangeRequestModal'));
import ScheduleRequestsPanel from './ScheduleRequestsPanel';
import SnapshotPanel from './SnapshotPanel';
import CopyWeekModal from './CopyWeekModal';
import TemplatesPanel from './TemplatesPanel';

const MONTH_NAMES = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

function getWeekStart(d: Date, startDay: 'monday' | 'sunday' | 'saturday' = 'monday'): Date {
  const day = d.getDay(); // 0=Sun, 1=Mon, ..., 6=Sat
  if (startDay === 'sunday') {
    const diff = d.getDate() - day;
    return new Date(d.getFullYear(), d.getMonth(), diff);
  }
  if (startDay === 'saturday') {
    // Saturday=0 offset: Sat=0, Sun=1, Mon=2, ..., Fri=6
    const offset = (day + 1) % 7;
    return new Date(d.getFullYear(), d.getMonth(), d.getDate() - offset);
  }
  // Monday-start
  const diff = d.getDate() - day + (day === 0 ? -6 : 1);
  return new Date(d.getFullYear(), d.getMonth(), diff);
}

function formatDate(d: Date): string {
  return toLocalDateStr(d);
}

function computeRange(
  anchor: Date,
  mode: RangeMode,
  weekStartDay: 'monday' | 'sunday' | 'saturday' = 'monday',
  customStart?: string,
  customEnd?: string,
): { start: Date; end: Date } {
  if (mode === 'custom' && customStart && customEnd) {
    return {
      start: new Date(customStart + 'T00:00:00'),
      end: new Date(customEnd + 'T00:00:00'),
    };
  }
  if (mode === 'month') {
    const start = new Date(anchor.getFullYear(), anchor.getMonth(), 1);
    const end = new Date(anchor.getFullYear(), anchor.getMonth() + 1, 0);
    return { start, end };
  }
  const weekStart = getWeekStart(anchor, weekStartDay);
  const days = mode === 'biweekly' ? 13 : 6;
  const end = new Date(weekStart.getFullYear(), weekStart.getMonth(), weekStart.getDate() + days);
  return { start: weekStart, end };
}

function buildDateLabel(start: Date, end: Date, mode: RangeMode): string {
  if (mode === 'month') {
    return `${MONTH_NAMES[start.getMonth()]} ${start.getFullYear()}`;
  }
  // For day-mode showing single date or any range
  if (start.getTime() === end.getTime()) {
    const dayNames = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    return `${dayNames[start.getDay()]}, ${MONTH_NAMES[start.getMonth()]} ${start.getDate()}, ${start.getFullYear()}`;
  }
  const startStr = `${MONTH_NAMES[start.getMonth()].substring(0, 3)} ${start.getDate()}`;
  const endStr = start.getMonth() === end.getMonth()
    ? `${end.getDate()}, ${end.getFullYear()}`
    : `${MONTH_NAMES[end.getMonth()].substring(0, 3)} ${end.getDate()}, ${end.getFullYear()}`;
  return `${startStr} – ${endStr}`;
}

export default function SchedulesPage() {
  return (
    <Suspense>
      <SchedulesPageInner />
    </Suspense>
  );
}

function SchedulesPageInner() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const router = useRouter();
  const { showToast } = useToast();
  // What the viewer may do is the permission matrix (the same module/action
  // the API checks); to whom is the row's can_manage flag from the grid. This
  // used to be a hard-coded role list, so unticking a box on the Permissions
  // screen changed nothing here either.
  const { hasPermission } = usePermissions();
  const canView = hasPermission('schedules', 'view');
  const canCreate = hasPermission('schedules', 'create');
  const canEditShifts = hasPermission('schedules', 'edit');
  const canDeleteShifts = hasPermission('schedules', 'delete');
  const canEdit = canCreate || canEditShifts || canDeleteShifts;

  // Fetch tenant settings (no staleTime — always refetch on mount so week-start changes take effect immediately)
  const { data: appSettings, isLoading: settingsLoading } = useQuery<AppSettings>({
    queryKey: ['app-settings'],
    queryFn: () => api.getAppSettings(),
  });

  const { data: statusTypes } = useQuery<ShiftStatusType[]>({
    queryKey: ['status-types'],
    queryFn: () => api.getStatusTypes(),
    staleTime: 60_000,
  });

  const { data: userPrefs } = useQuery<UserPreferences>({
    queryKey: ['user-preferences'],
    queryFn: () => api.getUserPreferences(),
    staleTime: 60_000,
  });

  const savedRowOrder = userPrefs?.preferences?.schedule_row_order ?? null;

  const saveRowOrderMutation = useMutation({
    mutationFn: (order: number[]) =>
      api.updateUserPreferences({ schedule_row_order: order }),
    onSuccess: () => {
      setCurrentRowOrder(null);
      queryClient.invalidateQueries({ queryKey: ['user-preferences'] });
    },
  });

  // Row order dirty tracking — set by LinearGridView on drag reorder
  const [currentRowOrder, setCurrentRowOrder] = useState<number[] | null>(null);
  const rowOrderDirty = currentRowOrder !== null;

  const handleSaveLayout = useCallback(() => {
    if (!currentRowOrder) return;
    saveRowOrderMutation.mutate(currentRowOrder);
  }, [currentRowOrder, saveRowOrderMutation]);

  const weekStartDay = appSettings?.week_starts_on ?? 'monday';
  const statusMaps = useMemo(
    () => (statusTypes ? buildStatusMaps(statusTypes) : undefined),
    [statusTypes],
  );

  // Overlay what actually happened (attendance, approved overtime) on top of
  // the plan. Off by default so the planning grid stays uncluttered.
  const [showActuals, setShowActuals] = useState(false);

  // Detect mobile for default view
  const [isMobile, setIsMobile] = useState(false);
  useEffect(() => {
    const check = () => setIsMobile(window.innerWidth < 768);
    check();
    window.addEventListener('resize', check);
    return () => window.removeEventListener('resize', check);
  }, []);

  // View state — initialized from URL query params (survive refresh)
  const [viewMode, setViewMode] = useState<ViewMode>(() => {
    const v = searchParams.get('view');
    if (v === 'linear' || v === 'calendar' || v === 'day') return v;
    return 'linear'; // will be overridden for mobile in useEffect below
  });
  const [rangeMode, setRangeMode] = useState<RangeMode>(() => {
    const r = searchParams.get('range');
    return r === 'week' || r === 'biweekly' || r === 'month' || r === 'custom' ? r : 'week';
  });
  const [currentDate, setCurrentDate] = useState<Date>(() => {
    const d = searchParams.get('date');
    if (d) {
      const parsed = new Date(d + 'T00:00:00');
      if (!isNaN(parsed.getTime())) return parsed;
    }
    return new Date();
  });
  const [search, setSearch] = useState('');
  const [orgNodeId, setOrgNodeId] = useState<number | null>(() => {
    const d = searchParams.get('node');
    const n = d ? Number(d) : NaN;
    return Number.isFinite(n) && n > 0 ? n : null;
  });

  // Custom range state
  const [customStartDate, setCustomStartDate] = useState<string>(() => {
    return searchParams.get('cs') ?? formatDate(new Date());
  });
  const [customEndDate, setCustomEndDate] = useState<string>(() => {
    const d = new Date();
    d.setDate(d.getDate() + 13);
    return searchParams.get('ce') ?? formatDate(d);
  });

  // Default to day view on mobile (only on initial load)
  const [mobileDefaultApplied, setMobileDefaultApplied] = useState(false);
  useEffect(() => {
    if (!(isMobile && !mobileDefaultApplied && !searchParams.get('view'))) return;
    let active = true;
    // Defer so the initial view-mode update does not run synchronously in the
    // effect body (react-hooks/set-state-in-effect).
    void Promise.resolve().then(() => {
      if (!active) return;
      setViewMode('day');
      setMobileDefaultApplied(true);
    });
    return () => {
      active = false;
    };
  }, [isMobile, mobileDefaultApplied, searchParams]);

  // Sync view state to URL (replace, not push, to avoid polluting history)
  useEffect(() => {
    const params = new URLSearchParams();
    params.set('date', formatDate(currentDate));
    params.set('range', rangeMode);
    params.set('view', viewMode);
    if (rangeMode === 'custom') {
      params.set('cs', customStartDate);
      params.set('ce', customEndDate);
    }
    if (orgNodeId) params.set('node', String(orgNodeId));
    router.replace(`/schedules?${params.toString()}`, { scroll: false });
  }, [currentDate, rangeMode, viewMode, customStartDate, customEndDate, orgNodeId, router]);

  // Clipboard state (copy/paste)
  const [clipboard, setClipboard] = useState<ClipboardShift | null>(null);
  const [selectedCell, setSelectedCell] = useState<SelectedCell | null>(null);

  // Modal state
  const [shiftModalOpen, setShiftModalOpen] = useState(false);
  const [editingShift, setEditingShift] = useState<Shift | null>(null);
  const [prefillEmployeeId, setPrefillEmployeeId] = useState<number | undefined>();
  const [prefillDate, setPrefillDate] = useState<string | undefined>();

  // Schedule request modals state
  const [swapModalOpen, setSwapModalOpen] = useState(false);
  const [changeModalOpen, setChangeModalOpen] = useState(false);
  const [requestTargetShift, setRequestTargetShift] = useState<Shift | null>(null);
  const [requestTargetDate, setRequestTargetDate] = useState<string>('');
  const [requestsPanelOpen, setRequestsPanelOpen] = useState(false);

  // Snapshot panel state
  const [snapshotPanelOpen, setSnapshotPanelOpen] = useState(false);

  // Copy-week modal state
  const [copyWeekOpen, setCopyWeekOpen] = useState(false);

  // Clear all confirmation state. The preview is the server's own count for
  // exactly the rows shown, so the confirmation states what the button does.
  const [clearAllConfirm, setClearAllConfirm] = useState(false);
  const [clearPreview, setClearPreview] = useState<ShiftBulkDeleteResult | null>(null);
  const [clearIncludeLeave, setClearIncludeLeave] = useState(false);
  // Publish confirmation, likewise counted by the server before anything changes.
  const [publishPreview, setPublishPreview] = useState<PublishRangeResult | null>(null);
  // Unpublish (return published shifts in view to draft), same pattern.
  const [unpublishPreview, setUnpublishPreview] = useState<UnpublishRangeResult | null>(null);
  const [templatesOpen, setTemplatesOpen] = useState(false);

  // Range calculation
  const { start, end } = useMemo(() => {
    if (viewMode === 'day') {
      // Fetch today + tomorrow for the "tomorrow preview" in day view
      const tomorrow = new Date(currentDate.getFullYear(), currentDate.getMonth(), currentDate.getDate() + 1);
      return { start: currentDate, end: tomorrow };
    }
    return computeRange(currentDate, rangeMode, weekStartDay, customStartDate, customEndDate);
  }, [currentDate, rangeMode, weekStartDay, viewMode, customStartDate, customEndDate]);

  const dateLabel = useMemo(() => {
    if (viewMode === 'day') {
      // Day view label should show only the current date, not the tomorrow range
      return buildDateLabel(currentDate, currentDate, 'week');
    }
    return buildDateLabel(start, end, rangeMode);
  }, [start, end, rangeMode, viewMode, currentDate]);

  // Navigation
  const navigate = useCallback(
    (direction: number) => {
      setCurrentDate((prev) => {
        if (viewMode === 'day') {
          return new Date(prev.getFullYear(), prev.getMonth(), prev.getDate() + direction);
        }
        if (rangeMode === 'custom') {
          // Shift by the range length
          const startD = new Date(customStartDate + 'T00:00:00');
          const endD = new Date(customEndDate + 'T00:00:00');
          const rangeDays = Math.max(1, Math.round((endD.getTime() - startD.getTime()) / (1000 * 60 * 60 * 24)) + 1);
          const newStart = new Date(startD.getTime() + direction * rangeDays * 24 * 60 * 60 * 1000);
          const newEnd = new Date(endD.getTime() + direction * rangeDays * 24 * 60 * 60 * 1000);
          setCustomStartDate(formatDate(newStart));
          setCustomEndDate(formatDate(newEnd));
          return newStart;
        }
        if (rangeMode === 'month') {
          return new Date(prev.getFullYear(), prev.getMonth() + direction, 1);
        }
        const days = rangeMode === 'biweekly' ? 14 : 7;
        return new Date(prev.getFullYear(), prev.getMonth(), prev.getDate() + direction * days);
      });
    },
    [rangeMode, viewMode, customStartDate, customEndDate],
  );

  // Data fetching
  const gridQueryParams = useMemo(
    () => ({
      start_date: formatDate(start),
      end_date: formatDate(end),
      ...(search ? { search } : {}),
      ...(orgNodeId ? { org_node_id: String(orgNodeId) } : {}),
      // Only ask for actuals when the toggle is on. The grid is a planning
      // view; attendance and overtime only exist for days already worked.
      ...(showActuals ? { include_actuals: 'true' } : {}),
    }),
    [start, end, search, orgNodeId, showActuals],
  );

  const { data: gridData, isLoading: gridLoading, isError: gridError, refetch: refetchGrid } = useQuery<ScheduleGrid>({
    queryKey: ['schedule-grid', gridQueryParams],
    queryFn: () => api.getScheduleGrid(gridQueryParams) as Promise<ScheduleGrid>,
    staleTime: 30_000,
    enabled: !settingsLoading, // Wait for settings so weekStartDay is correct before fetching
  });

  // Org tree for the "narrow the roster" filter. The grid endpoint filters
  // server-side by org_node_id (including the node's whole subtree), so picking
  // a Division/Department/Section trims the visible rows to that unit.
  const actualsMap = useMemo(() => {
    const m = new Map<string, ShiftActuals>();
    for (const a of gridData?.actuals ?? []) m.set(`${a.employee_id}:${a.date}`, a);
    return m;
  }, [gridData]);

  // Work sites for the shift modal's site picker (the time clock geofence).
  const { data: workSites } = useQuery({
    queryKey: ['work-sites'],
    queryFn: () => api.listWorkSites(),
    enabled: shiftModalOpen,
    staleTime: 5 * 60_000,
  });

  const { data: orgTree } = useQuery({
    queryKey: ['org-tree'],
    queryFn: () => api.getOrgTree(),
    staleTime: 5 * 60_000,
  });
  // The nodes THIS user may actually view (mirrors their real schedule
  // visibility: role scope + per-node override + secondary assignments + grants).
  // Used to restrict the picker so a non-admin only sees choosable units, with a
  // live count of the people they can see in each.
  const { data: accessible } = useQuery({
    queryKey: ['accessible-nodes'],
    queryFn: () => api.getAccessibleNodes(),
    staleTime: 5 * 60_000,
  });
  const orgNodeOptions = useMemo(() => {
    const counts = new Map<number, number>();
    for (const n of accessible?.nodes ?? []) counts.set(n.id, n.visible_member_count);
    // Admins ("can_see_all") get the full tree; everyone else is restricted to
    // the nodes they can view.
    const restrict = accessible ? !accessible.can_see_all : false;

    const out: { id: number; label: string; depth: number }[] = [];
    const walk = (nodes: OrgTreeNode[], depth: number) => {
      for (const n of nodes) {
        // Skip the top-level company node — it covers everyone (= "All").
        if (depth === 0 && (!n.parent_id)) {
          walk(n.children ?? [], depth); // descend without adding the root
          continue;
        }
        const visible = !restrict || counts.has(n.id);
        if (visible) {
          const count = counts.get(n.id);
          const label = count != null ? `${n.name} (${count})` : n.name;
          out.push({ id: n.id, label, depth });
        }
        if (n.children?.length) walk(n.children, depth + 1);
      }
    };
    walk(orgTree?.nodes ?? [], 0);
    return out;
  }, [orgTree, accessible]);

  // Guardrail lint for the rows on screen → inline cell warnings. It sends
  // the ids shown, so a filtered view is linted as filtered (it used to lint
  // the whole company and count warnings for people not on screen).
  const shownIds = useMemo(() => (gridData?.employees ?? []).map((e) => e.employee_id), [gridData]);
  const { data: lintData } = useQuery({
    queryKey: ['schedule-lint', formatDate(start), formatDate(end), shownIds.join(',')],
    queryFn: () => api.lintSchedule({
      start_date: formatDate(start),
      end_date: formatDate(end),
      employee_ids: shownIds,
    }),
    enabled: canView && !settingsLoading && !!gridData,
    staleTime: 30_000,
  });
  // Map employee_id → date → violation messages.
  const violationMap = useMemo(() => {
    const m = new Map<number, Map<string, string[]>>();
    for (const v of lintData?.violations ?? []) {
      if (!m.has(v.employee_id)) m.set(v.employee_id, new Map());
      const byDate = m.get(v.employee_id)!;
      byDate.set(v.date, [...(byDate.get(v.date) ?? []), v.message]);
    }
    return m;
  }, [lintData]);
  const violationCount = lintData?.violations?.length ?? 0;

  const isLoading = settingsLoading || gridLoading;

  // Memoized so the array reference is stable across renders (its identity feeds
  // a useMemo below) — react-hooks/exhaustive-deps.
  const employees = useMemo(() => gridData?.employees ?? [], [gridData]);
  const dates = gridData?.dates ?? [];
  const dateRemarks = gridData?.date_remarks ?? [];
  const stats = gridData?.stats ?? {
    total_shifts: 0,
    total_employees: 0,
    scheduled_count: 0,
    leave_count: 0,
    rest_day_count: 0,
  };
  // The rows the viewer may change. Every bulk action (clear, publish, copy
  // week, snapshot) sends exactly these ids; the backend never widens an
  // absent or empty list to the whole company any more.
  const manageableIds = useMemo(
    () => employees.filter((e) => e.can_manage !== false).map((e) => e.employee_id),
    [employees],
  );
  const manageable = useMemo(() => new Set(manageableIds), [manageableIds]);
  const canManage = useCallback((employeeId: number) => manageable.has(employeeId), [manageable]);

  // Day view also loads tomorrow for its preview; actions apply to the day shown.
  const actionStart = formatDate(viewMode === 'day' ? currentDate : start);
  const actionEnd = formatDate(viewMode === 'day' ? currentDate : end);

  // Draft (unpublished) shifts in the current view that Publish would release.
  const draftCount = useMemo(
    () => employees.filter((e) => manageable.has(e.employee_id)).reduce(
      (acc, e) => acc + e.shifts.filter(
        (s) => s.is_published === false && s.date >= actionStart && s.date <= actionEnd,
      ).length,
      0,
    ),
    [employees, manageable, actionStart, actionEnd],
  );

  // Shared post-mutation handler: refetch grid + reset UI state
  const onMutationSuccess = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['schedule-grid'] });
    setShiftModalOpen(false);
    setEditingShift(null);
    setSelectedCell(null);
  }, [queryClient]);

  // Mutations
  const createShiftMutation = useMutation({
    mutationFn: (data: Record<string, unknown>) => api.createShift(data),
    onSuccess: onMutationSuccess,
  });

  const updateShiftMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Record<string, unknown> }) =>
      api.updateShift(id, data),
    onSuccess: onMutationSuccess,
  });

  const deleteShiftMutation = useMutation({
    mutationFn: (id: number) => api.deleteShift(id),
    onSuccess: onMutationSuccess,
  });

  // Clear all shifts in view: first ask the server what it would delete for
  // exactly the rows shown, then delete that.
  const clearPreviewMutation = useMutation({
    mutationFn: () => api.bulkDeleteShifts({
      start_date: actionStart,
      end_date: actionEnd,
      employee_ids: manageableIds,
      dry_run: true,
    }),
    onSuccess: (data) => setClearPreview(data),
    onError: (err: Error) => {
      setClearAllConfirm(false);
      showToast(err.message, 'error');
    },
  });

  const bulkDeleteMutation = useMutation({
    mutationFn: () => api.bulkDeleteShifts({
      start_date: actionStart,
      end_date: actionEnd,
      employee_ids: manageableIds,
      include_leave: clearIncludeLeave,
    }),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['schedule-grid'] });
      setClearAllConfirm(false);
      setClearPreview(null);
      setClearIncludeLeave(false);
      const kept = data.leave_kept_count
        ? ` · ${data.leave_kept_count} approved-leave day${data.leave_kept_count !== 1 ? 's' : ''} kept`
        : '';
      showToast(`${data.deleted_count} shift${data.deleted_count !== 1 ? 's' : ''} cleared${kept}`, 'success');
    },
    onError: (err: Error) => showToast(err.message, 'error'),
  });

  const openClearAll = () => {
    setClearAllConfirm(true);
    setClearPreview(null);
    setClearIncludeLeave(false);
    clearPreviewMutation.mutate();
  };

  // Publish the drafts of exactly the rows shown. The confirmation carries the
  // server's own count, so the banner, the dialog and the result agree.
  const publishBody = { start_date: actionStart, end_date: actionEnd, employee_ids: manageableIds };
  const publishPreviewMutation = useMutation({
    mutationFn: () => api.publishSchedule({ ...publishBody, dry_run: true }),
    onSuccess: (res) => setPublishPreview(res),
    onError: (err: Error) => showToast(err.message, 'error'),
  });
  // Unpublish: take the published shifts of the rows shown back to draft so
  // they can be reworked. The employees are told their schedule was withdrawn.
  const unpublishPreviewMutation = useMutation({
    mutationFn: () => api.unpublishSchedule({ ...publishBody, dry_run: true }),
    onSuccess: (res) => setUnpublishPreview(res),
    onError: (err: Error) => showToast(err.message, 'error'),
  });
  const unpublishMutation = useMutation({
    mutationFn: () => api.unpublishSchedule(publishBody),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ['schedule-grid'] });
      setUnpublishPreview(null);
      showToast(
        `${res.unpublished_count} shift${res.unpublished_count !== 1 ? 's' : ''} back to draft` +
        (res.notified ? ` · ${res.notified} employee${res.notified !== 1 ? 's' : ''} notified` : ''),
        'success',
      );
    },
    onError: (err: Error) => showToast(err.message, 'error'),
  });

  const publishMutation = useMutation({
    mutationFn: () => api.publishSchedule(publishBody),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ['schedule-grid'] });
      setPublishPreview(null);
      showToast(
        `Published ${res.published_count} shift${res.published_count !== 1 ? 's' : ''}` +
        (res.notified ? ` · ${res.notified} employee${res.notified !== 1 ? 's' : ''} notified` : ''),
        'success',
      );
    },
    onError: (err: Error) => showToast(err.message, 'error'),
  });

  // Handlers
  const handleAddShift = () => {
    setEditingShift(null);
    setPrefillEmployeeId(undefined);
    setPrefillDate(undefined);
    setShiftModalOpen(true);
  };

  const handleShiftClick = (shift: Shift) => {
    if ((canEditShifts || canDeleteShifts) && canManage(shift.employee_id)) {
      setEditingShift(shift);
      setPrefillEmployeeId(undefined);
      setPrefillDate(undefined);
      setShiftModalOpen(true);
    }
  };

  const handleSwapRequest = useCallback((shift: Shift) => {
    setRequestTargetShift(shift);
    setRequestTargetDate(shift.date);
    setSwapModalOpen(true);
  }, []);

  const handleChangeRequest = useCallback((shift: Shift) => {
    setRequestTargetShift(shift);
    setRequestTargetDate(shift.date);
    setChangeModalOpen(true);
  }, []);

  const handleCellClick = (employeeId: number, dateStr: string) => {
    if (!canCreate || (employeeId && !canManage(employeeId))) return;
    setEditingShift(null);
    setPrefillEmployeeId(employeeId);
    setPrefillDate(dateStr);
    setShiftModalOpen(true);
  };

  const handleCalendarAddShift = (dateStr: string) => {
    setEditingShift(null);
    setPrefillEmployeeId(undefined);
    setPrefillDate(dateStr);
    setShiftModalOpen(true);
  };

  const handleSave = async (data: Record<string, unknown>) => {
    if (editingShift) {
      await updateShiftMutation.mutateAsync({ id: editingShift.id, data });
    } else {
      await createShiftMutation.mutateAsync(data);
    }
  };

  const handleDelete = async () => {
    if (editingShift) {
      await deleteShiftMutation.mutateAsync(editingShift.id);
    }
  };

  // Copy/paste handlers
  const handleCopyShift = useCallback((shift: Shift) => {
    setClipboard({
      status: shift.status,
      start_time: shift.start_time,
      end_time: shift.end_time,
      work_arrangement: shift.work_arrangement,
      role_name: shift.role_name,
      color: shift.color,
      notes: shift.notes,
      remarks: shift.remarks,
    });
  }, []);

  // Paste and drag have no modal to show a refusal in, and a paste that hit
  // approved leave used to fail with no message at all. A refusal is now said
  // out loud; when every reason is a guardrail the editor may override (as the
  // modal's "Schedule Anyway" allows), they are asked whether to go ahead.
  const handleQuickWriteError = useCallback(
    (err: unknown, verb: string, retry: () => void) => {
      if (isScheduleConflictError(err)) {
        const conflicts = err.detail.conflicts;
        const lines = conflicts.map((c) => c.message).join('\n');
        if (conflicts.length > 0 && conflicts.every((c) => c.forceable)) {
          if (window.confirm(`${lines}\n\n${verb} anyway?`)) retry();
          return;
        }
        showToast(lines || err.message, 'error');
        return;
      }
      showToast(err instanceof Error ? err.message : `Could not ${verb.toLowerCase()} the shift`, 'error');
    },
    [showToast],
  );

  const handlePasteShift = useCallback(
    (employeeId: number, dateStr: string) => {
      if (!clipboard || !canCreate || !canManage(employeeId)) return;
      // Clear selection immediately for visual feedback
      setSelectedCell(null);
      const body = { employee_id: employeeId, date: dateStr, ...clipboard };
      createShiftMutation.mutate(body, {
        onError: (err) => handleQuickWriteError(err, 'Paste', () =>
          createShiftMutation.mutate({ ...body, force: true }, {
            onError: (e) => handleQuickWriteError(e, 'Paste', () => {}),
          })),
      });
    },
    [clipboard, canCreate, canManage, createShiftMutation, handleQuickWriteError],
  );

  const handleCellSelect = useCallback((employeeId: number, dateStr: string, shift?: Shift) => {
    setSelectedCell({ employeeId, dateStr, shift });
  }, []);

  const handleClearClipboard = useCallback(() => {
    setClipboard(null);
  }, []);

  // Drag-and-drop move handler
  const handleMoveShift = useCallback(
    (shiftId: number, targetEmployeeId: number, targetDateStr: string) => {
      if (!canEditShifts || !canManage(targetEmployeeId)) return;
      const data = { employee_id: targetEmployeeId, date: targetDateStr };
      updateShiftMutation.mutate({ id: shiftId, data }, {
        onError: (err) => handleQuickWriteError(err, 'Move', () =>
          updateShiftMutation.mutate({ id: shiftId, data: { ...data, force: true } }, {
            onError: (e) => handleQuickWriteError(e, 'Move', () => {}),
          })),
      });
    },
    [canEditShifts, canManage, updateShiftMutation, handleQuickWriteError],
  );

  // Keyboard shortcuts for copy/paste
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'c' && selectedCell?.shift) {
        e.preventDefault();
        handleCopyShift(selectedCell.shift);
      }
      if ((e.ctrlKey || e.metaKey) && e.key === 'v' && clipboard && selectedCell) {
        e.preventDefault();
        handlePasteShift(selectedCell.employeeId, selectedCell.dateStr);
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [selectedCell, clipboard, handleCopyShift, handlePasteShift]);

  const handleExport = async () => {
    try {
      const blob = await api.exportSchedule({
        start_date: formatDate(start),
        end_date: formatDate(end),
      });
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `schedule_${formatDate(start)}_${formatDate(end)}.csv`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
    } catch {
      // Export failed silently
    }
  };

  const handleExportXlsx = async () => {
    try {
      const blob = await api.exportScheduleXlsx({
        start_date: formatDate(start),
        end_date: formatDate(end),
      });
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `work-schedule-${formatDate(start)}-${formatDate(end)}.xlsx`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
    } catch {
      showToast('Export failed', 'error');
    }
  };

  const handleCustomRangeChange = useCallback((s: string, e: string) => {
    if (s) setCustomStartDate(s);
    if (e) setCustomEndDate(e);
  }, []);

  return (
    <DashboardLayout>
      <div className="space-y-4">
        {/* Page header */}
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Schedule</h1>
          <p className="text-sm text-gray-500 mt-0.5">Manage employee shifts and schedules</p>
        </div>

        {/* Toolbar */}
        <ScheduleToolbar
          showActuals={showActuals}
          onShowActualsChange={canView ? setShowActuals : undefined}
          viewMode={viewMode}
          onViewModeChange={setViewMode}
          rangeMode={rangeMode}
          onRangeModeChange={setRangeMode}
          currentDate={currentDate}
          onPrev={() => navigate(-1)}
          onNext={() => navigate(1)}
          onToday={() => setCurrentDate(new Date())}
          dateLabel={dateLabel}
          search={search}
          onSearchChange={setSearch}
          orgNodes={orgNodeOptions}
          orgNodeId={orgNodeId}
          onOrgNodeChange={setOrgNodeId}
          onAddShift={handleAddShift}
          onExport={handleExport}
          // The workbook covers the whole company, so only for people who see everyone.
          onExportXlsx={canView && accessible?.can_see_all ? handleExportXlsx : undefined}
          canEdit={canEdit}
          canAddShift={canCreate && manageableIds.length > 0}
          canExport={canView}
          clipboard={clipboard}
          onClearClipboard={handleClearClipboard}
          rowOrderDirty={rowOrderDirty}
          onSaveLayout={handleSaveLayout}
          savingLayout={saveRowOrderMutation.isPending}
          onOpenRequests={() => setRequestsPanelOpen(true)}
          customStartDate={customStartDate}
          customEndDate={customEndDate}
          onCustomRangeChange={handleCustomRangeChange}
          onOpenSnapshots={canEditShifts ? () => setSnapshotPanelOpen(true) : undefined}
          onCopyWeek={canCreate && manageableIds.length > 0 ? () => setCopyWeekOpen(true) : undefined}
          onClearAll={canDeleteShifts && manageableIds.length > 0 ? openClearAll : undefined}
          onOpenTemplates={canCreate && manageableIds.length > 0 ? () => setTemplatesOpen(true) : undefined}
          onUnpublish={canEditShifts && manageableIds.length > 0 ? () => unpublishPreviewMutation.mutate() : undefined}
        />

        {/* Stats bar */}
        <StatsBar stats={stats} loading={isLoading} />

        {/* Guardrail warnings summary */}
        {canView && violationCount > 0 && (
          <div className="flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-4 py-2 text-xs text-amber-700">
            <svg className="h-4 w-4 shrink-0" viewBox="0 0 24 24" fill="currentColor">
              <path d="M12 2L1 21h22L12 2zm0 6l7.53 13H4.47L12 8zm-1 3v4h2v-4h-2zm0 5v2h2v-2h-2z" />
            </svg>
            <span>
              <span className="font-semibold">{violationCount}</span> guardrail warning{violationCount !== 1 ? 's' : ''} in this range — tap or hover the amber marks on the grid for details.
            </span>
          </div>
        )}

        {/* Draft / publish banner */}
        {canEditShifts && draftCount > 0 && (
          <div className="rounded-lg border border-purple-200 bg-purple-50 px-4 py-2.5">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2 text-xs text-purple-800">
                <svg className="h-4 w-4 shrink-0" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                </svg>
                <span>
                  <span className="font-semibold">{draftCount}</span> draft shift{draftCount !== 1 ? 's' : ''} for the employees shown are hidden from them until published.
                </span>
              </div>
              {!publishPreview && (
                <button
                  onClick={() => publishPreviewMutation.mutate()}
                  disabled={publishPreviewMutation.isPending}
                  className="rounded-md bg-purple-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-purple-700 disabled:opacity-50"
                >
                  {publishPreviewMutation.isPending ? 'Checking…' : `Publish ${draftCount} shift${draftCount !== 1 ? 's' : ''}…`}
                </button>
              )}
            </div>
            {publishPreview && (
              <div className="mt-2 flex flex-wrap items-center justify-between gap-2 border-t border-purple-200 pt-2">
                <p className="text-xs text-purple-900">
                  {publishPreview.published_count === 0
                    ? 'Nothing left to publish for the employees shown.'
                    : `Publish ${publishPreview.published_count} shift${publishPreview.published_count !== 1 ? 's' : ''} for ${publishPreview.employee_count} employee${publishPreview.employee_count !== 1 ? 's' : ''} (${actionStart} to ${actionEnd})? Each of them is notified.`}
                </p>
                <div className="flex gap-2">
                  <button
                    onClick={() => setPublishPreview(null)}
                    className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={() => publishMutation.mutate()}
                    disabled={publishMutation.isPending || publishPreview.published_count === 0}
                    className="rounded-md bg-purple-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-purple-700 disabled:opacity-50"
                  >
                    {publishMutation.isPending ? 'Publishing…' : 'Publish and notify'}
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Unpublish confirmation, with the server's own count. */}
        {unpublishPreview && (
          <div className="rounded-xl border border-amber-200 bg-amber-50 px-5 py-4 flex flex-wrap items-center justify-between gap-3">
            <div className="min-w-0">
              <p className="text-sm font-medium text-amber-900">Unpublish the shifts in current view?</p>
              <p className="text-xs text-amber-800 mt-0.5">
                {unpublishPreview.unpublished_count === 0
                  ? 'Nothing published here for the employees shown.'
                  : `${unpublishPreview.unpublished_count} published shift${unpublishPreview.unpublished_count !== 1 ? 's' : ''} for ${unpublishPreview.employee_count} employee${unpublishPreview.employee_count !== 1 ? 's' : ''} (${actionStart} to ${actionEnd}) go back to draft and disappear from their schedule until you publish again. They are told. Approved leave stays visible.`}
              </p>
            </div>
            <div className="flex items-center gap-2 flex-shrink-0">
              <button
                onClick={() => setUnpublishPreview(null)}
                className="px-3 py-1.5 text-xs font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={() => unpublishMutation.mutate()}
                disabled={unpublishMutation.isPending || unpublishPreview.unpublished_count === 0}
                className="px-3 py-1.5 text-xs font-medium text-white bg-amber-600 rounded-lg hover:bg-amber-700 disabled:opacity-50"
              >
                {unpublishMutation.isPending ? 'Unpublishing…' : 'Unpublish and notify'}
              </button>
            </div>
          </div>
        )}

        {/* Clear all confirmation banner. The numbers come from the server's
            dry run for exactly the rows shown, so they are what will happen. */}
        {clearAllConfirm && (
          <div className="bg-red-50 border border-red-200 rounded-xl px-5 py-4 flex flex-wrap items-center justify-between gap-3">
            <div className="min-w-0">
              <p className="text-sm font-medium text-red-800">Clear all shifts in current view?</p>
              {!clearPreview ? (
                <p className="text-xs text-red-600 mt-0.5">Counting the shifts that would be deleted…</p>
              ) : (
                <>
                  <p className="text-xs text-red-600 mt-0.5">
                    This permanently deletes {clearPreview.deleted_count + (clearIncludeLeave ? clearPreview.leave_kept_count : 0)} shift
                    {clearPreview.deleted_count + (clearIncludeLeave ? clearPreview.leave_kept_count : 0) !== 1 ? 's' : ''} from {actionStart} to {actionEnd} for
                    the {manageableIds.length} employee{manageableIds.length !== 1 ? 's' : ''} shown{manageableIds.length < employees.length ? ' that you manage' : ''}. Nobody else is affected.
                  </p>
                  {clearPreview.leave_kept_count > 0 && (
                    <label className="mt-1.5 flex items-center gap-2 text-xs text-red-700">
                      <input
                        type="checkbox"
                        checked={clearIncludeLeave}
                        onChange={(e) => setClearIncludeLeave(e.target.checked)}
                        className="rounded border-red-300 text-red-600 focus:ring-red-500"
                      />
                      {clearIncludeLeave
                        ? `Also deleting ${clearPreview.leave_kept_count} approved-leave day${clearPreview.leave_kept_count !== 1 ? 's' : ''}. The leave requests stay approved.`
                        : `${clearPreview.leave_kept_count} approved-leave day${clearPreview.leave_kept_count !== 1 ? 's are' : ' is'} kept. Tick to delete them too.`}
                    </label>
                  )}
                </>
              )}
            </div>
            <div className="flex items-center gap-2 flex-shrink-0">
              <button
                onClick={() => { setClearAllConfirm(false); setClearPreview(null); }}
                className="px-3 py-1.5 text-xs font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => bulkDeleteMutation.mutate()}
                disabled={
                  bulkDeleteMutation.isPending || !clearPreview ||
                  clearPreview.deleted_count + (clearIncludeLeave ? clearPreview.leave_kept_count : 0) === 0
                }
                className="px-3 py-1.5 text-xs font-medium text-white bg-red-600 rounded-lg hover:bg-red-700 disabled:opacity-50 transition-colors flex items-center gap-1.5"
              >
                {bulkDeleteMutation.isPending ? (
                  <>
                    <div className="w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                    Clearing...
                  </>
                ) : (
                  'Yes, Clear All'
                )}
              </button>
            </div>
          </div>
        )}

        {/* Loading skeleton */}
        {isLoading && (
          <div className="bg-white rounded-xl border border-gray-200 p-12 flex items-center justify-center">
            <div className="text-center">
              <div className="w-10 h-10 border-4 border-purple-200 border-t-purple-600 rounded-full animate-spin mx-auto mb-3" />
              <p className="text-sm text-gray-500">Loading schedule...</p>
            </div>
          </div>
        )}

        {/* A failed grid fetch used to render an empty roster under a stats bar
            reading 0 employees / 0 shifts — indistinguishable from a genuinely
            blank week, on the screen people use to decide who is working. */}
        {!isLoading && gridError && (
          <div className="bg-white rounded-xl border border-gray-200 p-6">
            <ErrorMessage
              message="Could not load the schedule. The counts above are not real — nothing was returned for this range."
              onRetry={() => refetchGrid()}
            />
          </div>
        )}

        {/* Day View */}
        {!isLoading && !gridError && viewMode === 'day' && (
          <DayView
            employees={employees}
            dates={dates}
            dateRemarks={dateRemarks}
            onShiftClick={handleShiftClick}
            onCellClick={handleCellClick}
            canEdit={canCreate}
            statusMaps={statusMaps}
            currentUserId={user?.id}
            onSwapRequest={handleSwapRequest}
            onChangeRequest={handleChangeRequest}
          />
        )}

        {/* Grid / Calendar */}
        {!isLoading && !gridError && viewMode === 'linear' && (
          <LinearGridView
            employees={employees}
            dates={dates}
            dateRemarks={dateRemarks}
            violationMap={violationMap}
            onShiftClick={handleShiftClick}
            onCellClick={handleCellClick}
            selectedCell={selectedCell}
            clipboard={clipboard}
            onCellSelect={handleCellSelect}
            onCopyShift={handleCopyShift}
            onPasteShift={handlePasteShift}
            onMoveShift={canEditShifts ? handleMoveShift : undefined}
            savedRowOrder={savedRowOrder}
            onRowOrderChange={setCurrentRowOrder}
            canEdit={canCreate}
            canEditEmployee={canManage}
            currentUserId={user?.id}
            onSwapRequest={handleSwapRequest}
            onChangeRequest={handleChangeRequest}
            statusMaps={statusMaps}
            actualsMap={actualsMap}
          />
        )}

        {!isLoading && !gridError && viewMode === 'calendar' && (
          <CalendarView
            employees={employees}
            dates={dates}
            dateRemarks={dateRemarks}
            currentDate={currentDate}
            onShiftClick={handleShiftClick}
            onAddShift={handleCalendarAddShift}
            canEdit={canCreate}
            weekStartDay={weekStartDay}
            statusTypes={statusTypes}
            statusMaps={statusMaps}
            currentUserId={user?.id}
            onSwapRequest={handleSwapRequest}
            onChangeRequest={handleChangeRequest}
          />
        )}
      </div>

      {/* Shift Modal */}
      <ShiftModal
        isOpen={shiftModalOpen}
        onClose={() => setShiftModalOpen(false)}
        onSave={handleSave}
        onDelete={editingShift && canDeleteShifts ? handleDelete : undefined}
        shift={editingShift}
        employees={employees.filter((e) => manageable.has(e.employee_id))}
        prefillEmployeeId={prefillEmployeeId}
        prefillDate={prefillDate}
        statusOptions={statusMaps?.allStatuses}
        statusCategories={statusMaps?.categories}
        workSites={workSites}
        onBulkSave={async (data) => {
          const result = await api.bulkCreateShifts(data);
          // Always refresh the grid so created shifts show immediately.
          queryClient.invalidateQueries({ queryKey: ['schedule-grid'] });
          // Only close when nothing was skipped; otherwise the modal keeps
          // itself open to report the skipped dates.
          if (!result.skipped_conflicts?.length) {
            onMutationSuccess();
          }
          return result;
        }}
      />

      {/* Swap Request Modal */}
      {requestTargetShift && (
        <SwapRequestModal
          isOpen={swapModalOpen}
          onClose={() => { setSwapModalOpen(false); setRequestTargetShift(null); }}
          shift={requestTargetShift}
          dateStr={requestTargetDate}
          employees={employees}
        />
      )}

      {/* Change Request Modal */}
      {requestTargetShift && (
        <ChangeRequestModal
          isOpen={changeModalOpen}
          onClose={() => { setChangeModalOpen(false); setRequestTargetShift(null); }}
          shift={requestTargetShift}
          dateStr={requestTargetDate}
          statusOptions={statusMaps ? requestableStatuses(statusMaps) : undefined}
        />
      )}

      {/* Schedule Requests Panel */}
      <ScheduleRequestsPanel
        isOpen={requestsPanelOpen}
        onClose={() => setRequestsPanelOpen(false)}
      />

      {/* Snapshot Panel */}
      <SnapshotPanel
        isOpen={snapshotPanelOpen}
        onClose={() => setSnapshotPanelOpen(false)}
        currentStartDate={actionStart}
        currentEndDate={actionEnd}
        currentRangeType={viewMode === 'day' ? 'day' : rangeMode}
        employeeIds={shownIds}
      />

      <TemplatesPanel
        isOpen={templatesOpen}
        onClose={() => setTemplatesOpen(false)}
        employees={employees.filter((e) => manageable.has(e.employee_id))}
        weekStart={actionStart}
        statusMaps={statusMaps}
      />

      {/* Copy week → next. Always the rows shown (it used to send nothing when
          only the search box was used, which copied the whole company). */}
      <CopyWeekModal
        isOpen={copyWeekOpen}
        onClose={() => setCopyWeekOpen(false)}
        sourceStart={actionStart}
        sourceEnd={actionEnd}
        employeeIds={manageableIds}
      />
    </DashboardLayout>
  );
}
