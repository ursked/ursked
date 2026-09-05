'use client';

import React, { useMemo, useState } from 'react';
import { ScheduleEmployee, Shift, DateRemark } from '@/types';
import { resolveStatus, formatShiftTime, WORK_ARRANGEMENT_LABELS, type StatusMaps } from './scheduleHelpers';

interface DayViewProps {
  employees: ScheduleEmployee[];
  dates: string[];
  dateRemarks: DateRemark[];
  onShiftClick: (shift: Shift) => void;
  onCellClick: (employeeId: number, dateStr: string) => void;
  canEdit: boolean;
  statusMaps?: StatusMaps;
  currentUserId?: number;
  onSwapRequest?: (shift: Shift) => void;
  onChangeRequest?: (shift: Shift) => void;
}

const DAY_NAMES = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
const DAY_SHORT = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

function getGreeting(): string {
  const h = new Date().getHours();
  if (h < 12) return 'Good Morning';
  if (h < 17) return 'Good Afternoon';
  return 'Good Evening';
}

function formatDayDate(dateStr: string): string {
  if (!dateStr) return '';
  const d = new Date(dateStr + 'T00:00:00');
  return `${DAY_NAMES[d.getDay()]}, ${d.toLocaleDateString('en-US', { month: 'long', day: 'numeric' })}`;
}

function formatDayDateShort(dateStr: string): string {
  if (!dateStr) return '';
  const d = new Date(dateStr + 'T00:00:00');
  return `${DAY_SHORT[d.getDay()]}, ${d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}`;
}

