'use client';

import React, { useMemo, useState, useEffect, useRef, useCallback } from 'react';
import { ScheduleEmployee, Shift, DateRemark, ShiftActuals } from '@/types';
import { ClipboardShift, SelectedCell } from './page';
import { toLocalDateStr, type StatusMaps } from './scheduleHelpers';
import ShiftCell from './ShiftCell';

interface LinearGridViewProps {
  employees: ScheduleEmployee[];
  dates: string[];
  dateRemarks: DateRemark[];
  /** employee_id → date → guardrail violation messages (inline warnings). */
  violationMap?: Map<number, Map<string, string[]>>;
  onShiftClick: (shift: Shift) => void;
  onCellClick: (employeeId: number, dateStr: string) => void;
  selectedCell?: SelectedCell | null;
  clipboard?: ClipboardShift | null;
  onCellSelect?: (employeeId: number, dateStr: string, shift?: Shift) => void;
  onCopyShift?: (shift: Shift) => void;
  onPasteShift?: (employeeId: number, dateStr: string) => void;
  onMoveShift?: (shiftId: number, employeeId: number, dateStr: string) => void;
  savedRowOrder?: number[] | null;
  onRowOrderChange?: (order: number[]) => void;
  canEdit?: boolean;
  currentUserId?: number;
  onSwapRequest?: (shift: Shift) => void;
  onChangeRequest?: (shift: Shift) => void;
  /** Tenant status types, so the grid honours admin-configured colours. */
  statusMaps?: StatusMaps;
  /** Attendance/overtime keyed "employeeId:date". Empty unless actuals are on. */
  actualsMap?: Map<string, ShiftActuals>;
}

const DAY_NAMES_SHORT = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const ROW_DRAG_TYPE = 'application/x-row-reorder';

