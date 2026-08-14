'use client';

import React, { useState, useEffect } from 'react';
import { Shift, ScheduleEmployee } from '@/types';
import { ScheduleConflict, ShiftBulkCreateResult, isScheduleConflictError } from '@/lib/api';
import { ALL_STATUSES, ALL_WORK_ARRANGEMENTS, isWorkStatus } from './scheduleHelpers';

interface ShiftModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSave: (data: Record<string, unknown>) => Promise<void>;
  onDelete?: () => Promise<void>;
  shift?: Shift | null;
  employees: ScheduleEmployee[];
  prefillEmployeeId?: number;
  prefillDate?: string;
  statusOptions?: { value: string; label: string }[];
  statusCategories?: Record<string, string>;
  onBulkSave?: (data: Record<string, unknown>) => Promise<ShiftBulkCreateResult>;
}

const PRESET_COLORS = [
  '#7c3aed', '#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#ec4899',
  '#8b5cf6', '#0ea5e9', '#14b8a6', '#f97316', '#6b7280', '#374151',
];

export default function ShiftModal({
  isOpen,
  onClose,
  onSave,
  onDelete,
  shift,
  employees,
  prefillEmployeeId,
  prefillDate,
  statusOptions,
  statusCategories,
  onBulkSave,
}: ShiftModalProps) {
  const isEdit = !!shift;
  const [activeTab, setActiveTab] = useState<'details' | 'notes'>('details');
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  // Conflicts surfaced from the backend: either a blocked single-shift create
  // (409) or the dates skipped by a bulk create.
  const [conflicts, setConflicts] = useState<ScheduleConflict[]>([]);
  const [conflictHeading, setConflictHeading] = useState('');
  // 'blocked' = a single create was rejected (nothing saved yet).
  // 'partial' = a bulk create saved some shifts and skipped others.
  const [conflictMode, setConflictMode] = useState<'blocked' | 'partial' | null>(null);

  // Date mode: single or range (create only)
  const [dateMode, setDateMode] = useState<'single' | 'range'>('single');

  // Single date fields
  const [employeeId, setEmployeeId] = useState<number>(0);
  const [date, setDate] = useState('');
  const [status, setStatus] = useState('scheduled');
  const [startTime, setStartTime] = useState('');
  const [endTime, setEndTime] = useState('');
  const [workArrangement, setWorkArrangement] = useState('');
  const [roleName, setRoleName] = useState('');
  const [color, setColor] = useState('');
  const [notes, setNotes] = useState('');
  const [remarks, setRemarks] = useState('');

  // Range fields
  const [rangeStartDate, setRangeStartDate] = useState('');
  const [rangeEndDate, setRangeEndDate] = useState('');
  const [selectedEmployeeIds, setSelectedEmployeeIds] = useState<number[]>([]);
  const [skipDays, setSkipDays] = useState<string[]>([]);
  const [skipHolidays, setSkipHolidays] = useState(false);

  const statuses = statusOptions ?? ALL_STATUSES;

  // Determine if the selected status is a "work" category
  const isWork = statusCategories
    ? isWorkStatus(status, statusCategories)
    : status === 'scheduled';

  useEffect(() => {
    if (!isOpen) return;
    let active = true;
    // Defer so the modal's form-reset state updates do not run synchronously in
    // the effect body (react-hooks/set-state-in-effect).
    void Promise.resolve().then(() => {
    if (!active) return;
    if (shift) {
      setEmployeeId(shift.employee_id);
      setDate(shift.date);
      setStatus(shift.status);
      setStartTime(shift.start_time?.substring(0, 5) ?? '');
      setEndTime(shift.end_time?.substring(0, 5) ?? '');
      setWorkArrangement(shift.work_arrangement ?? '');
      setRoleName(shift.role_name ?? '');
      setColor(shift.color ?? '');
      setNotes(shift.notes ?? '');
      setRemarks(shift.remarks ?? '');
      setDateMode('single');
    } else {
      setEmployeeId(prefillEmployeeId ?? 0);
      setDate(prefillDate ?? '');
      setStatus('scheduled');
      setStartTime('');
      setEndTime('');
      setWorkArrangement('onsite');
      setRoleName('');
      setColor('');
      setNotes('');
      setRemarks('');
      setDateMode('single');
      setRangeStartDate(prefillDate ?? '');
      setRangeEndDate('');
      setSelectedEmployeeIds(prefillEmployeeId ? [prefillEmployeeId] : []);
      setSkipDays([]);
      setSkipHolidays(false);
    }
    setActiveTab('details');
    setConflicts([]);
    setConflictHeading('');
    setConflictMode(null);
    });
    return () => {
      active = false;
    };
  }, [isOpen, shift, prefillEmployeeId, prefillDate]);

  if (!isOpen) return null;

  const handleSave = async (force = false) => {
    setSaving(true);
    setConflicts([]);
    setConflictHeading('');
    setConflictMode(null);
    try {
      if (!isEdit && dateMode === 'range' && onBulkSave) {
        const result = await onBulkSave({
          employee_ids: selectedEmployeeIds,
          start_date: rangeStartDate,
          end_date: rangeEndDate,
          status,
          start_time: isWork ? (startTime || null) : null,
          end_time: isWork ? (endTime || null) : null,
          work_arrangement: isWork ? (workArrangement || null) : null,
          role_name: roleName || null,
          color: color || null,
          notes: notes || null,
          remarks: remarks || null,
          skip_days: skipDays,
          skip_holidays: skipHolidays,
          force,
        });
        // Bulk create never fails on conflict — it skips and reports. If any
        // dates were skipped, keep the modal open and show them.
        if (result?.skipped_conflicts?.length) {
          setConflicts(result.skipped_conflicts);
          setConflictMode('partial');
          const created = result.created?.length ?? 0;
          setConflictHeading(
            `Created ${created} shift${created === 1 ? '' : 's'}. ` +
            `${result.skipped_conflicts.length} date(s) were skipped:`,
          );
        }
        // Nothing skipped → the parent closed the modal on success.
      } else {
        await onSave({
          employee_id: employeeId,
          date,
          status,
          start_time: isWork ? (startTime || null) : null,
          end_time: isWork ? (endTime || null) : null,
          work_arrangement: isWork ? (workArrangement || null) : null,
          role_name: roleName || null,
          color: color || null,
          notes: notes || null,
          remarks: remarks || null,
          force,
        });
      }
    } catch (err) {
      if (isScheduleConflictError(err)) {
        setConflicts(err.detail.conflicts);
        setConflictMode('blocked');
        setConflictHeading('This shift could not be scheduled:');
      } else {
        throw err;
      }
    } finally {
      setSaving(false);
    }
  };

  // A conflict set is overridable only when every item is forceable (i.e. no
  // approved-leave overlaps, which can never be forced).
  const allForceable = conflicts.length > 0 && conflicts.every((c) => c.forceable);

  const handleDelete = async () => {
    if (!onDelete) return;
    setDeleting(true);
    try {
      await onDelete();
    } finally {
      setDeleting(false);
    }
  };

  const toggleEmployeeSelection = (empId: number) => {
    setSelectedEmployeeIds((prev) =>
      prev.includes(empId) ? prev.filter((id) => id !== empId) : [...prev, empId],
    );
  };

  const tabClass = (tab: string) =>
    `px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
      activeTab === tab
        ? 'border-purple-600 text-purple-600'
        : 'border-transparent text-gray-500 hover:text-gray-700'
    }`;

  const canSubmit = dateMode === 'range'
    ? selectedEmployeeIds.length > 0 && rangeStartDate && rangeEndDate
    : (isEdit || employeeId) && date;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative bg-white rounded-xl shadow-2xl w-full max-w-lg mx-4 max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b">
          <h2 className="text-lg font-semibold text-gray-900">
            {isEdit ? 'Edit Shift' : 'New Shift'}
          </h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Tabs */}
        <div className="flex border-b px-6">
          <button className={tabClass('details')} onClick={() => setActiveTab('details')}>
            Shift Details
          </button>
          <button className={tabClass('notes')} onClick={() => setActiveTab('notes')}>
            Notes &amp; Color
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-4 space-y-4">
          {/* Conflict banner: leave overlaps and schedule-policy breaches */}
          {conflicts.length > 0 && (
            <div
              className={`rounded-lg border p-3 ${
                allForceable
                  ? 'border-amber-300 bg-amber-50'
                  : 'border-red-300 bg-red-50'
              }`}
            >
              <p className={`text-sm font-medium ${allForceable ? 'text-amber-800' : 'text-red-800'}`}>
                {conflictHeading}
              </p>
              <ul className="mt-2 space-y-1 max-h-40 overflow-y-auto">
                {conflicts.map((c, i) => (
                  <li key={`${c.employee_id}-${c.date}-${i}`} className="text-xs text-gray-700 flex gap-1.5">
                    <span className="text-gray-400">•</span>
                    <span>{c.message}</span>
                  </li>
                ))}
              </ul>
              {!allForceable && (
                <p className="mt-2 text-xs text-red-700">
                  Approved-leave conflicts cannot be overridden. Adjust the date or the leave first.
                </p>
              )}
            </div>
          )}

          {activeTab === 'details' && (
            <>
              {/* Date mode toggle (create only) */}
              {!isEdit && onBulkSave && (
                <div>
                  <label className="block text-xs font-medium text-gray-500 uppercase mb-1">Date Mode</label>
                  <div className="flex bg-gray-100 rounded-lg p-0.5 w-fit">
                    <button
                      type="button"
                      onClick={() => setDateMode('single')}
                      className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                        dateMode === 'single' ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500'
                      }`}
                    >
                      Single Date
                    </button>
                    <button
                      type="button"
                      onClick={() => setDateMode('range')}
                      className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                        dateMode === 'range' ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500'
                      }`}
                    >
                      Date Range
                    </button>
                  </div>
                </div>
              )}

              {/* Single date mode */}
              {dateMode === 'single' && (
                <>
                  {!isEdit && (
                    <div>
                      <label className="block text-xs font-medium text-gray-500 uppercase mb-1">Employee</label>
                      <select
                        value={employeeId}
                        onChange={(e) => setEmployeeId(Number(e.target.value))}
                        className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-purple-500 focus:border-transparent"
                      >
                        <option value={0}>Select employee...</option>
                        {employees.map((emp) => (
                          <option key={emp.employee_id} value={emp.employee_id}>
                            {emp.employee_name}
                          </option>
                        ))}
                      </select>
                    </div>
                  )}

                  <div>
                    <label className="block text-xs font-medium text-gray-500 uppercase mb-1">Date</label>
                    <input
                      type="date"
                      value={date}
                      onChange={(e) => setDate(e.target.value)}
                      className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-purple-500 focus:border-transparent"
                    />
                  </div>
                </>
              )}

              {/* Range date mode */}
              {dateMode === 'range' && (
                <>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="block text-xs font-medium text-gray-500 uppercase mb-1">Start Date</label>
                      <input
                        type="date"
                        value={rangeStartDate}
                        onChange={(e) => setRangeStartDate(e.target.value)}
                        className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-purple-500 focus:border-transparent"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-gray-500 uppercase mb-1">End Date</label>
                      <input
                        type="date"
                        value={rangeEndDate}
                        onChange={(e) => setRangeEndDate(e.target.value)}
                        className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-purple-500 focus:border-transparent"
                      />
                    </div>
                  </div>

                  {/* Employee multi-select */}
                  <div>
                    <label className="block text-xs font-medium text-gray-500 uppercase mb-1">
                      Employees ({selectedEmployeeIds.length} selected)
                    </label>
                    <div className="border border-gray-300 rounded-lg max-h-32 overflow-y-auto p-2 space-y-1">
                      {employees.map((emp) => (
                        <label key={emp.employee_id} className="flex items-center gap-2 cursor-pointer hover:bg-gray-50 px-2 py-1 rounded">
                          <input
                            type="checkbox"
                            checked={selectedEmployeeIds.includes(emp.employee_id)}
                            onChange={() => toggleEmployeeSelection(emp.employee_id)}
                            className="rounded border-gray-300 text-purple-600 focus:ring-purple-500"
                          />
                          <span className="text-sm text-gray-700">{emp.employee_name}</span>
                        </label>
                      ))}
                    </div>
                  </div>

                  {/* Skip days */}
                  <div>
                    <label className="block text-xs font-medium text-gray-500 uppercase mb-1">Skip Days</label>
                    <div className="flex flex-wrap gap-1.5">
                      {(['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'] as const).map((day) => {
                        const short = day.substring(0, 3);
                        const isActive = skipDays.includes(day);
                        return (
                          <button
                            key={day}
                            type="button"
                            onClick={() =>
                              setSkipDays((prev) =>
                                isActive ? prev.filter((d) => d !== day) : [...prev, day],
                              )
                            }
                            className={`px-2.5 py-1 text-xs font-medium rounded-md border transition-colors capitalize ${
                              isActive
                                ? 'bg-purple-600 text-white border-purple-600'
                                : 'bg-white text-gray-600 border-gray-300 hover:border-purple-300'
                            }`}
                          >
                            {short}
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  {/* Skip holidays */}
                  <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={skipHolidays}
                      onChange={(e) => setSkipHolidays(e.target.checked)}
                      className="rounded border-gray-300 text-purple-600 focus:ring-purple-500"
                    />
                    Skip Holidays
                  </label>
                </>
              )}

              {/* Status */}
              <div>
                <label className="block text-xs font-medium text-gray-500 uppercase mb-1">Status</label>
                <select
                  value={status}
                  onChange={(e) => setStatus(e.target.value)}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-purple-500 focus:border-transparent"
                >
                  {statuses.map((s) => (
                    <option key={s.value} value={s.value}>{s.label}</option>
                  ))}
                </select>
              </div>

              {/* Conditional time fields (only for "work" category) */}
              {isWork && (
                <>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="block text-xs font-medium text-gray-500 uppercase mb-1">Start Time</label>
                      <input
                        type="time"
                        value={startTime}
                        onChange={(e) => setStartTime(e.target.value)}
                        className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-purple-500 focus:border-transparent"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-gray-500 uppercase mb-1">End Time</label>
                      <input
                        type="time"
                        value={endTime}
                        onChange={(e) => setEndTime(e.target.value)}
                        className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-purple-500 focus:border-transparent"
                      />
                    </div>
                  </div>

                  <div>
                    <label className="block text-xs font-medium text-gray-500 uppercase mb-1">Work Arrangement</label>
                    <div className="flex flex-wrap gap-2 mt-1">
                      {ALL_WORK_ARRANGEMENTS.map((wa) => (
                        <button
                          key={wa.value}
                          type="button"
                          onClick={() => setWorkArrangement(wa.value)}
                          className={`px-3 py-1.5 text-xs font-medium rounded-lg border transition-colors ${
                            workArrangement === wa.value
                              ? 'bg-purple-600 text-white border-purple-600'
                              : 'bg-white text-gray-700 border-gray-300 hover:border-purple-300'
                          }`}
                        >
                          {wa.label}
                        </button>
                      ))}
                    </div>
                  </div>
                </>
              )}

              {/* Role Name */}
              <div>
                <label className="block text-xs font-medium text-gray-500 uppercase mb-1">Role Name</label>
                <input
                  type="text"
                  value={roleName}
                  onChange={(e) => setRoleName(e.target.value)}
                  placeholder="e.g. Shift Leader"
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-purple-500 focus:border-transparent"
                />
              </div>
            </>
          )}

          {activeTab === 'notes' && (
            <>
              {/* Color picker */}
              <div>
                <label className="block text-xs font-medium text-gray-500 uppercase mb-2">Color</label>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => setColor('')}
                    className={`w-7 h-7 rounded-full border-2 flex items-center justify-center text-xs ${
                      !color ? 'border-purple-500 ring-2 ring-purple-200' : 'border-gray-300'
                    }`}
                  >
                    <svg className="w-3 h-3 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                  {PRESET_COLORS.map((c) => (
                    <button
                      key={c}
                      type="button"
                      onClick={() => setColor(c)}
                      className={`w-7 h-7 rounded-full transition-all ${
                        color === c ? 'ring-2 ring-offset-2 ring-purple-500 scale-110' : 'hover:scale-105'
                      }`}
                      style={{ backgroundColor: c }}
                    />
                  ))}
                </div>
              </div>

              {/* Notes */}
              <div>
                <label className="block text-xs font-medium text-gray-500 uppercase mb-1">Notes</label>
                <textarea
                  rows={3}
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder="Additional notes..."
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-purple-500 focus:border-transparent resize-none"
                />
              </div>

              {/* Remarks */}
              <div>
                <label className="block text-xs font-medium text-gray-500 uppercase mb-1">Remarks</label>
                <textarea
                  rows={2}
                  value={remarks}
                  onChange={(e) => setRemarks(e.target.value)}
                  placeholder="Remarks..."
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-purple-500 focus:border-transparent resize-none"
                />
              </div>
            </>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-6 py-4 border-t bg-gray-50 rounded-b-xl">
          <div>
            {isEdit && onDelete && (
              <button
                onClick={handleDelete}
                disabled={deleting}
                className="px-4 py-2 text-sm font-medium text-red-600 hover:text-red-700 hover:bg-red-50 rounded-lg transition-colors"
              >
                {deleting ? 'Deleting...' : 'Delete Shift'}
              </button>
            )}
          </div>
          <div className="flex gap-2">
            <button
              onClick={onClose}
              className="px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100 rounded-lg transition-colors"
            >
              {conflictMode === 'partial' ? 'Close' : 'Cancel'}
            </button>
            {/* A bulk create already saved its non-conflicting shifts; offer a
                plain Done rather than re-submitting. */}
            {conflictMode === 'partial' ? (
              <button
                onClick={onClose}
                className="px-4 py-2 text-sm font-medium text-white bg-purple-600 hover:bg-purple-700 rounded-lg transition-colors"
              >
                Done
              </button>
            ) : (
              <>
                {/* Override only when every conflict is forceable (no leave). */}
                {conflictMode === 'blocked' && allForceable && (
                  <button
                    onClick={() => handleSave(true)}
                    disabled={saving}
                    className="px-4 py-2 text-sm font-medium text-white bg-amber-600 hover:bg-amber-700 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    Schedule Anyway
                  </button>
                )}
                <button
                  onClick={() => handleSave()}
                  disabled={saving || !canSubmit}
                  className="px-4 py-2 text-sm font-medium text-white bg-purple-600 hover:bg-purple-700 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                >
                  {saving && (
                    <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                  )}
                  {dateMode === 'range' ? 'Create Shifts' : isEdit ? 'Update Shift' : 'Create Shift'}
                </button>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
