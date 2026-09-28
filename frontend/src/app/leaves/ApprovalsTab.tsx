'use client'

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { LeaveApplication, PaginatedResponse } from '@/types'
import { useToast } from '@/components/ui/Toast'
import { ErrorMessage } from '@/components/ui/ErrorBoundary'
import { UserPicker } from '@/components/ui'
import { usePermissions } from '@/contexts/PermissionsContext'
import { ApproverCheckNote, EventList, StepDots, ViolationList, daysLabel, typeLabel, useApproverCheck } from './leaveUi'

type Target = { id: number; employeeName: string; app: LeaveApplication }

const SPINNER = (
  <svg className="h-5 w-5 animate-spin text-purple-600" fill="none" viewBox="0 0 24 24">
    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
  </svg>
)

function ModalShell({ title, children, footer }: { title: string; children: React.ReactNode; footer: React.ReactNode }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" role="dialog" aria-modal="true" aria-label={title}>
      <div className="bg-white rounded-xl shadow-xl w-full max-w-lg mx-4 p-6 space-y-4 max-h-[90vh] overflow-y-auto">
        <h3 className="text-lg font-semibold text-gray-900">{title}</h3>
        {children}
        <div className="flex items-center justify-end gap-3">{footer}</div>
      </div>
    </div>
  )
}

const BTN_SECONDARY =
  'inline-flex items-center rounded-md bg-white px-4 py-2 text-sm font-semibold text-gray-700 shadow-sm ring-1 ring-inset ring-gray-300 hover:bg-gray-50 transition-colors'

function ReasonField({ id, value, onChange, placeholder, help }: { id: string; value: string; onChange: (v: string) => void; placeholder: string; help: string }) {
  return (
    <div>
      <label htmlFor={id} className="block text-sm font-medium text-gray-700 mb-1">
        Reason <span className="text-red-500">*</span>
      </label>
      <textarea
        id={id}
        rows={3}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none"
      />
      <p className="mt-1 text-xs text-gray-500">{help}</p>
    </div>
  )
}

