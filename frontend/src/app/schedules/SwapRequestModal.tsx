'use client';

import React, { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { ScheduleEmployee, Shift } from '@/types';
import { useAuth } from '@/contexts/AuthContext';
import { getStatusLabel, formatShiftTime, WORK_ARRANGEMENT_LABELS } from './scheduleHelpers';

interface SwapRequestModalProps {
  isOpen: boolean;
  onClose: () => void;
  shift: Shift;
  dateStr: string;
  employees: ScheduleEmployee[];
}

export default function SwapRequestModal({
  isOpen,
  onClose,
  shift,
  dateStr,
  employees,
}: SwapRequestModalProps) {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [targetEmployeeId, setTargetEmployeeId] = useState<number | ''>('');
  const [useRange, setUseRange] = useState(false);
  const [endDate, setEndDate] = useState('');
  const [reason, setReason] = useState('');
  const [error, setError] = useState('');

  const otherEmployees = employees.filter(
    (e) => e.employee_id !== (user?.id ?? shift.employee_id),
  );

  // Find target employee's shifts for the selected date
  const targetEmployee = targetEmployeeId
    ? employees.find((e) => e.employee_id === targetEmployeeId)
    : null;
  const targetShifts = targetEmployee
    ? targetEmployee.shifts.filter((s) => s.date === dateStr)
    : [];

  const createMutation = useMutation({
    mutationFn: (data: Parameters<typeof api.createScheduleChangeRequest>[0]) =>
      api.createScheduleChangeRequest(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['my-schedule-requests'] });
      queryClient.invalidateQueries({ queryKey: ['pending-schedule-approvals'] });
      onClose();
      resetForm();
    },
    onError: (err: Error) => setError(err.message),
  });

  const resetForm = () => {
    setTargetEmployeeId('');
    setUseRange(false);
    setEndDate('');
    setReason('');
    setError('');
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!targetEmployeeId) {
      setError('Please select an employee to swap with');
      return;
    }
    setError('');
    createMutation.mutate({
      request_type: 'swap',
      date: dateStr,
      end_date: useRange && endDate ? endDate : undefined,
      target_employee_id: targetEmployeeId as number,
      reason: reason || undefined,
    });
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />
      <div className="relative bg-white rounded-xl shadow-2xl w-full max-w-lg mx-4 max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="px-6 py-4 border-b flex items-center justify-between">
          <div>
            <h3 className="text-lg font-semibold text-gray-900">Swap Schedule</h3>
            <p className="text-sm text-gray-500">Request to swap your shift with another employee</p>
          </div>
          <button onClick={onClose} className="p-1 rounded-lg hover:bg-gray-100 text-gray-400">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <form onSubmit={handleSubmit} className="px-6 py-4 space-y-4">
          {/* Your current shift */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Your Shift on {dateStr}</label>
            <div className="p-3 rounded-lg bg-purple-50 border border-purple-200">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-purple-800">
                  {getStatusLabel(shift.status)}
                </span>
                {formatShiftTime(shift.start_time, shift.end_time) && (
                  <span className="text-sm text-purple-600">
                    {formatShiftTime(shift.start_time, shift.end_time)}
                  </span>
                )}
                {shift.work_arrangement && (
                  <span className="text-xs px-1.5 py-0.5 rounded bg-purple-100 text-purple-700">
                    {WORK_ARRANGEMENT_LABELS[shift.work_arrangement] ?? shift.work_arrangement}
                  </span>
                )}
              </div>
            </div>
          </div>

          {/* Target employee */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Swap With</label>
            <select
              value={targetEmployeeId}
              onChange={(e) => setTargetEmployeeId(e.target.value ? Number(e.target.value) : '')}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-purple-500 focus:border-transparent"
            >
              <option value="">Select employee...</option>
              {otherEmployees.map((emp) => (
                <option key={emp.employee_id} value={emp.employee_id}>
                  {emp.employee_name}{emp.section_name ? ` (${emp.section_name})` : ''}
                </option>
              ))}
            </select>
          </div>

          {/* Target's shift preview */}
          {targetEmployee && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                {targetEmployee.employee_name}&apos;s Shift on {dateStr}
              </label>
              {targetShifts.length > 0 ? (
                <div className="p-3 rounded-lg bg-blue-50 border border-blue-200 space-y-1">
                  {targetShifts.map((ts) => (
                    <div key={ts.id} className="flex items-center gap-2">
                      <span className="text-sm font-medium text-blue-800">
                        {getStatusLabel(ts.status)}
                      </span>
                      {formatShiftTime(ts.start_time, ts.end_time) && (
                        <span className="text-sm text-blue-600">
                          {formatShiftTime(ts.start_time, ts.end_time)}
                        </span>
                      )}
                      {ts.work_arrangement && (
                        <span className="text-xs px-1.5 py-0.5 rounded bg-blue-100 text-blue-700">
                          {WORK_ARRANGEMENT_LABELS[ts.work_arrangement] ?? ts.work_arrangement}
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="p-3 rounded-lg bg-gray-50 border border-gray-200 text-sm text-gray-500">
                  No shift scheduled for this date
                </div>
              )}
            </div>
          )}

          {/* Swap preview */}
          {targetEmployee && targetShifts.length > 0 && (
            <div className="p-3 rounded-lg bg-amber-50 border border-amber-200">
              <p className="text-xs font-medium text-amber-800 mb-1">After swap:</p>
              <div className="text-xs text-amber-700 space-y-0.5">
                <p>You will get: {getStatusLabel(targetShifts[0].status)} {formatShiftTime(targetShifts[0].start_time, targetShifts[0].end_time)}</p>
                <p>{targetEmployee.employee_name} will get: {getStatusLabel(shift.status)} {formatShiftTime(shift.start_time, shift.end_time)}</p>
              </div>
            </div>
          )}

          {/* Date range */}
          <div>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={useRange}
                onChange={(e) => setUseRange(e.target.checked)}
                className="rounded border-gray-300 text-purple-600 focus:ring-purple-500"
              />
              <span className="text-sm text-gray-700">Apply to date range</span>
            </label>
            {useRange && (
              <input
                type="date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
                min={dateStr}
                className="mt-2 w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-purple-500 focus:border-transparent"
                placeholder="End date"
              />
            )}
          </div>

          {/* Reason */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Reason (optional)</label>
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={3}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-purple-500 focus:border-transparent resize-none"
              placeholder="Why do you need to swap schedules?"
            />
          </div>

          {/* Error */}
          {error && (
            <div className="p-3 rounded-lg bg-red-50 border border-red-200 text-sm text-red-700">
              {error}
            </div>
          )}

          {/* Actions */}
          <div className="flex items-center gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={createMutation.isPending || !targetEmployeeId}
              className="flex-1 px-4 py-2 text-sm font-medium text-white bg-purple-600 rounded-lg hover:bg-purple-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {createMutation.isPending ? 'Submitting...' : 'Submit Request'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
