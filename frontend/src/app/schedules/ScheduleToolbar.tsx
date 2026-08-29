'use client';

import React, { useState, useRef, useEffect } from 'react';
import { ClipboardShift } from './page';

export interface OrgNodeOption {
  id: number;
  label: string;
  depth: number;
}

export type ViewMode = 'linear' | 'calendar' | 'day';
export type RangeMode = 'week' | 'biweekly' | 'month' | 'custom';

interface ScheduleToolbarProps {
  viewMode: ViewMode;
  onViewModeChange: (mode: ViewMode) => void;
  rangeMode: RangeMode;
  onRangeModeChange: (mode: RangeMode) => void;
  currentDate: Date;
  onPrev: () => void;
  onNext: () => void;
  onToday: () => void;
  dateLabel: string;
  search: string;
  onSearchChange: (val: string) => void;
  orgNodes?: OrgNodeOption[];
  orgNodeId?: number | null;
  onOrgNodeChange?: (id: number | null) => void;
  onAddShift: () => void;
  onExport: () => void;
  onExportXlsx?: () => void;
  canEdit: boolean;
  /** Overlay recorded attendance + approved overtime on the planning grid. */
  showActuals?: boolean;
  onShowActualsChange?: (v: boolean) => void;
  clipboard?: ClipboardShift | null;
  onClearClipboard?: () => void;
  rowOrderDirty?: boolean;
  onSaveLayout?: () => void;
  savingLayout?: boolean;
  onOpenRequests?: () => void;
  // Custom range
  customStartDate?: string;
  customEndDate?: string;
  onCustomRangeChange?: (start: string, end: string) => void;
  // Snapshots
  onOpenSnapshots?: () => void;
  // Copy week → next
  onCopyWeek?: () => void;
  // Clear all
  onClearAll?: () => void;
}