export default function ApprovalsTab() {
  const queryClient = useQueryClient()
  const { showToast } = useToast()
  const { hasPermission } = usePermissions()
  // Stepping in on someone else's approval is a leave:edit power (admin and
  // HR by default); the API refuses it to anyone else.
  const canStepIn = hasPermission('leave', 'edit')

  const [page, setPage] = useState(1)
  const [reviewModal, setReviewModal] = useState<(Target & { action: 'approve' | 'reject' }) | null>(null)
  const [reviewNotes, setReviewNotes] = useState('')
  // Undoing an approval is a separate flow: it reverses a decision the employee
  // was already told about, and it rewrites their schedule.
  const [revokeModal, setRevokeModal] = useState<(Target & { action: 'unapprove' | 'reject' }) | null>(null)
  const [revokeNotes, setRevokeNotes] = useState('')
  const [overrideModal, setOverrideModal] = useState<(Target & { action: 'approve' | 'reject' }) | null>(null)
  const [reassignModal, setReassignModal] = useState<Target | null>(null)
  const [reason, setReason] = useState('')
  const [newApprover, setNewApprover] = useState<number | null>(null)
  const { data: newApproverCheck } = useApproverCheck(newApprover)

  // ── Queries ────────────────────────────────────────────────────────
  const { data: pendingApprovals, isLoading, isError, refetch } = useQuery<PaginatedResponse<LeaveApplication>>({
    queryKey: ['pending-approvals', page],
    queryFn: () => api.getPendingApprovals({ page: String(page), per_page: '10' }),
  })

  // Requests in the caller's reach that are waiting on SOMEONE ELSE, for
  // reassigning a stuck approver or overriding. Only fetched for people who
  // may do either.
  const { data: stuck } = useQuery<PaginatedResponse<LeaveApplication>>({
    queryKey: ['stuck-approvals'],
    queryFn: () =>
      api.getLeaveApplications({ scope: 'review', status: 'pending', per_page: '50' }) as Promise<PaginatedResponse<LeaveApplication>>,
    enabled: canStepIn,
  })
  const stuckItems = (stuck?.items ?? []).filter((a) => a.actions?.can_override && !a.actions?.can_review)

  const { data: approved, isLoading: approvedLoading } = useQuery<PaginatedResponse<LeaveApplication>>({
    queryKey: ['approved-applications'],
    queryFn: () =>
      api.getLeaveApplications({ scope: 'review', status: 'approved', per_page: '10' }) as Promise<PaginatedResponse<LeaveApplication>>,
  })
  const revocable = (approved?.items ?? []).filter((a) => a.actions?.can_revoke)

  const refreshAll = () => {
    queryClient.invalidateQueries({ queryKey: ['pending-approvals'] })
    queryClient.invalidateQueries({ queryKey: ['stuck-approvals'] })
    queryClient.invalidateQueries({ queryKey: ['approved-applications'] })
    queryClient.invalidateQueries({ queryKey: ['my-leave-applications'] })
    queryClient.invalidateQueries({ queryKey: ['team-leave-applications'] })
    queryClient.invalidateQueries({ queryKey: ['team-stats'] })
    // Approval and revocation rewrite the schedule.
    queryClient.invalidateQueries({ queryKey: ['schedule-grid'] })
  }
  const closeAll = () => {
    setReviewModal(null)
    setRevokeModal(null)
    setOverrideModal(null)
    setReassignModal(null)
    setReviewNotes('')
    setRevokeNotes('')
    setReason('')
    setNewApprover(null)
  }

  // ── Mutations ──────────────────────────────────────────────────────
  const reviewMutation = useMutation({
    mutationFn: ({ id, action, notes }: { id: number; action: string; notes: string }) =>
      api.reviewLeaveApplication(id, { action, notes: notes || undefined }),
    onSuccess: (_data, variables) => {
      refreshAll()
      closeAll()
      showToast(`Request ${variables.action === 'approve' ? 'approved' : 'rejected'}`, 'success')
    },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  const revokeMutation = useMutation({
    mutationFn: ({ id, action, notes }: { id: number; action: 'unapprove' | 'reject'; notes: string }) =>
      api.revokeLeaveApplication(id, { action, notes }),
    onSuccess: (_data, variables) => {
      refreshAll()
      closeAll()
      showToast(
        variables.action === 'unapprove' ? 'Approval withdrawn; the request is pending again' : 'Approved leave rejected',
        'success',
      )
    },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  const overrideMutation = useMutation({
    mutationFn: ({ id, action, reason }: { id: number; action: 'approve' | 'reject'; reason: string }) =>
      api.overrideLeaveApplication(id, { action, reason }),
    onSuccess: (_d, v) => {
      refreshAll()
      closeAll()
      showToast(v.action === 'approve' ? 'Request approved by override' : 'Request rejected by override', 'success')
    },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  const reassignMutation = useMutation({
    mutationFn: ({ id, approver_id, reason }: { id: number; approver_id: number; reason: string }) =>
      api.reassignLeaveApprover(id, { approver_id, reason }),
    onSuccess: () => {
      refreshAll()
      closeAll()
      showToast('Approver changed; they have been notified', 'success')
    },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  const pendingCount = pendingApprovals?.total ?? 0
  const target = (app: LeaveApplication): Target => ({ id: app.id, employeeName: app.employee_name, app })

  const currentApprover = (app: LeaveApplication) =>
    app.approval_steps?.find((s) => s.step_order === app.current_step)?.approver_name ?? 'nobody'

  return (
    <div className="space-y-6">
      {/* ── Summary Cards ───────────────────────────────────────────── */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="bg-white border border-gray-200 rounded-lg p-4">
          <p className="text-sm text-gray-500">Pending my review</p>
          <p className="mt-1 text-2xl font-bold text-yellow-600">{pendingCount}</p>
        </div>
        {canStepIn && (
          <div className="bg-white border border-gray-200 rounded-lg p-4">
            <p className="text-sm text-gray-500">Waiting on another approver</p>
            <p className="mt-1 text-2xl font-bold text-gray-700">{stuckItems.length}</p>
          </div>
        )}
      </div>

      {/* ── Pending Approvals Table ─────────────────────────────────── */}
      <div className="bg-white border border-gray-200 rounded-xl shadow-sm">
        <div className="border-b border-gray-200 px-6 py-4">
          <h3 className="text-lg font-semibold text-gray-900">Pending approvals</h3>
          <p className="mt-1 text-sm text-gray-500">Leave requests waiting for your decision.</p>
        </div>
        <div className="px-6 py-4">
          {isLoading ? (
            <div className="flex items-center gap-3 text-sm text-gray-500 py-8">{SPINNER}Loading...</div>
          ) : pendingApprovals && pendingApprovals.items.length > 0 ? (
            <>
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-gray-200">
                  <thead>
                    <tr>
                      {['Employee', 'Type', 'Dates', 'Days', 'Reason', 'Step'].map((h) => (
                        <th key={h} className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">{h}</th>
                      ))}
                      <th className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-wider text-gray-500">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {pendingApprovals.items.map((app) => (
                      <tr key={app.id} className="hover:bg-gray-50 transition-colors align-top">
                        <td className="px-4 py-3 text-sm font-medium text-gray-900">{app.employee_name}</td>
                        <td className="px-4 py-3 text-sm text-gray-700">{typeLabel(app)}</td>
                        <td className="px-4 py-3 text-sm text-gray-600">{app.start_date} to {app.end_date}</td>
                        <td className="px-4 py-3 text-sm text-gray-700 font-medium">{daysLabel(app)}</td>
                        <td className="px-4 py-3 text-sm text-gray-600 max-w-xs">
                          <p className="truncate" title={app.reason}>{app.reason}</p>
                          {app.rule_warnings && app.rule_warnings.length > 0 && (
                            <p className="mt-1 text-xs font-medium text-amber-700">
                              {app.rule_warnings.length} warning{app.rule_warnings.length === 1 ? '' : 's'} — open to read
                            </p>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          <StepDots app={app} />
                        </td>
                        <td className="px-4 py-3 text-right">
                          {app.actions?.can_review && (
                            <div className="flex items-center justify-end gap-2">
                              <button
                                type="button"
                                onClick={() => setReviewModal({ ...target(app), action: 'approve' })}
                                className="inline-flex items-center rounded-md bg-green-600 px-3 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-green-700 transition-colors"
                              >
                                Approve
                              </button>
                              <button
                                type="button"
                                onClick={() => setReviewModal({ ...target(app), action: 'reject' })}
                                className="inline-flex items-center rounded-md bg-red-600 px-3 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-red-700 transition-colors"
                              >
                                Reject
                              </button>
                            </div>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {pendingApprovals.total_pages > 1 && (
                <div className="flex items-center justify-between mt-4 pt-4 border-t border-gray-100">
                  <p className="text-sm text-gray-500">
                    Page {pendingApprovals.page} of {pendingApprovals.total_pages} ({pendingApprovals.total} total)
                  </p>
                  <div className="flex gap-2">
                    <button type="button" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1}
                      className="rounded-md px-3 py-1 text-sm font-medium text-gray-700 ring-1 ring-inset ring-gray-300 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors">
                      Previous
                    </button>
                    <button type="button" onClick={() => setPage((p) => p + 1)} disabled={page >= pendingApprovals.total_pages}
                      className="rounded-md px-3 py-1 text-sm font-medium text-gray-700 ring-1 ring-inset ring-gray-300 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors">
                      Next
                    </button>
                  </div>
                </div>
              )}
            </>
          ) : isError ? (
            /* Never claim an empty queue on a failed request. A reviewer told
               "you're all caught up" stops looking, and the applications sit
               there unapproved. */
            <ErrorMessage
              message="Could not load the approval queue. This is a loading failure, not an empty queue — do not treat it as nothing to review."
              onRetry={() => refetch()}
            />
          ) : (
            <p className="py-10 text-center text-sm text-gray-500">No pending approvals. You&apos;re all caught up!</p>
          )}
        </div>
      </div>

      {/* ── Waiting on someone else (reassign / override) ──────────── */}
      {canStepIn && (
        <div className="bg-white border border-gray-200 rounded-xl shadow-sm">
          <div className="border-b border-gray-200 px-6 py-4">
            <h3 className="text-lg font-semibold text-gray-900">Waiting on another approver</h3>
            <p className="mt-1 text-sm text-gray-500">
              If an approver is away or has left, pass the request to someone else, or decide it yourself.
              Both need a reason, which is shown on the request and kept in the audit log.
            </p>
          </div>
          <div className="px-6 py-4">
            {stuckItems.length === 0 ? (
              <p className="text-sm text-gray-500 py-6 text-center">Nothing is waiting on anyone else.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-gray-200">
                  <thead>
                    <tr>
                      {['Employee', 'Type', 'Dates', 'Waiting on'].map((h) => (
                        <th key={h} className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">{h}</th>
                      ))}
                      <th className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-wider text-gray-500">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {stuckItems.map((app) => (
                      <tr key={app.id} className="hover:bg-gray-50">
                        <td className="px-4 py-3 text-sm font-medium text-gray-900">{app.employee_name}</td>
                        <td className="px-4 py-3 text-sm text-gray-700">{typeLabel(app)}</td>
                        <td className="px-4 py-3 text-sm text-gray-600">{app.start_date} to {app.end_date}</td>
                        <td className="px-4 py-3 text-sm text-gray-700">{currentApprover(app)}</td>
                        <td className="px-4 py-3 text-right">
                          <div className="flex flex-wrap items-center justify-end gap-2">
                            {app.actions?.can_reassign && (
                              <button type="button" onClick={() => setReassignModal(target(app))}
                                className="inline-flex items-center rounded-md bg-white px-3 py-1.5 text-xs font-semibold text-purple-700 shadow-sm ring-1 ring-inset ring-purple-300 hover:bg-purple-50">
                                Reassign approver
                              </button>
                            )}
                            <button type="button" onClick={() => setOverrideModal({ ...target(app), action: 'approve' })}
                              className="inline-flex items-center rounded-md bg-white px-3 py-1.5 text-xs font-semibold text-green-700 shadow-sm ring-1 ring-inset ring-green-300 hover:bg-green-50">
                              Override: approve
                            </button>
                            <button type="button" onClick={() => setOverrideModal({ ...target(app), action: 'reject' })}
                              className="inline-flex items-center rounded-md bg-white px-3 py-1.5 text-xs font-semibold text-red-700 shadow-sm ring-1 ring-inset ring-red-300 hover:bg-red-50">
                              Override: reject
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Approved (revocable) ────────────────────────────────────── */}
      <div className="bg-white border border-gray-200 rounded-xl shadow-sm">
        <div className="border-b border-gray-200 px-6 py-4">
          <h3 className="text-lg font-semibold text-gray-900">Approved leave</h3>
          <p className="mt-1 text-sm text-gray-500">
            Leave you approved{canStepIn ? ', or that you can reverse as an administrator' : ''}. Withdraw an
            approval made in error, or reject leave that can no longer stand. Either action puts the
            employee back on the schedule.
          </p>
        </div>
        <div className="px-6 py-4">
          {approvedLoading ? (
            <div className="text-sm text-gray-500 py-6">Loading...</div>
          ) : revocable.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200">
                <thead>
                  <tr>
                    {['Employee', 'Type', 'Dates', 'Days'].map((h) => (
                      <th key={h} className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">{h}</th>
                    ))}
                    <th className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-wider text-gray-500">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {revocable.map((app) => (
                    <tr key={app.id} className="hover:bg-gray-50 transition-colors">
                      <td className="px-4 py-3 text-sm font-medium text-gray-900">{app.employee_name}</td>
                      <td className="px-4 py-3 text-sm text-gray-700">{typeLabel(app)}</td>
                      <td className="px-4 py-3 text-sm text-gray-600">{app.start_date} to {app.end_date}</td>
                      <td className="px-4 py-3 text-sm text-gray-700 font-medium">{daysLabel(app)}</td>
                      <td className="px-4 py-3 text-right">
                        <div className="flex items-center justify-end gap-2">
                          <button type="button" onClick={() => setRevokeModal({ ...target(app), action: 'unapprove' })}
                            className="inline-flex items-center rounded-md bg-white px-3 py-1.5 text-xs font-semibold text-amber-700 shadow-sm ring-1 ring-inset ring-amber-300 hover:bg-amber-50 transition-colors"
                            title="Withdraw the approval and send it back for review">
                            Unapprove
                          </button>
                          <button type="button" onClick={() => setRevokeModal({ ...target(app), action: 'reject' })}
                            className="inline-flex items-center rounded-md bg-white px-3 py-1.5 text-xs font-semibold text-red-700 shadow-sm ring-1 ring-inset ring-red-300 hover:bg-red-50 transition-colors"
                            title="Reject this previously approved leave outright">
                            Disapprove
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-sm text-gray-500 py-6 text-center">No approved leave you can reverse.</p>
          )}
        </div>
      </div>

      {/* ── Review Modal ────────────────────────────────────────────── */}
      {reviewModal && (
        <ModalShell
          title={`${reviewModal.action === 'approve' ? 'Approve' : 'Reject'} leave request`}
          footer={
            <>
              <button type="button" onClick={closeAll} className={BTN_SECONDARY}>Cancel</button>
              <button
                type="button"
                onClick={() => reviewMutation.mutate({ id: reviewModal.id, action: reviewModal.action, notes: reviewNotes })}
                disabled={reviewMutation.isPending}
                className={`inline-flex items-center rounded-md px-4 py-2 text-sm font-semibold text-white shadow-sm disabled:opacity-50 ${
                  reviewModal.action === 'approve' ? 'bg-green-600 hover:bg-green-700' : 'bg-red-600 hover:bg-red-700'
                }`}
              >
                {reviewMutation.isPending ? 'Processing...' : reviewModal.action === 'approve' ? 'Approve' : 'Reject'}
              </button>
            </>
          }
        >
          <p className="text-sm text-gray-600">
            {reviewModal.employeeName}: {typeLabel(reviewModal.app)}, {reviewModal.app.start_date} to{' '}
            {reviewModal.app.end_date} ({daysLabel(reviewModal.app)}).
          </p>
          <p className="text-sm text-gray-600">Reason given: {reviewModal.app.reason}</p>
          <ViolationList
            items={reviewModal.app.rule_warnings}
            tone="warn"
            title="The leave policy flagged this request:"
          />
          <EventList events={reviewModal.app.events} />
          <div>
            <label htmlFor="review-notes" className="block text-sm font-medium text-gray-700 mb-1">Notes (optional)</label>
            <textarea id="review-notes" rows={3} value={reviewNotes} onChange={(e) => setReviewNotes(e.target.value)}
              placeholder="Add any notes..."
              className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none" />
          </div>
        </ModalShell>
      )}

      {/* ── Revoke Modal ────────────────────────────────────────────── */}
      {revokeModal && (
        <ModalShell
          title={revokeModal.action === 'unapprove' ? 'Withdraw approval' : 'Reject approved leave'}
          footer={
            <>
              <button type="button" onClick={closeAll} className={BTN_SECONDARY}>Cancel</button>
              <button
                type="button"
                onClick={() => revokeMutation.mutate({ id: revokeModal.id, action: revokeModal.action, notes: revokeNotes.trim() })}
                disabled={revokeMutation.isPending || !revokeNotes.trim()}
                className={`inline-flex items-center rounded-md px-4 py-2 text-sm font-semibold text-white shadow-sm disabled:opacity-50 ${
                  revokeModal.action === 'unapprove' ? 'bg-amber-600 hover:bg-amber-700' : 'bg-red-600 hover:bg-red-700'
                }`}
              >
                {revokeMutation.isPending ? 'Processing...' : revokeModal.action === 'unapprove' ? 'Withdraw approval' : 'Reject'}
              </button>
            </>
          }
        >
          <p className="text-sm text-gray-600">
            {revokeModal.action === 'unapprove'
              ? `${revokeModal.employeeName}'s leave goes back to pending and will need approving again.`
              : `${revokeModal.employeeName}'s approved leave will be rejected.`}
          </p>
          <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3">
            <p className="text-xs text-amber-800">
              Their schedule is restored: shifts that existed before the leave return to what they
              were, and shifts created purely to hold the leave are removed. The leave days go back
              to their balance, and they and the other approvers are notified.
            </p>
          </div>
          <ReasonField id="revoke-notes" value={revokeNotes} onChange={setRevokeNotes}
            placeholder="Why is this approval being reversed?"
            help="Required — the employee was already told this leave was approved." />
        </ModalShell>
      )}

      {/* ── Override Modal ──────────────────────────────────────────── */}
      {overrideModal && (
        <ModalShell
          title={overrideModal.action === 'approve' ? 'Approve on the approver’s behalf' : 'Reject on the approver’s behalf'}
          footer={
            <>
              <button type="button" onClick={closeAll} className={BTN_SECONDARY}>Cancel</button>
              <button
                type="button"
                onClick={() => overrideMutation.mutate({ id: overrideModal.id, action: overrideModal.action, reason: reason.trim() })}
                disabled={overrideMutation.isPending || !reason.trim()}
                className={`inline-flex items-center rounded-md px-4 py-2 text-sm font-semibold text-white shadow-sm disabled:opacity-50 ${
                  overrideModal.action === 'approve' ? 'bg-green-600 hover:bg-green-700' : 'bg-red-600 hover:bg-red-700'
                }`}
              >
                {overrideMutation.isPending ? 'Processing...' : overrideModal.action === 'approve' ? 'Approve by override' : 'Reject by override'}
              </button>
            </>
          }
        >
          <p className="text-sm text-gray-600">
            {overrideModal.employeeName}&apos;s {typeLabel(overrideModal.app)} ({overrideModal.app.start_date} to{' '}
            {overrideModal.app.end_date}) is waiting on {currentApprover(overrideModal.app)}. This decides it now and
            closes the remaining approval steps. {currentApprover(overrideModal.app)} and {overrideModal.employeeName} are told.
          </p>
          <ViolationList items={overrideModal.app.rule_warnings} tone="warn" title="The leave policy flagged this request:" />
          <ReasonField id="override-reason" value={reason} onChange={setReason}
            placeholder="e.g. Approver on extended leave"
            help="Required. Shown on the request and kept in the audit log." />
        </ModalShell>
      )}

      {/* ── Reassign Modal ──────────────────────────────────────────── */}
      {reassignModal && (
        <ModalShell
          title="Reassign approver"
          footer={
            <>
              <button type="button" onClick={closeAll} className={BTN_SECONDARY}>Cancel</button>
              <button
                type="button"
                onClick={() => newApprover && reassignMutation.mutate({ id: reassignModal.id, approver_id: newApprover, reason: reason.trim() })}
                disabled={reassignMutation.isPending || !newApprover || !reason.trim() || newApproverCheck?.is_active === false}
                className="inline-flex items-center rounded-md bg-purple-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-purple-700 disabled:opacity-50"
              >
                {reassignMutation.isPending ? 'Saving...' : 'Reassign'}
              </button>
            </>
          }
        >
          <p className="text-sm text-gray-600">
            {reassignModal.employeeName}&apos;s request is waiting on {currentApprover(reassignModal.app)}. Choose who
            should decide it instead. They will be notified, and so will {reassignModal.employeeName}.
          </p>
          <div>
            <UserPicker
              label="New approver"
              value={newApprover}
              onChange={(id) => setNewApprover(id)}
              excludeIds={[reassignModal.app.employee_id]}
            />
            <ApproverCheckNote userId={newApprover} />
          </div>
          <ReasonField id="reassign-reason" value={reason} onChange={setReason}
            placeholder="e.g. Approver has left the team"
            help="Required. Shown on the request and kept in the audit log." />
        </ModalShell>
      )}
    </div>
  )
}
