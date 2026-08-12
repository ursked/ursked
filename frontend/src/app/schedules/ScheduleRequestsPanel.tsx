'use client';

import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { ScheduleChangeRequest } from '@/types';
import { getStatusLabel, formatShiftTime } from './scheduleHelpers';

interface ScheduleRequestsPanelProps {
  isOpen: boolean;
  onClose: () => void;
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    pending: 'bg-yellow-100 text-yellow-800',
    approved: 'bg-green-100 text-green-800',
    rejected: 'bg-red-100 text-red-800',
    cancelled: 'bg-gray-100 text-gray-600',
  };
  return (
    <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${colors[status] || 'bg-gray-100 text-gray-600'}`}>
      {status.charAt(0).toUpperCase() + status.slice(1)}
    </span>
  );
}

function ApprovalSteps({ request }: { request: ScheduleChangeRequest }) {
  return (
    <div className="flex items-center gap-1 mt-2">
      {request.approval_steps.map((step, idx) => (
        <React.Fragment key={step.id}>
          {idx > 0 && (
            <div className={`w-4 h-px ${step.status === 'approved' ? 'bg-green-300' : 'bg-gray-200'}`} />
          )}
          <div
            className={`w-5 h-5 rounded-full flex items-center justify-center text-[9px] font-bold
              ${
                step.status === 'approved'
                  ? 'bg-green-100 text-green-700'
                  : step.status === 'rejected'
                  ? 'bg-red-100 text-red-700'
                  : 'bg-gray-100 text-gray-500'
              }`}
            title={`Step ${step.step_order}: ${step.approver_name} (${step.step_type === 'peer_approval' ? 'Peer' : 'Manager'}) — ${step.status}`}
          >
            {step.status === 'approved' ? (
              <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
              </svg>
            ) : step.status === 'rejected' ? (
              <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M6 18L18 6M6 6l12 12" />
              </svg>
            ) : (
              step.step_order
            )}
          </div>
        </React.Fragment>
      ))}
    </div>
  );
}

function RequestCard({
  request,
  showActions,
  onApprove,
  onReject,
  onCancel,
}: {
  request: ScheduleChangeRequest;
  showActions?: 'approve' | 'cancel';
  onApprove?: (id: number, notes: string) => void;
  onReject?: (id: number, notes: string) => void;
  onCancel?: (id: number) => void;
}) {
  const [showNotes, setShowNotes] = useState(false);
  const [notes, setNotes] = useState('');

  return (
    <div className="p-3 border border-gray-200 rounded-lg hover:border-gray-300 transition-colors">
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`text-xs font-semibold px-1.5 py-0.5 rounded ${
              request.request_type === 'swap' ? 'bg-blue-100 text-blue-700' : 'bg-orange-100 text-orange-700'
            }`}>
              {request.request_type === 'swap' ? 'Swap' : 'Change'}
            </span>
            <StatusBadge status={request.status} />
          </div>

          <p className="text-sm font-medium text-gray-900 mt-1">
            {request.request_type === 'swap' ? (
              <>
                {request.requester_name} &harr; {request.target_employee_name}
              </>
            ) : (
              <>{request.requester_name}</>
            )}
          </p>

          <div className="text-xs text-gray-500 mt-0.5">
            {request.date}
            {request.end_date && request.end_date !== request.date && ` — ${request.end_date}`}
          </div>

          {/* Shift details */}
          {request.request_type === 'swap' && (
            <div className="text-xs text-gray-500 mt-1 space-y-0.5">
              {request.original_start_time && (
                <p>Your shift: {getStatusLabel(request.original_status || '')} {formatShiftTime(request.original_start_time, request.original_end_time)}</p>
              )}
              {request.target_original_start_time && (
                <p>Their shift: {getStatusLabel(request.target_original_status || '')} {formatShiftTime(request.target_original_start_time, request.target_original_end_time)}</p>
              )}
            </div>
          )}

          {request.request_type === 'change' && (
            <div className="text-xs text-gray-500 mt-1 space-y-0.5">
              {request.original_start_time && (
                <p>Current: {formatShiftTime(request.original_start_time, request.original_end_time)}</p>
              )}
              {(request.requested_start_time || request.requested_end_time) && (
                <p>Requested: {formatShiftTime(request.requested_start_time, request.requested_end_time)}</p>
              )}
              {request.requested_status && (
                <p>Status: {getStatusLabel(request.requested_status)}</p>
              )}
              {request.requested_work_arrangement && (
                <p>Arrangement: {request.requested_work_arrangement}</p>
              )}
            </div>
          )}

          {request.reason && (
            <p className="text-xs text-gray-400 mt-1 italic">&ldquo;{request.reason}&rdquo;</p>
          )}

          <ApprovalSteps request={request} />
        </div>

        <div className="text-[10px] text-gray-400 whitespace-nowrap">
          {new Date(request.created_at).toLocaleDateString()}
        </div>
      </div>

      {/* Action buttons */}
      {showActions === 'cancel' && request.status === 'pending' && onCancel && (
        <div className="mt-2 pt-2 border-t">
          <button
            onClick={() => onCancel(request.id)}
            className="text-xs text-red-600 hover:text-red-700 font-medium"
          >
            Cancel Request
          </button>
        </div>
      )}

      {showActions === 'approve' && request.status === 'pending' && (
        <div className="mt-2 pt-2 border-t space-y-2">
          {!showNotes ? (
            <div className="flex items-center gap-2">
              <button
                onClick={() => {
                  setShowNotes(true);
                }}
                className="text-xs font-medium text-green-700 bg-green-50 px-3 py-1 rounded-lg hover:bg-green-100 transition-colors"
              >
                Approve
              </button>
              <button
                onClick={() => {
                  setShowNotes(true);
                }}
                className="text-xs font-medium text-red-700 bg-red-50 px-3 py-1 rounded-lg hover:bg-red-100 transition-colors"
              >
                Reject
              </button>
            </div>
          ) : (
            <div className="space-y-2">
              <textarea
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                rows={2}
                className="w-full px-2 py-1.5 border border-gray-300 rounded-lg text-xs focus:ring-2 focus:ring-purple-500 focus:border-transparent resize-none"
                placeholder="Notes (optional)"
              />
              <div className="flex items-center gap-2">
                <button
                  onClick={() => onApprove?.(request.id, notes)}
                  className="text-xs font-medium text-white bg-green-600 px-3 py-1 rounded-lg hover:bg-green-700 transition-colors"
                >
                  Confirm Approve
                </button>
                <button
                  onClick={() => onReject?.(request.id, notes)}
                  className="text-xs font-medium text-white bg-red-600 px-3 py-1 rounded-lg hover:bg-red-700 transition-colors"
                >
                  Confirm Reject
                </button>
                <button
                  onClick={() => { setShowNotes(false); setNotes(''); }}
                  className="text-xs text-gray-500 hover:text-gray-700"
                >
                  Back
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Reviewer notes */}
      {request.reviewer_notes && request.status !== 'pending' && (
        <div className="mt-2 pt-2 border-t">
          <p className="text-xs text-gray-500">
            <span className="font-medium">Reviewer:</span> {request.reviewer_notes}
          </p>
        </div>
      )}
    </div>
  );
}

export default function ScheduleRequestsPanel({ isOpen, onClose }: ScheduleRequestsPanelProps) {
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<'my' | 'approvals'>('my');

  const { data: myRequests = [], isLoading: loadingMy } = useQuery<ScheduleChangeRequest[]>({
    queryKey: ['my-schedule-requests'],
    queryFn: () => api.getMyScheduleChangeRequests(),
    enabled: isOpen,
  });

  const { data: pendingApprovals = [], isLoading: loadingApprovals } = useQuery<ScheduleChangeRequest[]>({
    queryKey: ['pending-schedule-approvals'],
    queryFn: () => api.getPendingScheduleApprovals(),
    enabled: isOpen,
  });

  const reviewMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: { action: 'approve' | 'reject'; notes?: string } }) =>
      api.reviewScheduleChangeRequest(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['my-schedule-requests'] });
      queryClient.invalidateQueries({ queryKey: ['pending-schedule-approvals'] });
      queryClient.invalidateQueries({ queryKey: ['schedule-grid'] });
    },
  });

  const cancelMutation = useMutation({
    mutationFn: (id: number) => api.cancelScheduleChangeRequest(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['my-schedule-requests'] });
      queryClient.invalidateQueries({ queryKey: ['pending-schedule-approvals'] });
    },
  });

  const handleApprove = (id: number, notes: string) => {
    reviewMutation.mutate({ id, data: { action: 'approve', notes: notes || undefined } });
  };

  const handleReject = (id: number, notes: string) => {
    reviewMutation.mutate({ id, data: { action: 'reject', notes: notes || undefined } });
  };

  const handleCancel = (id: number) => {
    cancelMutation.mutate(id);
  };

  if (!isOpen) return null;

  const pendingCount = pendingApprovals.length;

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />
      <div className="relative w-full max-w-md bg-white shadow-2xl flex flex-col">
        {/* Header */}
        <div className="px-6 py-4 border-b flex items-center justify-between">
          <h3 className="text-lg font-semibold text-gray-900">Schedule Requests</h3>
          <button onClick={onClose} className="p-1 rounded-lg hover:bg-gray-100 text-gray-400">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Tabs */}
        <div className="flex border-b">
          <button
            onClick={() => setTab('my')}
            className={`flex-1 px-4 py-2.5 text-sm font-medium transition-colors ${
              tab === 'my'
                ? 'text-purple-700 border-b-2 border-purple-600'
                : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            My Requests
          </button>
          <button
            onClick={() => setTab('approvals')}
            className={`flex-1 px-4 py-2.5 text-sm font-medium transition-colors relative ${
              tab === 'approvals'
                ? 'text-purple-700 border-b-2 border-purple-600'
                : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            Pending Approvals
            {pendingCount > 0 && (
              <span className="ml-1.5 inline-flex items-center justify-center w-5 h-5 text-[10px] font-bold text-white bg-red-500 rounded-full">
                {pendingCount}
              </span>
            )}
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-4 py-4">
          {tab === 'my' && (
            <>
              {loadingMy ? (
                <div className="text-center py-8">
                  <div className="w-8 h-8 border-4 border-purple-200 border-t-purple-600 rounded-full animate-spin mx-auto mb-2" />
                  <p className="text-sm text-gray-500">Loading requests...</p>
                </div>
              ) : myRequests.length === 0 ? (
                <div className="text-center py-8">
                  <svg className="w-10 h-10 mx-auto text-gray-300 mb-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
                  </svg>
                  <p className="text-sm text-gray-500">No schedule requests yet</p>
                  <p className="text-xs text-gray-400 mt-1">Click on your shift to request a swap or change</p>
                </div>
              ) : (
                <div className="space-y-3">
                  {myRequests.map((req) => (
                    <RequestCard
                      key={req.id}
                      request={req}
                      showActions="cancel"
                      onCancel={handleCancel}
                    />
                  ))}
                </div>
              )}
            </>
          )}

          {tab === 'approvals' && (
            <>
              {loadingApprovals ? (
                <div className="text-center py-8">
                  <div className="w-8 h-8 border-4 border-purple-200 border-t-purple-600 rounded-full animate-spin mx-auto mb-2" />
                  <p className="text-sm text-gray-500">Loading approvals...</p>
                </div>
              ) : pendingApprovals.length === 0 ? (
                <div className="text-center py-8">
                  <svg className="w-10 h-10 mx-auto text-gray-300 mb-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  <p className="text-sm text-gray-500">No pending approvals</p>
                </div>
              ) : (
                <div className="space-y-3">
                  {pendingApprovals.map((req) => (
                    <RequestCard
                      key={req.id}
                      request={req}
                      showActions="approve"
                      onApprove={handleApprove}
                      onReject={handleReject}
                    />
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
