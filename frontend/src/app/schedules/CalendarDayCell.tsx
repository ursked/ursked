'use client';

import React from 'react';
import { Shift, DateRemark } from '@/types';
import { getStatusColor, getStatusShort } from './scheduleHelpers';

interface CalendarDayCellProps {
  date: Date;
  dateStr: string;
  shifts: Shift[];
  remark?: DateRemark;
  isToday: boolean;
  isCurrentMonth: boolean;
  onClick: (dateStr: string) => void;
}

export default function CalendarDayCell({
  date,
  dateStr,
  shifts,
  remark,
  isToday,
  isCurrentMonth,
  onClick,
}: CalendarDayCellProps) {
  const isWeekend = date.getDay() === 0 || date.getDay() === 6;
  const dayNum = date.getDate();

  // Aggregate: count by status
  const statusCounts: Record<string, number> = {};
  shifts.forEach((s) => {
    statusCounts[s.status] = (statusCounts[s.status] || 0) + 1;
  });
  const statusEntries = Object.entries(statusCounts).slice(0, 4);
  const totalShifts = shifts.length;

  return (
    <button
      type="button"
      onClick={() => onClick(dateStr)}
      className={`relative w-full border border-gray-100 rounded-lg p-2 text-left transition-all hover:shadow-md hover:border-purple-200 min-h-[100px] flex flex-col ${
        !isCurrentMonth ? 'opacity-40' : ''
      } ${isToday ? 'ring-2 ring-purple-400 ring-offset-1 bg-purple-50/30' : 'bg-white'} ${
        remark?.is_holiday ? 'bg-red-50/40' : isWeekend && isCurrentMonth ? 'bg-gray-50/50' : ''
      }`}
    >
      {/* Day number */}
      <div className="flex items-center justify-between mb-1">
        <span
          className={`text-sm font-semibold ${
            isToday ? 'text-purple-700' : isCurrentMonth ? 'text-gray-800' : 'text-gray-400'
          }`}
        >
          {dayNum}
        </span>
        {totalShifts > 0 && (
          <span className="text-[10px] font-medium px-1.5 py-0.5 rounded-full bg-purple-100 text-purple-700">
            {totalShifts}
          </span>
        )}
      </div>

      {/* Remark */}
      {remark && (
        <div
          className={`text-[10px] truncate mb-1 px-1 py-0.5 rounded ${
            remark.is_holiday ? 'bg-red-100 text-red-700 font-medium' : 'bg-blue-50 text-blue-600'
          }`}
        >
          {remark.title}
        </div>
      )}

      {/* Status dots */}
      <div className="flex-1 flex flex-col gap-0.5 mt-auto">
        {statusEntries.map(([status, count]) => (
          <div key={status} className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: getStatusColor(status) }} />
            <span className="text-[10px] text-gray-600 truncate">
              {count} {getStatusShort(status)}
            </span>
          </div>
        ))}
        {Object.keys(statusCounts).length > 4 && (
          <span className="text-[9px] text-gray-400">+{Object.keys(statusCounts).length - 4} more</span>
        )}
      </div>
    </button>
  );
}
