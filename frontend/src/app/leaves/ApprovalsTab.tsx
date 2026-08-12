'use client'

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { LeaveApplication, PaginatedResponse } from '@/types'
import { useToast } from '@/components/ui/Toast'

const STATUS_COLORS: Record<string, string> = {
  pending: 'bg-yellow-100 text-yellow-800',
  approved: 'bg-green-100 text-green-800',
  rejected: 'bg-red-100 text-red-800',
  cancelled: 'bg-gray-100 text-gray-600',
}

export default function ApprovalsTab() {
  const queryClient = useQueryClient()
  const { showToast } = useToast()

  const [page, setPage] = useState(1)
  const [reviewModal, setReviewModal] = useState<{ id: number; action: 'approve' | 'reject'; employeeName: string } | null>(null)
  const [reviewNotes, setReviewNotes] = useState('')

  // ── Queries ────────────────────────────────────────────────────────
  const { data: pendingApprovals, isLoading } = useQuery<PaginatedResponse<LeaveApplication>>({
    queryKey: ['pending-approvals', page],
    queryFn: () => api.getPendingApprovals({ page: String(page), per_page: '10' }),
  })

  // ── Mutations ──────────────────────────────────────────────────────
  const reviewMutation = useMutation({
    mutationFn: ({ id, action, notes }: { id: number; action: string; notes: string }) =>
      api.reviewLeaveApplication(id, { action, notes: notes || undefined }),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ['pending-approvals'] })
      queryClient.invalidateQueries({ queryKey: ['my-leave-applications'] })
      setReviewModal(null)
      setReviewNotes('')
      showToast(`Application ${variables.action === 'approve' ? 'approved' : 'rejected'}`, 'success')
    },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  const handleReviewSubmit = () => {
    if (!reviewModal) return
    reviewMutation.mutate({ id: reviewModal.id, action: reviewModal.action, notes: reviewNotes })
  }

  const pendingCount = pendingApprovals?.total ?? 0

  return (
    <div className="space-y-6">
      {/* ── Summary Cards ───────────────────────────────────────────── */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="bg-white border border-gray-200 rounded-lg p-4">
          <p className="text-sm text-gray-500">Pending My Review</p>
          <p className="mt-1 text-2xl font-bold text-yellow-600">{pendingCount}</p>
        </div>
      </div>

      {/* ── Pending Approvals Table ─────────────────────────────────── */}
      <div className="bg-white border border-gray-200 rounded-xl shadow-sm">
        <div className="border-b border-gray-200 px-6 py-4">
          <h3 className="text-lg font-semibold text-gray-900">Pending Approvals</h3>
          <p className="mt-1 text-sm text-gray-500">Leave applications awaiting your decision.</p>
        </div>
        <div className="px-6 py-4">
          {isLoading ? (
            <div className="flex items-center gap-3 text-sm text-gray-500 py-8">
              <svg className="h-5 w-5 animate-spin text-purple-600" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              Loading...
            </div>
          ) : pendingApprovals && pendingApprovals.items.length > 0 ? (
            <>
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-gray-200">
                  <thead>
                    <tr>
                      <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Employee</th>
                      <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Type</th>
                      <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Dates</th>
                      <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Days</th>
                      <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Reason</th>
                      <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Step</th>
                      <th className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-wider text-gray-500">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {pendingApprovals.items.map((app) => (
                      <tr key={app.id} className="hover:bg-gray-50 transition-colors">
                        <td className="px-4 py-3 text-sm font-medium text-gray-900">{app.employee_name}</td>
                        <td className="px-4 py-3 text-sm text-gray-700">{app.leave_type.replace(/_/g, ' ')}</td>
                        <td className="px-4 py-3 text-sm text-gray-600">
                          {app.start_date} to {app.end_date}
                        </td>
                        <td className="px-4 py-3 text-sm text-gray-700 font-medium">{app.days_requested}</td>
                        <td className="px-4 py-3 text-sm text-gray-600 max-w-xs truncate" title={app.reason}>
                          {app.reason}
                        </td>
                        <td className="px-4 py-3">
                          {app.approval_steps && app.approval_steps.length > 0 ? (
                            <div className="flex items-center gap-1">
                              {app.approval_steps.map((step) => (
                                <div
                                  key={step.id}
                                  title={`Step ${step.step_order}: ${step.approver_name} - ${step.status}`}
                                  className={`h-2.5 w-2.5 rounded-full ${
                                    step.status === 'approved' ? 'bg-green-500' :
                                    step.status === 'rejected' ? 'bg-red-500' :
                                    'bg-yellow-400'
                                  }`}
                                />
                              ))}
                              <span className="ml-1 text-xs text-gray-500">
                                Step {app.current_step ?? '?'}/{app.approval_steps.length}
                              </span>
                            </div>
                          ) : (
                            <span className="text-xs text-gray-400">--</span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-right">
                          <div className="flex items-center justify-end gap-2">
                            <button
                              type="button"
                              onClick={() => setReviewModal({ id: app.id, action: 'approve', employeeName: app.employee_name })}
                              className="inline-flex items-center rounded-md bg-green-600 px-3 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-green-700 transition-colors"
                            >
                              Approve
                            </button>
                            <button
                              type="button"
                              onClick={() => setReviewModal({ id: app.id, action: 'reject', employeeName: app.employee_name })}
                              className="inline-flex items-center rounded-md bg-red-600 px-3 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-red-700 transition-colors"
                            >
                              Reject
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {/* Pagination */}
              {pendingApprovals.total_pages > 1 && (
                <div className="flex items-center justify-between mt-4 pt-4 border-t border-gray-100">
                  <p className="text-sm text-gray-500">
                    Page {pendingApprovals.page} of {pendingApprovals.total_pages} ({pendingApprovals.total} total)
                  </p>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => setPage((p) => Math.max(1, p - 1))}
                      disabled={page <= 1}
                      className="rounded-md px-3 py-1 text-sm font-medium text-gray-700 ring-1 ring-inset ring-gray-300 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                    >
                      Previous
                    </button>
                    <button
                      type="button"
                      onClick={() => setPage((p) => p + 1)}
                      disabled={page >= pendingApprovals.total_pages}
                      className="rounded-md px-3 py-1 text-sm font-medium text-gray-700 ring-1 ring-inset ring-gray-300 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                    >
                      Next
                    </button>
                  </div>
                </div>
              )}
            </>
          ) : (
            <div className="text-center py-12">
              <svg className="mx-auto h-12 w-12 text-gray-300" fill="none" viewBox="0 0 24 24" strokeWidth={1} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <p className="mt-4 text-sm text-gray-500">No pending approvals. You&apos;re all caught up!</p>
            </div>
          )}
        </div>
      </div>

      {/* ── Review Modal ────────────────────────────────────────────── */}
      {reviewModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-md mx-4 p-6 space-y-4">
            <h3 className="text-lg font-semibold text-gray-900">
              {reviewModal.action === 'approve' ? 'Approve' : 'Reject'} Leave Request
            </h3>
            <p className="text-sm text-gray-600">
              {reviewModal.action === 'approve'
                ? `Approve ${reviewModal.employeeName}'s leave request?`
                : `Reject ${reviewModal.employeeName}'s leave request?`}
            </p>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Notes (optional)</label>
              <textarea
                rows={3}
                value={reviewNotes}
                onChange={(e) => setReviewNotes(e.target.value)}
                placeholder="Add any notes..."
                className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none"
              />
            </div>
            <div className="flex items-center justify-end gap-3">
              <button
                type="button"
                onClick={() => { setReviewModal(null); setReviewNotes('') }}
                className="inline-flex items-center rounded-md bg-white px-4 py-2 text-sm font-semibold text-gray-700 shadow-sm ring-1 ring-inset ring-gray-300 hover:bg-gray-50 transition-colors"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleReviewSubmit}
                disabled={reviewMutation.isPending}
                className={`inline-flex items-center rounded-md px-4 py-2 text-sm font-semibold text-white shadow-sm disabled:opacity-50 disabled:cursor-not-allowed transition-colors ${
                  reviewModal.action === 'approve'
                    ? 'bg-green-600 hover:bg-green-700'
                    : 'bg-red-600 hover:bg-red-700'
                }`}
              >
                {reviewMutation.isPending ? 'Processing...' : reviewModal.action === 'approve' ? 'Approve' : 'Reject'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