export default function ScheduleToolbar({
  viewMode,
  onViewModeChange,
  rangeMode,
  onRangeModeChange,
  currentDate,
  onPrev,
  onNext,
  onToday,
  dateLabel,
  search,
  onSearchChange,
  orgNodes,
  orgNodeId,
  onOrgNodeChange,
  onAddShift,
  onExport,
  onExportXlsx,
  canEdit,
  showActuals,
  onShowActualsChange,
  clipboard,
  onClearClipboard,
  rowOrderDirty,
  onSaveLayout,
  savingLayout,
  onOpenRequests,
  customStartDate,
  customEndDate,
  onCustomRangeChange,
  onOpenSnapshots,
  onCopyWeek,
  onClearAll,
}: ScheduleToolbarProps) {
  const [showCustomPicker, setShowCustomPicker] = useState(false);
  const [showMore, setShowMore] = useState(false);
  const moreRef = useRef<HTMLDivElement>(null);
  const customRef = useRef<HTMLDivElement>(null);

  // Close dropdowns on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (moreRef.current && !moreRef.current.contains(e.target as Node)) setShowMore(false);
      if (customRef.current && !customRef.current.contains(e.target as Node)) setShowCustomPicker(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  return (
    <div className="bg-white rounded-xl border border-gray-200 px-4 py-3 space-y-2">
      {/* Row 1: Main controls */}
      <div className="flex flex-wrap items-center gap-3">
        {/* Date navigation */}
        <div className="flex items-center gap-1">
          <button
            onClick={onPrev}
            className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-600 transition-colors"
            title="Previous"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          </button>
          <button
            onClick={onToday}
            className="px-3 py-1 text-xs font-medium rounded-lg bg-purple-50 text-purple-700 hover:bg-purple-100 transition-colors"
          >
            Today
          </button>
          <button
            onClick={onNext}
            className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-600 transition-colors"
            title="Next"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
          </button>
        </div>

        {/* Date label */}
        <h2 className="text-sm font-semibold text-gray-900 min-w-[140px]">{dateLabel}</h2>

        {/* Range selector */}
        <div className="flex bg-gray-100 rounded-lg p-0.5 relative" ref={customRef}>
          {(['week', 'biweekly', 'month'] as RangeMode[]).map((mode) => (
            <button
              key={mode}
              onClick={() => { onRangeModeChange(mode); setShowCustomPicker(false); }}
              className={`px-3 py-1 text-xs font-medium rounded-md transition-colors ${
                rangeMode === mode
                  ? 'bg-white text-gray-900 shadow-sm'
                  : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              {mode === 'week' ? '1W' : mode === 'biweekly' ? '2W' : '1M'}
            </button>
          ))}
          <button
            onClick={() => {
              if (rangeMode !== 'custom') onRangeModeChange('custom');
              setShowCustomPicker((p) => !p);
            }}
            className={`px-3 py-1 text-xs font-medium rounded-md transition-colors ${
              rangeMode === 'custom'
                ? 'bg-white text-gray-900 shadow-sm'
                : 'text-gray-500 hover:text-gray-700'
            }`}
            title="Custom date range"
          >
            <svg className="w-3.5 h-3.5 inline-block" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 012.25-2.25h13.5A2.25 2.25 0 0121 7.5v11.25m-18 0A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75m-18 0v-7.5A2.25 2.25 0 015.25 9h13.5A2.25 2.25 0 0121 11.25v7.5" />
            </svg>
          </button>

          {/* Custom range popover */}
          {showCustomPicker && (
            <div className="absolute top-full left-0 mt-1 z-50 bg-white border border-gray-200 rounded-lg shadow-lg p-3 min-w-[280px]">
              <p className="text-xs font-medium text-gray-700 mb-2">Custom Date Range</p>
              <div className="flex items-center gap-2">
                <input
                  type="date"
                  value={customStartDate ?? ''}
                  onChange={(e) => onCustomRangeChange?.(e.target.value, customEndDate ?? '')}
                  className="flex-1 text-xs border border-gray-300 rounded-md px-2 py-1.5 focus:ring-2 focus:ring-purple-500 focus:border-transparent"
                />
                <span className="text-xs text-gray-400">to</span>
                <input
                  type="date"
                  value={customEndDate ?? ''}
                  onChange={(e) => onCustomRangeChange?.(customStartDate ?? '', e.target.value)}
                  className="flex-1 text-xs border border-gray-300 rounded-md px-2 py-1.5 focus:ring-2 focus:ring-purple-500 focus:border-transparent"
                />
              </div>
              <button
                onClick={() => setShowCustomPicker(false)}
                className="mt-2 w-full px-3 py-1 text-xs font-medium text-purple-700 bg-purple-50 rounded-md hover:bg-purple-100 transition-colors"
              >
                Apply
              </button>
            </div>
          )}
        </div>

        {/* View toggle */}
        <div className="flex bg-gray-100 rounded-lg p-0.5">
          <button
            onClick={() => onViewModeChange('day')}
            className={`p-1.5 rounded-md transition-colors ${
              viewMode === 'day' ? 'bg-white text-purple-600 shadow-sm' : 'text-gray-400 hover:text-gray-600'
            }`}
            title="Day View"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 012.25-2.25h13.5A2.25 2.25 0 0121 7.5v11.25m-18 0A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75m-18 0v-7.5A2.25 2.25 0 015.25 9h13.5A2.25 2.25 0 0121 11.25v7.5m-9-6h.008v.008H12v-.008zM12 15h.008v.008H12V15z" />
            </svg>
          </button>
          <button
            onClick={() => onViewModeChange('linear')}
            className={`p-1.5 rounded-md transition-colors ${
              viewMode === 'linear' ? 'bg-white text-purple-600 shadow-sm' : 'text-gray-400 hover:text-gray-600'
            }`}
            title="Grid View"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 10h16M4 14h16M4 18h16" />
            </svg>
          </button>
          <button
            onClick={() => onViewModeChange('calendar')}
            className={`p-1.5 rounded-md transition-colors ${
              viewMode === 'calendar' ? 'bg-white text-purple-600 shadow-sm' : 'text-gray-400 hover:text-gray-600'
            }`}
            title="Calendar View"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
            </svg>
          </button>
        </div>

        {/* Spacer */}
        <div className="flex-1" />

        {/* Org-unit filter — narrows the roster so a big all-employees view
            isn't an endless scroll. Picking a unit includes its whole subtree.
            "All units" clears it. */}
        {orgNodes && orgNodes.length > 0 && onOrgNodeChange && (
          <select
            value={orgNodeId ?? ''}
            onChange={(e) => onOrgNodeChange(e.target.value ? Number(e.target.value) : null)}
            className="py-1.5 pl-3 pr-8 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-transparent bg-white text-gray-700 max-w-[200px]"
            title="Filter by org unit"
          >
            <option value="">All units</option>
            {orgNodes.map((n) => (
              <option key={n.id} value={n.id}>
                {`${'\u00A0\u00A0'.repeat(n.depth)}${n.label}`}
              </option>
            ))}
          </select>
        )}

        {/* Search */}
        <div className="relative">
          <svg className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            type="text"
            placeholder="Search employees..."
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
            className="w-48 pl-8 pr-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-transparent"
          />
        </div>

        {/* Clipboard indicator */}
        {clipboard && (
          <div className="flex items-center gap-1.5 px-2.5 py-1 bg-purple-50 border border-purple-200 rounded-lg">
            <svg className="w-3.5 h-3.5 text-purple-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
            </svg>
            <span className="text-xs font-medium text-purple-700">
              Copied: {clipboard.status}{clipboard.start_time ? ` ${clipboard.start_time.substring(0, 5)}` : ''}
            </span>
            <button
              onClick={onClearClipboard}
              className="p-0.5 rounded hover:bg-purple-100 text-purple-400 hover:text-purple-600 transition-colors"
              title="Clear clipboard"
            >
              <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        )}

        {/* Save Layout */}
        {rowOrderDirty && onSaveLayout && (
          <button
            onClick={onSaveLayout}
            disabled={savingLayout}
            className="px-3 py-1.5 text-xs font-medium text-purple-700 bg-purple-50 border border-purple-300 rounded-lg hover:bg-purple-100 transition-colors flex items-center gap-1.5 disabled:opacity-50"
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7H5a2 2 0 00-2 2v9a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-3m-1 4l-3 3m0 0l-3-3m3 3V4" />
            </svg>
            {savingLayout ? 'Saving...' : 'Save Layout'}
          </button>
        )}

        {/* My Requests */}
        {onOpenRequests && (
          <button
            onClick={onOpenRequests}
            className="px-3 py-1.5 text-xs font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors flex items-center gap-1.5"
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
            </svg>
            Requests
          </button>
        )}

        {/* More actions dropdown (editor only) */}
        {canEdit && (
          <div className="relative" ref={moreRef}>
            <button
              onClick={() => setShowMore((p) => !p)}
              title="Snapshots, export, clear…"
              className="px-3 py-1.5 text-xs font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors flex items-center gap-1.5"
            >
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 6.75a.75.75 0 110-1.5.75.75 0 010 1.5zM12 12.75a.75.75 0 110-1.5.75.75 0 010 1.5zM12 18.75a.75.75 0 110-1.5.75.75 0 010 1.5z" />
              </svg>
              More
            </button>

            {showMore && (
              <div className="absolute right-0 top-full mt-1 z-50 bg-white border border-gray-200 rounded-lg shadow-lg py-1 min-w-[180px]">
                {/* Primary reusable action first */}
                {onOpenSnapshots && (
                  <button
                    onClick={() => { onOpenSnapshots(); setShowMore(false); }}
                    className="w-full text-left px-3 py-2 text-xs text-gray-700 hover:bg-gray-50 flex items-center gap-2 transition-colors"
                  >
                    <svg className="w-3.5 h-3.5 text-purple-500" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M6.827 6.175A2.31 2.31 0 015.186 7.23c-.38.054-.757.112-1.134.175C2.999 7.58 2.25 8.507 2.25 9.574V18a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9.574c0-1.067-.75-1.994-1.802-2.169a47.865 47.865 0 00-1.134-.175 2.31 2.31 0 01-1.64-1.055l-.822-1.316a2.192 2.192 0 00-1.736-1.039 48.774 48.774 0 00-5.232 0 2.192 2.192 0 00-1.736 1.039l-.821 1.316z" />
                      <path strokeLinecap="round" strokeLinejoin="round" d="M16.5 12.75a4.5 4.5 0 11-9 0 4.5 4.5 0 019 0z" />
                    </svg>
                    Schedule Snapshots
                  </button>
                )}

                {onCopyWeek && (
                  <button
                    onClick={() => { onCopyWeek(); setShowMore(false); }}
                    className="w-full text-left px-3 py-2 text-xs text-gray-700 hover:bg-gray-50 flex items-center gap-2 transition-colors"
                  >
                    <svg className="w-3.5 h-3.5 text-purple-500" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M8 7v8a2 2 0 002 2h6M8 7V5a2 2 0 012-2h4.586a1 1 0 01.707.293l4.414 4.414a1 1 0 01.293.707V15a2 2 0 01-2 2h-2M8 7H6a2 2 0 00-2 2v10a2 2 0 002 2h8a2 2 0 002-2v-2" />
                    </svg>
                    Duplicate week → next
                  </button>
                )}

                {(onOpenSnapshots || onCopyWeek) && <div className="border-t border-gray-100 my-1" />}

                <button
                  onClick={() => { onExport(); setShowMore(false); }}
                  className="w-full text-left px-3 py-2 text-xs text-gray-700 hover:bg-gray-50 flex items-center gap-2 transition-colors"
                >
                  <svg className="w-3.5 h-3.5 text-gray-400" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                  </svg>
                  Export CSV
                </button>

                {onExportXlsx && (
                  <button
                    onClick={() => { onExportXlsx(); setShowMore(false); }}
                    className="w-full text-left px-3 py-2 text-xs text-gray-700 hover:bg-gray-50 flex items-center gap-2 transition-colors"
                  >
                    <svg className="w-3.5 h-3.5 text-green-600" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                    </svg>
                    Export Work Schedule (XLSX)
                  </button>
                )}

                {onClearAll && (
                  <>
                    <div className="border-t border-gray-100 my-1" />
                    <button
                      onClick={() => { onClearAll(); setShowMore(false); }}
                      className="w-full text-left px-3 py-2 text-xs text-red-600 hover:bg-red-50 flex items-center gap-2 transition-colors"
                    >
                      <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
                      </svg>
                      Clear All Shifts in View
                    </button>
                  </>
                )}
              </div>
            )}
          </div>
        )}

        {/* Actuals overlay. Off by default: the grid is a plan, and actuals
            only exist for days already worked. */}
        {onShowActualsChange && (
          <button
            type="button"
            onClick={() => onShowActualsChange(!showActuals)}
            aria-pressed={!!showActuals}
            title="Overlay recorded attendance and approved overtime on the schedule"
            className={`px-3 py-1.5 text-xs font-medium rounded-lg border transition-colors flex items-center gap-1.5 ${
              showActuals
                ? 'bg-indigo-50 border-indigo-300 text-indigo-700'
                : 'bg-white border-gray-300 text-gray-700 hover:bg-gray-50'
            }`}
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            Actuals
          </button>
        )}

        {/* Export (non-editor fallback) */}
        {!canEdit && (
          <button
            onClick={onExport}
            className="px-3 py-1.5 text-xs font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors flex items-center gap-1.5"
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            Export
          </button>
        )}

        {/* Add Shift */}
        {canEdit && (
          <button
            onClick={onAddShift}
            className="px-3 py-1.5 text-xs font-medium text-white bg-purple-600 rounded-lg hover:bg-purple-700 transition-colors flex items-center gap-1.5"
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
            Add Shift
          </button>
        )}
      </div>
    </div>
  );
}
