'use client'

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import {
  LeaveApplication,
  LeaveBalance,
  LeaveTypeConfig,
  ApprovalChainPreviewItem,
  PaginatedResponse,
} from '@/types'
import { useToast } from '@/components/ui/Toast'

const STATUS_COLORS: Record<string, string> = {
  pending: 'bg-yellow-100 text-yellow-800',
  approved: 'bg-green-100 text-green-800',
  rejected: 'bg-red-100 text-red-800',
  cancelled: 'bg-gray-100 text-gray-600',
}

interface ApplyFormData {
  leave_type: string
  start_date: string
  end_date: string
  reason: string
}

const EMPTY_FORM: ApplyFormData = { leave_type: '', start_date: '', end_date: '', reason: '' }

export default function MyLeaveTab() {
  const queryClient = useQueryClient()
  const { showToast } = useToast()

  const [showApplyForm, setShowApplyForm] = useState(false)
  const [form, setForm] = useState<ApplyFormData>(EMPTY_FORM)
  const [statusFilter, setStatusFilter] = useState<string>('all')
  const [page, setPage] = useState(1)
  const [cancelConfirmId, setCancelConfirmId] = useState<number | null>(null)

  // ── Queries ────────────────────────────────────────────────────────
  const { data: balance, isLoading: balanceLoading } = useQuery<LeaveBalance>({
    queryKey: ['my-leave-balance'],
    queryFn: () => api.getMyLeaveBalance(),
  })

  const { data: leaveTypes } = useQuery<LeaveTypeConfig[]>({
    queryKey: ['leave-types'],
    queryFn: () => api.getLeaveTypes(),
  })

  const { data: chainPreview } = useQuery<{ chain: ApprovalChainPreviewItem[] }>({
    queryKey: ['my-approval-chain'],
    queryFn: () => api.getMyApprovalChain(),
  })

  const params: Record<string, string> = { page: String(page), per_page: '10', scope: 'mine' }
  if (statusFilter !== 'all') params.status = statusFilter

  const { data: applications, isLoading: appsLoading } = useQuery<PaginatedResponse<LeaveApplication>>({
    queryKey: ['my-leave-applications', page, statusFilter],
    queryFn: () => api.getLeaveApplications(params) as Promise<PaginatedResponse<LeaveApplication>>,
  })

  // ── Mutations ──────────────────────────────────────────────────────
  const applyMutation = useMutation({
    mutationFn: (data: ApplyFormData) => api.createLeaveApplication(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['my-leave-applications'] })
      queryClient.invalidateQueries({ queryKey: ['my-leave-balance'] })
      setShowApplyForm(false)
      setForm(EMPTY_FORM)
      showToast('Leave application submitted', 'success')
    },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  const cancelMutation = useMutation({
    mutationFn: (id: number) => api.cancelLeaveApplication(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['my-leave-applications'] })
      queryClient.invalidateQueries({ queryKey: ['my-leave-balance'] })
      setCancelConfirmId(null)
      showToast('Leave application cancelled', 'success')
    },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    applyMutation.mutate(form)
  }

  const activeTypes = leaveTypes?.filter((t) => t.is_active) ?? []

  return (
    <div className="space-y-6">
      {/* ── Balance Cards ───────────────────────────────────────────── */}
      <div>
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-lg font-semibold text-gray-900">Leave Balance</h3>
            {balance?.policy_name && (
              <p className="text-sm text-gray-500">
                Policy: {balance.policy_name} &middot; {balance.accrual_method} accrual
                {balance.pool_type === 'shared' && ' &middot; Shared pool'}
              </p>
            )}
          </div>
          {!showApplyForm && (
            <button
              type="button"
              onClick={() => setShowApplyForm(true)}
              className="inline-flex items-center gap-1.5 rounded-md bg-purple-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-purple-700 transition-colors"
            >
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
              </svg>
              Apply for Leave
            </button>
          )}
        </div>

        {balanceLoading ? (
          <div className="flex items-center gap-3 text-sm text-gray-500">
            <svg className="h-5 w-5 animate-spin text-purple-600" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            Loading balance...
          </div>
        ) : balance && balance.balances.length > 0 ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {balance.balances.map((b) => {
              const usedPct = b.total_days > 0 ? (b.used_days / b.total_days) * 100 : 0
              const pendingPct = b.total_days > 0 ? (b.pending_days / b.total_days) * 100 : 0
              return (
                <div key={b.leave_type} className="bg-white border border-gray-200 rounded-lg p-4">
                  <h4 className="text-sm font-semibold text-gray-900 truncate">{b.leave_type_name || b.leave_type}</h4>
                  <div className="mt-2 flex items-baseline gap-1">
                    <span className="text-2xl font-bold text-purple-600">{b.available_days}</span>
                    <span className="text-sm text-gray-500">/ {b.total_days} days</span>
                  </div>
                  <div className="mt-2 h-2 bg-gray-100 rounded-full overflow-hidden flex">
                    <div className="bg-purple-500 h-full" style={{ width: `${usedPct}%` }} />
                    <div className="bg-yellow-400 h-full" style={{ width: `${pendingPct}%` }} />
                  </div>
                  <div className="mt-1 flex justify-between text-xs text-gray-500">
                    <span>Used: {b.used_days}</span>
                    <span>Pending: {b.pending_days}</span>
                  </div>
                </div>
              )
            })}
          </div>
        ) : (
          <p className="text-sm text-gray-500">No leave balance data available. A leave policy may not be assigned yet.</p>
        )}
      </div>

      {/* ── Apply Form ──────────────────────────────────────────────── */}
      {showApplyForm && (
        <div className="bg-white border border-gray-200 rounded-xl shadow-sm p-6 space-y-4">
          <h3 className="text-lg font-semibold text-gray-900">Apply for Leave</h3>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Leave Type</label>
                <select
                  required
                  value={form.leave_type}
                  onChange={(e) => setForm((p) => ({ ...p, leave_type: e.target.value }))}
                  className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none"
                >
                  <option value="">Select type</option>
                  {activeTypes.map((lt) => (
                    <option key={lt.code} value={lt.code}>{lt.name}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Start Date</label>
                <input
                  type="date"
                  required
                  value={form.start_date}
                  onChange={(e) => setForm((p) => ({ ...p, start_date: e.target.value }))}
                  className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">End Date</label>
                <input
                  type="date"
                  required
                  value={form.end_date}
                  onChange={(e) => setForm((p) => ({ ...p, end_date: e.target.value }))}
                  min={form.start_date || undefined}
                  className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none"
                />
              </div>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Reason</label>
              <textarea
                required
                rows={3}
                value={form.reason}
                onChange={(e) => setForm((p) => ({ ...p, reason: e.target.value }))}
                placeholder="Provide a reason for your leave request"
                className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none"
              />
            </div>

            {/* Approval chain preview */}
            {chainPreview && chainPreview.chain.length > 0 && (
              <div className="bg-purple-50 border border-purple-200 rounded-lg p-3">
                <p className="text-xs font-medium text-purple-700 mb-2">Your application will be reviewed by:</p>
                <div className="flex flex-wrap gap-2">
                  {chainPreview.chain.map((step, i) => (
                    <div key={i} className="flex items-center gap-1">
                      <span className="inline-flex items-center justify-center h-5 w-5 rounded-full bg-purple-200 text-purple-800 text-xs font-bold">
                        {step.step_order}
                      </span>
                      <span className="text-sm text-purple-800">{step.approver_name}</span>
                      {i < chainPreview.chain.length - 1 && (
                        <svg className="h-4 w-4 text-purple-300 mx-1" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
                        </svg>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div className="flex items-center gap-3">
              <button
                type="submit"
                disabled={applyMutation.isPending}
                className="inline-flex items-center rounded-md bg-purple-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {applyMutation.isPending ? 'Submitting...' : 'Submit Application'}
              </button>
              <button
                type="button"
                onClick={() => { setShowApplyForm(false); setForm(EMPTY_FORM) }}
                className="inline-flex items-center rounded-md bg-white px-4 py-2 text-sm font-semibold text-gray-700 shadow-sm ring-1 ring-inset ring-gray-300 hover:bg-gray-50 transition-colors"
              >
                Cancel
              </button>
            </div>
          </form>
        </div>
      )}

      {/* ── My Leave History ────────────────────────────────────────── */}
      <div className="bg-white border border-gray-200 rounded-xl shadow-sm">
        <div className="border-b border-gray-200 px-6 py-4">
          <h3 className="text-lg font-semibold text-gray-900">My Leave History</h3>
          <div className="mt-3 flex gap-2">
            {['all', 'pending', 'approved', 'rejected', 'cancelled'].map((s) => (
              <button
                key={s}
                onClick={() => { setStatusFilter(s); setPage(1) }}
                className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
                  statusFilter === s
                    ? 'bg-purple-100 text-purple-700'
                    : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                }`}
              >
                {s.charAt(0).toUpperCase() + s.slice(1)}
              </button>
            ))}
          </div>
        </div>
        <div className="px-6 py-4">
          {appsLoading ? (
            <div className="flex items-center gap-3 text-sm text-gray-500 py-8">
              <svg className="h-5 w-5 animate-spin text-purple-600" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              Loading...
            </div>
          ) : applications && applications.items.length > 0 ? (
            <>
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-gray-200">
                  <thead>
                    <tr>
                      <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Type</th>
                      <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Dates</th>
                      <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Days</th>
                      <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Status</th>
                      <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Approval Progress</th>
                      <th className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-wider text-gray-500">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {applications.items.map((app) => (
                      <tr key={app.id} className="hover:bg-gray-50 transition-colors">
                        <td className="px-4 py-3 text-sm text-gray-900">{app.leave_type.replace(/_/g, ' ')}</td>
                        <td className="px-4 py-3 text-sm text-gray-600">
                          {app.start_date} to {app.end_date}
                        </td>
                        <td className="px-4 py-3 text-sm text-gray-700 font-medium">{app.days_requested}</td>
                        <td className="px-4 py-3">
                          <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${STATUS_COLORS[app.status] ?? 'bg-gray-100 text-gray-600'}`}>
                            {app.status}
                          </span>
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
                                {app.approval_steps.filter((s) => s.status === 'approved').length}/{app.approval_steps.length}
                              </span>
                            </div>
                          ) : (
                            <span className="text-xs text-gray-400">--</span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-right">
                          {app.status === 'pending' && (
                            cancelConfirmId === app.id ? (
                              <div className="flex items-center justify-end gap-1">
                                <button
                                  type="button"
                                  onClick={() => cancelMutation.mutate(app.id)}
                                  disabled={cancelMutation.isPending}
                                  className="inline-flex items-center rounded-md bg-red-600 px-2 py-1 text-xs font-medium text-white hover:bg-red-700 disabled:opacity-50 transition-colors"
                                >
                                  Confirm
                                </button>
                                <button
                                  type="button"
                                  onClick={() => setCancelConfirmId(null)}
                                  className="inline-flex items-center rounded-md bg-gray-100 px-2 py-1 text-xs font-medium text-gray-600 hover:bg-gray-200 transition-colors"
                                >
                                  No
                                </button>
                              </div>
                            ) : (
                              <button
                                type="button"
                                onClick={() => setCancelConfirmId(app.id)}
                                className="inline-flex items-center rounded-md px-2 py-1 text-xs font-medium text-red-600 hover:bg-red-50 transition-colors"
                              >
                                Cancel
                              </button>
                            )
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {/* Pagination */}
              {applications.total_pages > 1 && (
                <div className="flex items-center justify-between mt-4 pt-4 border-t border-gray-100">
                  <p className="text-sm text-gray-500">
                    Page {applications.page} of {applications.total_pages} ({applications.total} total)
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
                      disabled={page >= applications.total_pages}
                      className="rounded-md px-3 py-1 text-sm font-medium text-gray-700 ring-1 ring-inset ring-gray-300 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                    >
                      Next
                    </button>
                  </div>
                </div>
              )}
            </>
          ) : (
            <p className="text-sm text-gray-500 py-8 text-center">No leave applications found.</p>
          )}
        </div>
      </div>
    </div>
  )
}
