'use client';

import React, { Suspense, useState, useMemo, useCallback, useEffect } from 'react';
import dynamic from 'next/dynamic';
import { useSearchParams, useRouter } from 'next/navigation';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import DashboardLayout from '@/components/layout/DashboardLayout';
import { useAuth } from '@/contexts/AuthContext';
import { hasAnyRole } from '@/lib/roles';
import { api } from '@/lib/api';
import { ScheduleGrid, Shift, AppSettings, ShiftStatusType, UserPreferences, OrgTreeNode, ShiftActuals } from '@/types';
import { buildStatusMaps, toLocalDateStr } from './scheduleHelpers';
import { useToast } from '@/components/ui/Toast';

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

const EDITOR_ROLES = ['tenant_admin', 'hr', 'manager', 'schedule_editor'];
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
  const canEdit = user ? hasAnyRole(user, EDITOR_ROLES) : false;

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

  // Clear all confirmation state
  const [clearAllConfirm, setClearAllConfirm] = useState(false);

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

  const { data: gridData, isLoading: gridLoading } = useQuery<ScheduleGrid>({
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

  // Guardrail lint for the visible range (editors only) → inline cell warnings.
  const { data: lintData } = useQuery({
    queryKey: ['schedule-lint', formatDate(start), formatDate(end), orgNodeId],
    queryFn: () => api.lintSchedule({
      start_date: formatDate(start),
      end_date: formatDate(end),
    }),
    enabled: canEdit && !settingsLoading,
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
  // Draft (unpublished) shifts in the current view — only editors see these.
  const draftCount = useMemo(
    () => employees.reduce(
      (acc, e) => acc + e.shifts.filter((s) => s.is_published === false).length, 0,
    ),
    [employees],
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

  // Bulk delete mutation
  const bulkDeleteMutation = useMutation({
    mutationFn: () => api.bulkDeleteShifts({
      start_date: formatDate(start),
      end_date: formatDate(end),
    }),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['schedule-grid'] });
      setClearAllConfirm(false);
      showToast(`${(data as { deleted_count: number }).deleted_count} shifts cleared`, 'success');
    },
    onError: (err: Error) => showToast(err.message, 'error'),
  });

  // Publish the current visible range (respect the org/dept filter).
  const publishMutation = useMutation({
    mutationFn: () => api.publishSchedule({
      start_date: formatDate(start),
      end_date: formatDate(end),
      ...(orgNodeId ? { employee_ids: employees.map((e) => e.employee_id) } : {}),
    }),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ['schedule-grid'] });
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
    if (canEdit) {
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
    if (!canEdit) return;
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

  const handlePasteShift = useCallback(
    (employeeId: number, dateStr: string) => {
      if (!clipboard || !canEdit) return;
      // Clear selection immediately for visual feedback
      setSelectedCell(null);
      createShiftMutation.mutate({
        employee_id: employeeId,
        date: dateStr,
        ...clipboard,
      });
    },
    [clipboard, canEdit, createShiftMutation],
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
      if (!canEdit) return;
      updateShiftMutation.mutate({
        id: shiftId,
        data: { employee_id: targetEmployeeId, date: targetDateStr },
      });
    },
    [canEdit, updateShiftMutation],
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
          onShowActualsChange={setShowActuals}
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
          onExportXlsx={handleExportXlsx}
          canEdit={canEdit}
          clipboard={clipboard}
          onClearClipboard={handleClearClipboard}
          rowOrderDirty={rowOrderDirty}
          onSaveLayout={handleSaveLayout}
          savingLayout={saveRowOrderMutation.isPending}
          onOpenRequests={() => setRequestsPanelOpen(true)}
          customStartDate={customStartDate}
          customEndDate={customEndDate}
          onCustomRangeChange={handleCustomRangeChange}
          onOpenSnapshots={() => setSnapshotPanelOpen(true)}
          onCopyWeek={() => setCopyWeekOpen(true)}
          onClearAll={() => setClearAllConfirm(true)}
        />

        {/* Stats bar */}
        <StatsBar stats={stats} loading={isLoading} />

        {/* Guardrail warnings summary (editors only) */}
        {canEdit && violationCount > 0 && (
          <div className="flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-4 py-2 text-xs text-amber-700">
            <svg className="h-4 w-4 shrink-0" viewBox="0 0 24 24" fill="currentColor">
              <path d="M12 2L1 21h22L12 2zm0 6l7.53 13H4.47L12 8zm-1 3v4h2v-4h-2zm0 5v2h2v-2h-2z" />
            </svg>
            <span>
              <span className="font-semibold">{violationCount}</span> guardrail warning{violationCount !== 1 ? 's' : ''} in this range — hover the amber marks on the grid for details.
            </span>
          </div>
        )}

        {/* Draft / publish banner (editors only) */}
        {canEdit && draftCount > 0 && (
          <div className="flex items-center justify-between gap-3 rounded-lg border border-purple-200 bg-purple-50 px-4 py-2.5">
            <div className="flex items-center gap-2 text-xs text-purple-800">
              <svg className="h-4 w-4 shrink-0" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
              </svg>
              <span>
                <span className="font-semibold">{draftCount}</span> draft shift{draftCount !== 1 ? 's' : ''} in this range are hidden from employees until published.
              </span>
            </div>
            <button
              onClick={() => publishMutation.mutate()}
              disabled={publishMutation.isPending}
              className="rounded-md bg-purple-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-purple-700 disabled:opacity-50"
            >
              {publishMutation.isPending ? 'Publishing…' : `Publish ${draftCount} shift${draftCount !== 1 ? 's' : ''}`}
            </button>
          </div>
        )}

        {/* Clear all confirmation banner */}
        {clearAllConfirm && (
          <div className="bg-red-50 border border-red-200 rounded-xl px-5 py-4 flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-red-800">Clear all shifts in current view?</p>
              <p className="text-xs text-red-600 mt-0.5">
                This will permanently delete all {stats.total_shifts} shift{stats.total_shifts !== 1 ? 's' : ''} from {formatDate(start)} to {formatDate(end)} for all employees.
              </p>
            </div>
            <div className="flex items-center gap-2 ml-4 flex-shrink-0">
              <button
                onClick={() => setClearAllConfirm(false)}
                className="px-3 py-1.5 text-xs font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => bulkDeleteMutation.mutate()}
                disabled={bulkDeleteMutation.isPending}
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

        {/* Day View */}
        {!isLoading && viewMode === 'day' && (
          <DayView
            employees={employees}
            dates={dates}
            dateRemarks={dateRemarks}
            onShiftClick={handleShiftClick}
            onCellClick={handleCellClick}
            canEdit={canEdit}
            statusMaps={statusMaps}
            currentUserId={user?.id}
            onSwapRequest={handleSwapRequest}
            onChangeRequest={handleChangeRequest}
          />
        )}

        {/* Grid / Calendar */}
        {!isLoading && viewMode === 'linear' && (
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
            onMoveShift={canEdit ? handleMoveShift : undefined}
            savedRowOrder={savedRowOrder}
            onRowOrderChange={setCurrentRowOrder}
            canEdit={canEdit}
            currentUserId={user?.id}
            onSwapRequest={handleSwapRequest}
            onChangeRequest={handleChangeRequest}
            statusMaps={statusMaps}
            actualsMap={actualsMap}
          />
        )}

        {!isLoading && viewMode === 'calendar' && (
          <CalendarView
            employees={employees}
            dates={dates}
            dateRemarks={dateRemarks}
            currentDate={currentDate}
            onShiftClick={handleShiftClick}
            onAddShift={handleCalendarAddShift}
            canEdit={canEdit}
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
        onDelete={editingShift ? handleDelete : undefined}
        shift={editingShift}
        employees={employees}
        prefillEmployeeId={prefillEmployeeId}
        prefillDate={prefillDate}
        statusOptions={statusMaps?.allStatuses}
        statusCategories={statusMaps?.categories}
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
          statusOptions={statusMaps?.allStatuses}
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
        currentStartDate={formatDate(start)}
        currentEndDate={formatDate(end)}
        currentRangeType={viewMode === 'day' ? 'day' : rangeMode}
      />

      {/* Copy week → next */}
      <CopyWeekModal
        isOpen={copyWeekOpen}
        onClose={() => setCopyWeekOpen(false)}
        sourceStart={formatDate(start)}
        sourceEnd={formatDate(end)}
        employeeIds={orgNodeId ? employees.map((e) => e.employee_id) : undefined}
      />
    </DashboardLayout>
  );
}