export default function DayView({
  employees,
  dates,
  dateRemarks,
  onShiftClick,
  onCellClick,
  canEdit,
  currentUserId,
  onSwapRequest,
  onChangeRequest,
  statusMaps,
}: DayViewProps) {
  const [teamExpanded, setTeamExpanded] = useState(false);

  const todayStr = dates[0] ?? '';
  const tomorrowStr = dates[1] ?? '';

  const todayRemark = useMemo(
    () => dateRemarks.find((r) => r.date === todayStr),
    [dateRemarks, todayStr],
  );
  const tomorrowRemark = useMemo(
    () => dateRemarks.find((r) => r.date === tomorrowStr),
    [dateRemarks, tomorrowStr],
  );

  // Find current user's employee record
  const myEmployee = useMemo(
    () => employees.find((e) => e.employee_id === currentUserId),
    [employees, currentUserId],
  );

  // My shifts for today and tomorrow
  const myTodayShifts = useMemo(
    () => myEmployee?.shifts.filter((s) => s.date === todayStr) ?? [],
    [myEmployee, todayStr],
  );
  const myTomorrowShifts = useMemo(
    () => myEmployee?.shifts.filter((s) => s.date === tomorrowStr) ?? [],
    [myEmployee, tomorrowStr],
  );

  // Team: all other employees with their today shifts
  const teamToday = useMemo(() => {
    return employees
      .filter((e) => e.employee_id !== currentUserId)
      .map((emp) => ({
        ...emp,
        dayShifts: emp.shifts.filter((s) => s.date === todayStr),
      }));
  }, [employees, currentUserId, todayStr]);

  const teamShiftCount = teamToday.reduce((sum, e) => sum + e.dayShifts.length, 0);

  const greeting = useMemo(() => getGreeting(), []);
  const firstName = myEmployee?.employee_name?.split(' ')[0] ?? '';

  return (
    <div className="space-y-4 max-w-lg mx-auto">
      {/* Greeting & Date */}
      <div className="px-1">
        <h2 className="text-xl font-bold text-gray-900">
          {greeting}{firstName ? `, ${firstName}` : ''}
        </h2>
        <p className="text-sm text-gray-500 mt-0.5">{formatDayDate(todayStr)}</p>
        {todayRemark && (
          <div className={`inline-block mt-2 px-3 py-1 rounded-full text-xs font-medium ${
            todayRemark.is_holiday ? 'bg-red-100 text-red-700' : 'bg-blue-100 text-blue-700'
          }`}>
            {todayRemark.title}
          </div>
        )}
      </div>

      {/* MY SCHEDULE TODAY — Hero Card */}
      <div className="bg-gradient-to-br from-purple-600 to-purple-800 rounded-2xl p-5 text-white shadow-lg">
        <div className="flex items-center gap-2 mb-3">
          <svg className="w-5 h-5 text-purple-200" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 012.25-2.25h13.5A2.25 2.25 0 0121 7.5v11.25m-18 0A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75m-18 0v-7.5A2.25 2.25 0 015.25 9h13.5A2.25 2.25 0 0121 11.25v7.5" />
          </svg>
          <span className="text-sm font-medium text-purple-200 uppercase tracking-wide">My Schedule Today</span>
        </div>

        {myTodayShifts.length === 0 ? (
          <div className="py-4 text-center">
            <div className="w-14 h-14 mx-auto mb-3 rounded-full bg-white/10 flex items-center justify-center">
              <svg className="w-7 h-7 text-purple-200" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M15.182 15.182a4.5 4.5 0 01-6.364 0M21 12a9 9 0 11-18 0 9 9 0 0118 0zM9.75 9.75c0 .414-.168.75-.375.75S9 10.164 9 9.75 9.168 9 9.375 9s.375.336.375.75zm-.375 0h.008v.015h-.008V9.75zm5.625 0c0 .414-.168.75-.375.75s-.375-.336-.375-.75.168-.75.375-.75.375.336.375.75zm-.375 0h.008v.015h-.008V9.75z" />
              </svg>
            </div>
            <p className="text-base font-medium text-white">No shift scheduled</p>
            <p className="text-sm text-purple-200 mt-1">Enjoy your day off!</p>
            {canEdit && (
              <button
                onClick={() => myEmployee && onCellClick(myEmployee.employee_id, todayStr)}
                className="mt-3 px-4 py-2 text-sm font-medium bg-white/15 hover:bg-white/25 rounded-xl transition-colors"
              >
                + Add Shift
              </button>
            )}
          </div>
        ) : (
          <div className="space-y-3">
            {myTodayShifts.map((shift) => (
              <div key={shift.id}>
                <button
                  onClick={() => onShiftClick(shift)}
                  className="w-full text-left bg-white/10 hover:bg-white/15 rounded-xl p-4 transition-colors"
                >
                  <div className="flex items-center justify-between mb-2">
                    <span className={`text-xs font-semibold px-2.5 py-1 rounded-full ${resolveStatus(shift.status, statusMaps).bgClass}`}>
                      {resolveStatus(shift.status, statusMaps).label}
                    </span>
                    {shift.work_arrangement && (
                      <span className="text-xs text-purple-200 bg-white/10 px-2 py-0.5 rounded-full">
                        {WORK_ARRANGEMENT_LABELS[shift.work_arrangement] ?? shift.work_arrangement}
                      </span>
                    )}
                  </div>

                  {formatShiftTime(shift.start_time, shift.end_time) && (
                    <div className="flex items-center gap-2 mb-1">
                      <svg className="w-4 h-4 text-purple-200" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" />
                      </svg>
                      <span className="text-lg font-semibold text-white">
                        {formatShiftTime(shift.start_time, shift.end_time)}
                      </span>
                    </div>
                  )}

                  {shift.role_name && (
                    <p className="text-sm text-purple-200 mt-1">{shift.role_name}</p>
                  )}
                  {shift.notes && (
                    <p className="text-xs text-purple-300 mt-1 truncate">{shift.notes}</p>
                  )}
                </button>

                {/* Swap / Change actions */}
                {onSwapRequest && onChangeRequest && (
                  <div className="flex gap-2 mt-2">
                    <button
                      onClick={() => onSwapRequest(shift)}
                      className="flex-1 py-2.5 text-xs font-medium text-white bg-white/10 hover:bg-white/20 rounded-xl transition-colors flex items-center justify-center gap-1.5"
                    >
                      <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" d="M7.5 21L3 16.5m0 0L7.5 12M3 16.5h13.5m0-13.5L21 7.5m0 0L16.5 12M21 7.5H7.5" />
                      </svg>
                      Swap
                    </button>
                    <button
                      onClick={() => onChangeRequest(shift)}
                      className="flex-1 py-2.5 text-xs font-medium text-white bg-white/10 hover:bg-white/20 rounded-xl transition-colors flex items-center justify-center gap-1.5"
                    >
                      <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931z" />
                      </svg>
                      Request Change
                    </button>
                  </div>
                )}
              </div>
            ))}
            {canEdit && (
              <button
                onClick={() => myEmployee && onCellClick(myEmployee.employee_id, todayStr)}
                className="w-full py-2 text-xs font-medium text-purple-200 hover:text-white bg-white/5 hover:bg-white/10 rounded-xl transition-colors"
              >
                + Add another shift
              </button>
            )}
          </div>
        )}
      </div>

      {/* TOMORROW PREVIEW */}
      {tomorrowStr && (
        <div className="bg-white rounded-2xl border border-gray-200 p-4 shadow-sm">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <svg className="w-4 h-4 text-gray-500" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 3.75v4.5m0-4.5h4.5m-4.5 0L9 9M3.75 20.25v-4.5m0 4.5h4.5m-4.5 0L9 15M20.25 3.75h-4.5m4.5 0v4.5m0-4.5L15 9m5.25 11.25h-4.5m4.5 0v-4.5m0 4.5L15 15" />
              </svg>
              <span className="text-sm font-semibold text-gray-700">Tomorrow</span>
              <span className="text-xs text-gray-500">{formatDayDateShort(tomorrowStr)}</span>
            </div>
            {tomorrowRemark && (
              <span className={`text-[10px] font-medium px-2 py-0.5 rounded-full ${
                tomorrowRemark.is_holiday ? 'bg-red-100 text-red-700' : 'bg-blue-100 text-blue-700'
              }`}>
                {tomorrowRemark.title}
              </span>
            )}
          </div>

          {myTomorrowShifts.length === 0 ? (
            <div className="flex items-center gap-3 py-2 px-3 bg-gray-50 rounded-xl">
              <div className="w-8 h-8 rounded-full bg-gray-100 flex items-center justify-center flex-shrink-0">
                <svg className="w-4 h-4 text-gray-500" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M15.182 15.182a4.5 4.5 0 01-6.364 0M21 12a9 9 0 11-18 0 9 9 0 0118 0zM9.75 9.75c0 .414-.168.75-.375.75S9 10.164 9 9.75 9.168 9 9.375 9s.375.336.375.75zm-.375 0h.008v.015h-.008V9.75zm5.625 0c0 .414-.168.75-.375.75s-.375-.336-.375-.75.168-.75.375-.75.375.336.375.75zm-.375 0h.008v.015h-.008V9.75z" />
                </svg>
              </div>
              <div>
                <p className="text-sm text-gray-500">No shift scheduled</p>
                <p className="text-xs text-gray-500">Day off</p>
              </div>
            </div>
          ) : (
            <div className="space-y-2">
              {myTomorrowShifts.map((shift) => (
                <div key={shift.id} className="flex items-center gap-3 py-2 px-3 bg-gray-50 rounded-xl">
                  <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full flex-shrink-0 ${resolveStatus(shift.status, statusMaps).bgClass}`}>
                    {resolveStatus(shift.status, statusMaps).label}
                  </span>
                  <div className="flex-1 min-w-0">
                    {formatShiftTime(shift.start_time, shift.end_time) ? (
                      <p className="text-sm font-medium text-gray-800">{formatShiftTime(shift.start_time, shift.end_time)}</p>
                    ) : (
                      <p className="text-sm text-gray-500">All day</p>
                    )}
                    {shift.work_arrangement && (
                      <p className="text-xs text-gray-500">
                        {WORK_ARRANGEMENT_LABELS[shift.work_arrangement] ?? shift.work_arrangement}
                      </p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* TEAM OVERVIEW — Collapsible */}
      <div className="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden">
        <button
          onClick={() => setTeamExpanded((prev) => !prev)}
          className="w-full px-4 py-3.5 flex items-center justify-between hover:bg-gray-50 transition-colors"
        >
          <div className="flex items-center gap-2">
            <svg className="w-4 h-4 text-gray-500" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M18 18.72a9.094 9.094 0 003.741-.479 3 3 0 00-4.682-2.72m.94 3.198l.001.031c0 .225-.012.447-.037.666A11.944 11.944 0 0112 21c-2.17 0-4.207-.576-5.963-1.584A6.062 6.062 0 016 18.719m12 0a5.971 5.971 0 00-.941-3.197m0 0A5.995 5.995 0 0012 12.75a5.995 5.995 0 00-5.058 2.772m0 0a3 3 0 00-4.681 2.72 8.986 8.986 0 003.74.477m.94-3.197a5.971 5.971 0 00-.94 3.197M15 6.75a3 3 0 11-6 0 3 3 0 016 0zm6 3a2.25 2.25 0 11-4.5 0 2.25 2.25 0 014.5 0zm-13.5 0a2.25 2.25 0 11-4.5 0 2.25 2.25 0 014.5 0z" />
            </svg>
            <span className="text-sm font-semibold text-gray-700">Team Today</span>
            <span className="text-xs text-gray-700 bg-gray-100 px-2 py-0.5 rounded-full">
              {teamToday.length} people &middot; {teamShiftCount} shift{teamShiftCount !== 1 ? 's' : ''}
            </span>
          </div>
          <svg
            className={`w-4 h-4 text-gray-500 transition-transform ${teamExpanded ? 'rotate-180' : ''}`}
            fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor"
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
          </svg>
        </button>

        {teamExpanded && (
          <div className="border-t border-gray-100 divide-y divide-gray-50">
            {teamToday.length === 0 ? (
              <div className="px-4 py-6 text-center">
                <p className="text-sm text-gray-500">No team members found</p>
              </div>
            ) : (
              teamToday.map((emp) => (
                <div key={emp.employee_id} className="px-4 py-3 hover:bg-gray-50 transition-colors">
                  <div className="flex items-center gap-3">
                    {/* Avatar */}
                    <div className="w-8 h-8 rounded-full bg-gradient-to-br from-gray-300 to-gray-400 flex items-center justify-center text-white text-[10px] font-semibold flex-shrink-0">
                      {emp.employee_name.split(' ').map((n) => n[0]).join('').substring(0, 2)}
                    </div>

                    {/* Info */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-gray-800 truncate">{emp.employee_name}</span>
                        {emp.section_name && (
                          <span className="text-[10px] text-gray-700 bg-gray-100 px-1.5 py-0.5 rounded flex-shrink-0">{emp.section_name}</span>
                        )}
                      </div>
                      {emp.dayShifts.length === 0 ? (
                        <p className="text-xs text-gray-500 mt-0.5">No shift</p>
                      ) : (
                        <div className="flex flex-wrap items-center gap-1.5 mt-0.5">
                          {emp.dayShifts.map((shift) => (
                            <button
                              key={shift.id}
                              onClick={() => onShiftClick(shift)}
                              className="inline-flex items-center gap-1 text-xs"
                            >
                              <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded-full ${resolveStatus(shift.status, statusMaps).bgClass}`}>
                                {resolveStatus(shift.status, statusMaps).label}
                              </span>
                              {formatShiftTime(shift.start_time, shift.end_time) && (
                                <span className="text-gray-500">{formatShiftTime(shift.start_time, shift.end_time)}</span>
                              )}
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        )}
      </div>

      {/* Editor: Quick add for any employee */}
      {canEdit && teamExpanded && (
        <div className="text-center pb-4">
          <button
            onClick={() => onCellClick(0, todayStr)}
            className="text-xs font-medium text-purple-600 hover:text-purple-800 transition-colors"
          >
            + Add shift for an employee
          </button>
        </div>
      )}
    </div>
  );
}
