'use client';

import React, { useMemo, useState } from 'react';
import { ScheduleEmployee, Shift, DateRemark, ShiftStatusType } from '@/types';
import { toLocalDateStr } from './scheduleHelpers';
import CalendarDayCell from './CalendarDayCell';
import type { StatusMaps } from './scheduleHelpers';
import DayDetailPanel from './DayDetailPanel';

interface CalendarViewProps {
  employees: ScheduleEmployee[];
  dates: string[];
  dateRemarks: DateRemark[];
  currentDate: Date;
  onShiftClick: (shift: Shift) => void;
  onAddShift: (dateStr: string) => void;
  canEdit: boolean;
  weekStartDay?: 'monday' | 'sunday' | 'saturday';
  statusTypes?: ShiftStatusType[];
  statusMaps?: StatusMaps;
  currentUserId?: number;
  onSwapRequest?: (shift: Shift) => void;
  onChangeRequest?: (shift: Shift) => void;
}

const DAY_HEADERS_SUN = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const DAY_HEADERS_MON = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const DAY_HEADERS_SAT = ['Sat', 'Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri'];

export default function CalendarView({
  employees,
  dates,
  dateRemarks,
  currentDate,
  onShiftClick,
  onAddShift,
  canEdit,
  weekStartDay = 'monday',
  statusTypes,
  statusMaps,
  currentUserId,
  onSwapRequest,
  onChangeRequest,
}: CalendarViewProps) {
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const today = useMemo(() => toLocalDateStr(new Date()), []);

  // Build a flat map of dateStr -> all shifts for that day
  const shiftsByDate = useMemo(() => {
    const map: Record<string, Shift[]> = {};
    employees.forEach((emp) => {
      emp.shifts.forEach((s) => {
        if (!map[s.date]) map[s.date] = [];
        map[s.date].push(s);
      });
    });
    return map;
  }, [employees]);

  const remarkMap = useMemo(() => {
    const map: Record<string, DateRemark> = {};
    dateRemarks.forEach((r) => (map[r.date] = r));
    return map;
  }, [dateRemarks]);

  const dayHeaders = weekStartDay === 'monday'
    ? DAY_HEADERS_MON
    : weekStartDay === 'saturday'
      ? DAY_HEADERS_SAT
      : DAY_HEADERS_SUN;

  // Calendar grid: build 6x7 grid of dates for the current month
  const calendarDays = useMemo(() => {
    const year = currentDate.getFullYear();
    const month = currentDate.getMonth();
    const firstDayOfMonth = new Date(year, month, 1);
    const lastDayOfMonth = new Date(year, month + 1, 0);
    const dow = firstDayOfMonth.getDay(); // 0=Sun

    // Number of leading blank cells depends on week start day
    const startOffset = weekStartDay === 'monday'
      ? (dow + 6) % 7  // Mon-start: Mon=0, Tue=1, ... Sun=6
      : weekStartDay === 'saturday'
        ? (dow + 1) % 7  // Sat-start: Sat=0, Sun=1, Mon=2, ... Fri=6
        : dow;            // Sun-start: Sun=0, Mon=1, ... Sat=6

    const days: { date: Date; dateStr: string; isCurrentMonth: boolean }[] = [];

    // Fill leading days from previous month
    for (let i = startOffset - 1; i >= 0; i--) {
      const d = new Date(year, month, -i);
      days.push({ date: d, dateStr: toLocalDateStr(d), isCurrentMonth: false });
    }

    // Fill current month
    for (let d = 1; d <= lastDayOfMonth.getDate(); d++) {
      const dt = new Date(year, month, d);
      days.push({ date: dt, dateStr: toLocalDateStr(dt), isCurrentMonth: true });
    }

    // Fill trailing days to complete 6 rows
    const remaining = 42 - days.length;
    for (let i = 1; i <= remaining; i++) {
      const d = new Date(year, month + 1, i);
      days.push({ date: d, dateStr: toLocalDateStr(d), isCurrentMonth: false });
    }

    return days;
  }, [currentDate, weekStartDay]);

  // Rows of 7
  const weeks = useMemo(() => {
    const rows = [];
    for (let i = 0; i < calendarDays.length; i += 7) {
      rows.push(calendarDays.slice(i, i + 7));
    }
    return rows;
  }, [calendarDays]);

  const selectedShifts = selectedDate ? (shiftsByDate[selectedDate] ?? []) : [];
  const selectedRemark = selectedDate ? remarkMap[selectedDate] : undefined;

  return (
    <>
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        {/* Day headers */}
        <div className="grid grid-cols-7 border-b bg-gray-50">
          {dayHeaders.map((day) => (
            <div key={day} className="px-2 py-2 text-center text-xs font-semibold text-gray-500 uppercase">
              {day}
            </div>
          ))}
        </div>

        {/* Calendar grid */}
        <div className="grid grid-cols-7">
          {weeks.map((week, wi) =>
            week.map((day) => (
              <CalendarDayCell
                key={day.dateStr}
                date={day.date}
                dateStr={day.dateStr}
                shifts={shiftsByDate[day.dateStr] ?? []}
                remark={remarkMap[day.dateStr]}
                isToday={day.dateStr === today}
                isCurrentMonth={day.isCurrentMonth}
                onClick={(ds) => setSelectedDate(ds)}
                statusMaps={statusMaps}
              />
            ))
          )}
        </div>

        {/* Legend */}
        <div className="px-4 py-3 border-t bg-gray-50 flex flex-wrap items-center gap-4 text-[10px] text-gray-500">
          <span className="font-medium uppercase">Legend:</span>
          {(statusTypes && statusTypes.length > 0
            ? statusTypes.map((st) => ({ label: st.label, color: st.color }))
            : [
                { label: 'Scheduled', color: '#7c3aed' },
                { label: 'Rest Day', color: '#6b7280' },
                { label: 'Leave', color: '#ef4444' },
                { label: 'Vacation', color: '#3b82f6' },
                { label: 'Holiday Off', color: '#10b981' },
              ]
          )
            // Holidays are day markers rather than shift statuses, so they are
            // never in shift_status_types — but they colour cells, and every
            // colour on screen should be explained by the legend.
            .concat([
              { label: 'Regular holiday', color: '#fca5a5' },
              { label: 'Special holiday', color: '#fcd34d' },
            ])
            .map((item) => (
            <div key={item.label} className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-full" style={{ backgroundColor: item.color }} />
              <span>{item.label}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Day detail slide-over */}
      <DayDetailPanel
        isOpen={!!selectedDate}
        onClose={() => setSelectedDate(null)}
        dateStr={selectedDate ?? ''}
        shifts={selectedShifts}
        remark={selectedRemark}
        onShiftClick={(shift) => {
          setSelectedDate(null);
          onShiftClick(shift);
        }}
        onAddShift={(ds) => {
          setSelectedDate(null);
          onAddShift(ds);
        }}
        canEdit={canEdit}
        currentUserId={currentUserId}
        onSwapRequest={(shift) => {
          setSelectedDate(null);
          onSwapRequest?.(shift);
        }}
        onChangeRequest={(shift) => {
          setSelectedDate(null);
          onChangeRequest?.(shift);
        }}
      />
    </>
  );
}
