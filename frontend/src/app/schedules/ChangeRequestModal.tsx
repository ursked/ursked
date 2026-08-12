'use client';

import React, { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { Shift, ShiftStatusType } from '@/types';
import { getStatusLabel, formatShiftTime, WORK_ARRANGEMENT_LABELS } from './scheduleHelpers';
import { convertShiftTime } from '@/lib/scheduleTimezone';

interface ChangeRequestModalProps {
  isOpen: boolean;
  onClose: () => void;
  shift: Shift;
  dateStr: string;
  statusOptions?: { value: string; label: string }[];
  /** Organization (master-schedule) timezone — the source of truth for requests. */
  orgTz?: string;
  /** The viewer's chosen display timezone (only used to show a read-only hint). */
  viewerTz?: string;
}

export default function ChangeRequestModal({
  isOpen,
  onClose,
  shift,
  dateStr,
  statusOptions,
  orgTz,
  viewerTz,
}: ChangeRequestModalProps) {
  const queryClient = useQueryClient();
  const [useRange, setUseRange] = useState(false);
  const [endDate, setEndDate] = useState('');
  const [requestedStartTime, setRequestedStartTime] = useState(
    shift.start_time ? shift.start_time.substring(0, 5) : '',
  );
  const [requestedEndTime, setRequestedEndTime] = useState(
    shift.end_time ? shift.end_time.substring(0, 5) : '',
  );
  const [requestedStatus, setRequestedStatus] = useState(shift.status);
  const [requestedWorkArrangement, setRequestedWorkArrangement] = useState(
    shift.work_arrangement || '',
  );
  const [reason, setReason] = useState('');
  const [error, setError] = useState('');

  const createMutation = useMutation({
    mutationFn: (data: Parameters<typeof api.createScheduleChangeRequest>[0]) =>
      api.createScheduleChangeRequest(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['my-schedule-requests'] });
      queryClient.invalidateQueries({ queryKey: ['pending-schedule-approvals'] });
      onClose();
    },
    onError: (err: Error) => setError(err.message),
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    // Build only changed fields
    const data: Parameters<typeof api.createScheduleChangeRequest>[0] = {
      request_type: 'change',
      date: dateStr,
      end_date: useRange && endDate ? endDate : undefined,
      reason: reason || undefined,
    };

    const currentStart = shift.start_time ? shift.start_time.substring(0, 5) : '';
    const currentEnd = shift.end_time ? shift.end_time.substring(0, 5) : '';

    if (requestedStartTime && requestedStartTime !== currentStart) {
      data.requested_start_time = requestedStartTime + ':00';
    }
    if (requestedEndTime && requestedEndTime !== currentEnd) {
      data.requested_end_time = requestedEndTime + ':00';
    }
    if (requestedStatus && requestedStatus !== shift.status) {
      data.requested_status = requestedStatus;
    }
    if (requestedWorkArrangement && requestedWorkArrangement !== (shift.work_arrangement || '')) {
      data.requested_work_arrangement = requestedWorkArrangement;
    }

    // Ensure at least one change
    if (
      !data.requested_start_time &&
      !data.requested_end_time &&
      !data.requested_status &&
      !data.requested_work_arrangement
    ) {
      setError('Please change at least one field from the current values');
      return;
    }

    createMutation.mutate(data);
  };

  if (!isOpen) return null;

  const workArrangements = [
    { value: 'onsite', label: 'On-site' },
    { value: 'wfh', label: 'Work From Home' },
    { value: 'hybrid', label: 'Hybrid' },
    { value: 'ob', label: 'Official Business' },
  ];

  // The schedule is authored in the organization (master) timezone, and requests
  // are filed against it. When the viewer reads the grid in a different tz, show
  // a read-only "your local time" hint so they can reconcile the numbers — but
  // the editable fields below stay in organization time (never converted).
  const tzDiffers = !!(orgTz && viewerTz && orgTz !== viewerTz);
  let localHint = '';
  if (tzDiffers && shift.start_time) {
    const cs = convertShiftTime(dateStr, shift.start_time, orgTz, viewerTz);
    const ce = shift.end_time ? convertShiftTime(dateStr, shift.end_time, orgTz, viewerTz) : null;
    if (cs) {
      const roll = cs.dayShift ? (cs.dayShift > 0 ? ' (+1d)' : ' (-1d)') : '';
      localHint = ce ? `${cs.time}–${ce.time}${roll}` : `${cs.time}${roll}`;
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />
      <div className="relative bg-white rounded-xl shadow-2xl w-full max-w-lg mx-4 max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="px-6 py-4 border-b flex items-center justify-between">
          <div>
            <h3 className="text-lg font-semibold text-gray-900">Request Schedule Change</h3>
            <p className="text-sm text-gray-500">Request changes to your shift on {dateStr}</p>
          </div>
          <button onClick={onClose} className="p-1 rounded-lg hover:bg-gray-100 text-gray-400">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <form onSubmit={handleSubmit} className="px-6 py-4 space-y-4">
          {/* Current shift info */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Current Schedule</label>
            <div className="p-3 rounded-lg bg-gray-50 border border-gray-200">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-sm font-medium text-gray-800">
                  {getStatusLabel(shift.status)}
                </span>
                {formatShiftTime(shift.start_time, shift.end_time) && (
                  <span className="text-sm text-gray-600">
                    {formatShiftTime(shift.start_time, shift.end_time)}
                  </span>
                )}
                {shift.work_arrangement && (
                  <span className="text-xs px-1.5 py-0.5 rounded bg-gray-200 text-gray-700">
                    {WORK_ARRANGEMENT_LABELS[shift.work_arrangement] ?? shift.work_arrangement}
                  </span>
                )}
              </div>
              {tzDiffers && localHint && (
                <p className="mt-1.5 text-xs text-amber-600">
                  Your local time ({viewerTz}): {localHint}
                </p>
              )}
            </div>
          </div>

          {/* Requested changes */}
          <div className="border-t pt-4">
            <div className="mb-3 flex items-baseline justify-between gap-2">
              <p className="text-sm font-medium text-gray-700">Requested Changes</p>
              {orgTz && (
                <span className="text-[11px] text-gray-400">
                  Times in organization timezone ({orgTz})
                </span>
              )}
            </div>

            <div className="grid grid-cols-2 gap-3">
              {/* Start time */}
              <div>
                <label className="block text-xs text-gray-500 mb-1">Start Time</label>
                <input
                  type="time"
                  value={requestedStartTime}
                  onChange={(e) => setRequestedStartTime(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-purple-500 focus:border-transparent"
                />
              </div>

              {/* End time */}
              <div>
                <label className="block text-xs text-gray-500 mb-1">End Time</label>
                <input
                  type="time"
                  value={requestedEndTime}
                  onChange={(e) => setRequestedEndTime(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-purple-500 focus:border-transparent"
                />
              </div>

              {/* Status */}
              <div>
                <label className="block text-xs text-gray-500 mb-1">Status</label>
                <select
                  value={requestedStatus}
                  onChange={(e) => setRequestedStatus(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-purple-500 focus:border-transparent"
                >
                  {(statusOptions || []).map((s) => (
                    <option key={s.value} value={s.value}>
                      {s.label}
                    </option>
                  ))}
                </select>
              </div>

              {/* Work arrangement */}
              <div>
                <label className="block text-xs text-gray-500 mb-1">Work Arrangement</label>
                <select
                  value={requestedWorkArrangement}
                  onChange={(e) => setRequestedWorkArrangement(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-purple-500 focus:border-transparent"
                >
                  <option value="">—</option>
                  {workArrangements.map((wa) => (
                    <option key={wa.value} value={wa.value}>
                      {wa.label}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          </div>

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
              placeholder="Why do you need this schedule change?"
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
              disabled={createMutation.isPending}
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