export default function LinearGridView({
  employees,
  dates,
  dateRemarks,
  violationMap,
  onShiftClick,
  onCellClick,
  selectedCell,
  clipboard,
  onCellSelect,
  onCopyShift,
  onPasteShift,
  onMoveShift,
  savedRowOrder,
  onRowOrderChange,
  canEdit,
  currentUserId,
  onSwapRequest,
  onChangeRequest,
  statusMaps,
  actualsMap,
}: LinearGridViewProps) {
  const today = useMemo(() => toLocalDateStr(new Date()), []);

  // ── Row reordering state ─────────────────────────────────────────
  const [orderedEmployees, setOrderedEmployees] = useState<ScheduleEmployee[]>(employees);
  const [dragRowId, setDragRowId] = useState<number | null>(null);
  const [dropTargetId, setDropTargetId] = useState<number | null>(null);
  const rowDragCounters = useRef<Record<number, number>>({});
  const appliedSavedOrder = useRef(false);

  // Sync when employees prop changes (new data from server)
  // On initial load, apply savedRowOrder if available; otherwise preserve local order
  useEffect(() => {
    if (employees.length === 0) return;

    setOrderedEmployees((prev) => {
      const newMap = new Map(employees.map((e) => [e.employee_id, e]));

      // Use savedRowOrder if it hasn't been applied yet and is available
      let orderSource: number[];
      if (!appliedSavedOrder.current && savedRowOrder && savedRowOrder.length > 0) {
        orderSource = savedRowOrder;
        appliedSavedOrder.current = true;
      } else if (prev.length > 0) {
        orderSource = prev.map((e) => e.employee_id);
      } else {
        // No saved order and no previous order — use server default
        return employees;
      }

      // Apply order: keep employees that still exist
      const ordered = orderSource
        .filter((id) => newMap.has(id))
        .map((id) => newMap.get(id)!);

      // Append new employees not in the order source
      const orderedIds = new Set(ordered.map((e) => e.employee_id));
      const added = employees.filter((e) => !orderedIds.has(e.employee_id));

      return [...ordered, ...added];
    });
  }, [employees, savedRowOrder]);


  const handleRowDragStart = useCallback((e: React.DragEvent, empId: number) => {
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData(ROW_DRAG_TYPE, String(empId));
    setDragRowId(empId);
    // Dim the dragged row
    const tr = (e.target as HTMLElement).closest('tr');
    if (tr) tr.style.opacity = '0.4';
  }, []);

  const handleRowDragEnd = useCallback((e: React.DragEvent) => {
    const tr = (e.target as HTMLElement).closest('tr');
    if (tr) tr.style.opacity = '1';
    setDragRowId(null);
    setDropTargetId(null);
    rowDragCounters.current = {};
  }, []);

  const handleRowDragOver = useCallback((e: React.DragEvent) => {
    if (!e.dataTransfer.types.includes(ROW_DRAG_TYPE)) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
  }, []);

  const handleRowDragEnter = useCallback((e: React.DragEvent, empId: number) => {
    if (!e.dataTransfer.types.includes(ROW_DRAG_TYPE)) return;
    e.preventDefault();
    rowDragCounters.current[empId] = (rowDragCounters.current[empId] || 0) + 1;
    if (rowDragCounters.current[empId] === 1) {
      setDropTargetId(empId);
    }
  }, []);

  const handleRowDragLeave = useCallback((empId: number) => {
    rowDragCounters.current[empId] = (rowDragCounters.current[empId] || 0) - 1;
    if (rowDragCounters.current[empId] <= 0) {
      rowDragCounters.current[empId] = 0;
      setDropTargetId((prev) => (prev === empId ? null : prev));
    }
  }, []);

  const handleRowDrop = useCallback((e: React.DragEvent, targetEmpId: number) => {
    e.preventDefault();
    rowDragCounters.current = {};
    setDropTargetId(null);
    setDragRowId(null);

    const raw = e.dataTransfer.getData(ROW_DRAG_TYPE);
    if (!raw) return;
    const sourceEmpId = Number(raw);
    if (sourceEmpId === targetEmpId) return;

    setOrderedEmployees((prev) => {
      const sourceIdx = prev.findIndex((e) => e.employee_id === sourceEmpId);
      const targetIdx = prev.findIndex((e) => e.employee_id === targetEmpId);
      if (sourceIdx === -1 || targetIdx === -1) return prev;
      const next = [...prev];
      const [moved] = next.splice(sourceIdx, 1);
      next.splice(targetIdx, 0, moved);
      // Notify parent synchronously (parent tracks dirty state)
      if (onRowOrderChange) {
        onRowOrderChange(next.map((e) => e.employee_id));
      }
      return next;
    });
  }, [onRowOrderChange]);

  const remarkMap = useMemo(() => {
    const map: Record<string, DateRemark> = {};
    dateRemarks.forEach((r) => (map[r.date] = r));
    return map;
  }, [dateRemarks]);

  // Group shifts by date for each employee
  const employeeShiftMap = useMemo(() => {
    const map: Record<number, Record<string, Shift[]>> = {};
    employees.forEach((emp) => {
      const byDate: Record<string, Shift[]> = {};
      emp.shifts.forEach((s) => {
        if (!byDate[s.date]) byDate[s.date] = [];
        byDate[s.date].push(s);
      });
      map[emp.employee_id] = byDate;
    });
    return map;
  }, [employees]);

  if (employees.length === 0) {
    return (
      <div className="bg-white rounded-xl border border-gray-200 p-12 text-center">
        <svg className="w-12 h-12 mx-auto text-gray-300 mb-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" />
        </svg>
        <p className="text-gray-500 text-sm">No employees found</p>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
      {/* Own scroll viewport: the grid scrolls internally (both axes) instead of
          growing the whole page, and the date-header row + employee column stay
          pinned so you never lose which day / whose row you're on. */}
      <div className="overflow-auto max-h-[70vh] sm:max-h-[calc(100vh-320px)]">
        {/* border-separate, NOT border-collapse. position:sticky on a th/td is
            ignored by WebKit when the table collapses its borders, so on iOS the
            pinned header and employee column detach and drift as you scroll.
            Cells carry their own border-b/border-r, so nothing doubles up. */}
        <table className="w-full border-separate border-spacing-0">
          <thead>
            <tr>
              {/* Employee column header — pinned top AND left (corner cell) */}
              <th className="sticky top-0 left-0 z-40 bg-gray-50 border-b border-r border-gray-200 px-2 sm:px-4 py-2 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider min-w-[124px] sm:min-w-[200px]">
                Employee
              </th>
              {dates.map((dateStr) => {
                const d = new Date(dateStr + 'T00:00:00');
                const dayName = DAY_NAMES_SHORT[d.getDay()];
                const dayNum = d.getDate();
                const isToday = dateStr === today;
                const isWeekend = d.getDay() === 0 || d.getDay() === 6;
                const remark = remarkMap[dateStr];

                return (
                  <th
                    key={dateStr}
                    className={`sticky top-0 z-30 border-b border-r border-gray-200 px-1 py-2 text-center min-w-[64px] sm:min-w-[100px] max-w-[120px] ${
                      isToday ? 'bg-purple-50' : isWeekend ? 'bg-gray-50' : 'bg-gray-100'
                    }`}
                  >
                    <div className="text-[10px] text-gray-400 uppercase">{dayName}</div>
                    <div className={`text-sm font-semibold ${isToday ? 'text-purple-600' : 'text-gray-700'}`}>
                      {dayNum}
                    </div>
                    {remark && (
                      <div
                        className={`text-[9px] truncate px-1 mt-0.5 rounded ${
                          remark.is_holiday
                            ? remark.is_special
                              ? 'text-amber-700 font-medium'
                              : 'text-red-600 font-medium'
                            : 'text-blue-500'
                        }`}
                        title={
                          remark.is_holiday
                            ? `${remark.title} — ${remark.is_special ? 'special (non-working)' : 'regular'} holiday`
                            : remark.title
                        }
                      >
                        {remark.title}
                      </div>
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {orderedEmployees.map((emp) => {
              const shiftsByDate = employeeShiftMap[emp.employee_id] ?? {};
              const isDragging = dragRowId === emp.employee_id;
              const isDropTarget = dropTargetId === emp.employee_id && dragRowId !== emp.employee_id;
              return (
                <tr
                  key={emp.employee_id}
                  className={`group transition-colors ${isDropTarget ? 'ring-2 ring-inset ring-blue-400' : ''}`}
                  onDragOver={handleRowDragOver}
                  onDragEnter={(e) => handleRowDragEnter(e, emp.employee_id)}
                  onDragLeave={() => handleRowDragLeave(emp.employee_id)}
                  onDrop={(e) => handleRowDrop(e, emp.employee_id)}
                >
                  {/* Sticky employee name with drag handle (left-pinned, under the
                      header corner but above the scrolling shift cells) */}
                  <td className={`sticky left-0 z-20 bg-white group-hover:bg-gray-50 border-b border-r border-gray-200 px-2 py-2 transition-colors ${isDragging ? 'opacity-40' : ''}`}>
                    <div className="flex items-center gap-1.5">
                      {/* Drag grip handle */}
                      <div
                        draggable
                        onDragStart={(e) => handleRowDragStart(e, emp.employee_id)}
                        onDragEnd={handleRowDragEnd}
                        className="hidden sm:block flex-shrink-0 cursor-grab active:cursor-grabbing p-0.5 rounded hover:bg-gray-200 text-gray-300 hover:text-gray-500 transition-colors"
                        title="Drag to reorder"
                      >
                        <svg className="w-4 h-4" viewBox="0 0 16 16" fill="currentColor">
                          <circle cx="5.5" cy="3.5" r="1.5" />
                          <circle cx="10.5" cy="3.5" r="1.5" />
                          <circle cx="5.5" cy="8" r="1.5" />
                          <circle cx="10.5" cy="8" r="1.5" />
                          <circle cx="5.5" cy="12.5" r="1.5" />
                          <circle cx="10.5" cy="12.5" r="1.5" />
                        </svg>
                      </div>
                      <div className="hidden sm:flex w-7 h-7 rounded-full bg-gradient-to-br from-purple-400 to-purple-600 items-center justify-center text-white text-[10px] font-semibold flex-shrink-0">
                        {emp.employee_name.split(' ').map(n => n[0]).join('').substring(0, 2)}
                      </div>
                      <div className="min-w-0">
                        <p className="text-xs font-medium text-gray-900 truncate">{emp.employee_name}</p>
                        {emp.section_name && (
                          <p className="text-[10px] text-gray-400 truncate">{emp.section_name}</p>
                        )}
                      </div>
                    </div>
                  </td>
                  {dates.map((dateStr) => {
                    const d = new Date(dateStr + 'T00:00:00');
                    const isToday = dateStr === today;
                    const isWeekend = d.getDay() === 0 || d.getDay() === 6;
                    const remark = remarkMap[dateStr];
                    const shifts = shiftsByDate[dateStr] ?? [];

                    const isCellSelected =
                      selectedCell?.employeeId === emp.employee_id &&
                      selectedCell?.dateStr === dateStr;

                    const warnings = violationMap?.get(emp.employee_id)?.get(dateStr);

                    // onCellClick is handed over only when the viewer may write.
                    // ShiftCell keys its add affordances off that prop, so a
                    // read-only user no longer sees a "+" the API would refuse.
                    // canEdit was previously declared and destructured here but
                    // never actually read.
                    return (
                      <ShiftCell
                        key={dateStr}
                        shifts={shifts}
                        employeeId={emp.employee_id}
                        dateStr={dateStr}
                        remark={remark}
                        warnings={warnings}
                        isToday={isToday}
                        isWeekend={isWeekend}
                        isSelected={isCellSelected}
                        hasClipboard={!!clipboard}
                        onShiftClick={onShiftClick}
                        {...(canEdit
                          ? { onCellClick: () => onCellClick(emp.employee_id, dateStr) }
                          : {})}
                        onCellSelect={onCellSelect}
                        onCopyShift={onCopyShift}
                        onPasteShift={onPasteShift}
                        onMoveShift={onMoveShift}
                        isOwnShift={currentUserId === emp.employee_id}
                        onSwapRequest={onSwapRequest}
                        onChangeRequest={onChangeRequest}
                        statusMaps={statusMaps}
                        actuals={actualsMap?.get(`${emp.employee_id}:${dateStr}`)}
                      />
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
