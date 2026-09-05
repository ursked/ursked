'use client';

import React from 'react';
import { Shift, DateRemark } from '@/types';
import { getStatusLabel, getStatusBgClass, formatShiftTime, WORK_ARRANGEMENT_LABELS } from './scheduleHelpers';

interface DayDetailPanelProps {
  isOpen: boolean;
  onClose: () => void;
  dateStr: string;
  shifts: Shift[];
  remark?: DateRemark;
  onShiftClick: (shift: Shift) => void;
  onAddShift: (dateStr: string) => void;
  canEdit: boolean;
  currentUserId?: number;
  onSwapRequest?: (shift: Shift) => void;
  onChangeRequest?: (shift: Shift) => void;
}

const DAY_NAMES = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
const MONTH_NAMES = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

export default function DayDetailPanel({
  isOpen,
  onClose,
  dateStr,
  shifts,
  remark,
  onShiftClick,
  onAddShift,
  canEdit,
  currentUserId,
  onSwapRequest,
  onChangeRequest,
}: DayDetailPanelProps) {
  if (!isOpen) return null;

  const d = new Date(dateStr + 'T00:00:00');
  const dayName = DAY_NAMES[d.getDay()];
  const monthName = MONTH_NAMES[d.getMonth()];
  const formatted = `${dayName}, ${monthName} ${d.getDate()}, ${d.getFullYear()}`;

  // Group shifts by employee
  const byEmployee: Record<string, Shift[]> = {};
  shifts.forEach((s) => {
    const name = s.employee_name || `Employee #${s.employee_id}`;
    if (!byEmployee[name]) byEmployee[name] = [];
    byEmployee[name].push(s);
  });

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />
      <div className="relative w-full max-w-md bg-white shadow-2xl flex flex-col animate-slide-in-right">
        {/* Header */}
        <div className="px-6 py-4 border-b flex items-center justify-between">
          <div>
            <h3 className="text-lg font-semibold text-gray-900">{formatted}</h3>
            <p className="text-sm text-gray-500">{shifts.length} shift{shifts.length !== 1 ? 's' : ''}</p>
          </div>
          <button onClick={onClose} className="p-1 rounded-lg hover:bg-gray-100 text-gray-500">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Remark banner */}
        {remark && (
          <div className={`mx-6 mt-4 px-4 py-2 rounded-lg ${
            remark.is_holiday ? 'bg-red-50 border border-red-200' : 'bg-blue-50 border border-blue-200'
          }`}>
            <p className={`text-sm font-medium ${remark.is_holiday ? 'text-red-700' : 'text-blue-700'}`}>
              {remark.title}
            </p>
            {remark.description && (
              <p className={`text-xs mt-0.5 ${remark.is_holiday ? 'text-red-500' : 'text-blue-500'}`}>
                {remark.description}
              </p>
            )}
          </div>
        )}

        {/* Shifts list */}
        <div className="flex-1 overflow-y-auto px-6 py-4">
          {Object.entries(byEmployee).length === 0 ? (
            <div className="text-center py-8">
              <svg className="w-10 h-10 mx-auto text-gray-500 mb-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
              </svg>
              <p className="text-sm text-gray-500">No shifts scheduled</p>
            </div>
          ) : (
            <div className="space-y-4">
              {Object.entries(byEmployee).map(([name, empShifts]) => (
                <div key={name}>
                  <div className="flex items-center gap-2 mb-2">
                    <div className="w-6 h-6 rounded-full bg-gradient-to-br from-purple-400 to-purple-600 flex items-center justify-center text-white text-[9px] font-semibold">
                      {name.split(' ').map(n => n[0]).join('').substring(0, 2)}
                    </div>
                    <span className="text-sm font-medium text-gray-800">{name}</span>
                  </div>
                  <div className="space-y-1.5 pl-8">
                    {empShifts.map((shift) => {
                      const isOwn = currentUserId === shift.employee_id;
                      return (
                        <div key={shift.id}>
                          <button
                            onClick={() => onShiftClick(shift)}
                            className="w-full text-left p-2.5 rounded-lg border border-gray-200 hover:border-purple-300 hover:shadow-sm transition-all"
                          >
                            <div className="flex items-center justify-between">
                              <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${getStatusBgClass(shift.status)}`}>
                                {getStatusLabel(shift.status)}
                              </span>
                              {shift.work_arrangement && (
                                <span className="text-[10px] text-gray-500">
                                  {WORK_ARRANGEMENT_LABELS[shift.work_arrangement] ?? shift.work_arrangement}
                                </span>
                              )}
                            </div>
                            {formatShiftTime(shift.start_time, shift.end_time) && (
                              <p className="text-xs text-gray-600 mt-1">
                                {formatShiftTime(shift.start_time, shift.end_time)}
                              </p>
                            )}
                            {shift.notes && (
                              <p className="text-[10px] text-gray-500 mt-1 truncate">{shift.notes}</p>
                            )}
                          </button>
                          {isOwn && onSwapRequest && onChangeRequest && (
                            <div className="flex gap-1.5 mt-1">
                              <button
                                onClick={() => onSwapRequest(shift)}
                                className="flex-1 py-1 text-[10px] font-medium text-blue-700 bg-blue-50 rounded hover:bg-blue-100 transition-colors"
                              >
                                Swap With...
                              </button>
                              <button
                                onClick={() => onChangeRequest(shift)}
                                className="flex-1 py-1 text-[10px] font-medium text-orange-700 bg-orange-50 rounded hover:bg-orange-100 transition-colors"
                              >
                                Request Change
                              </button>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        {canEdit && (
          <div className="px-6 py-3 border-t">
            <button
              onClick={() => onAddShift(dateStr)}
              className="w-full py-2 text-sm font-medium text-purple-700 bg-purple-50 rounded-lg hover:bg-purple-100 transition-colors flex items-center justify-center gap-1.5"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
              </svg>
              Add Shift for {dateStr}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
