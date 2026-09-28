'use client'

import { Fragment, useEffect, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import {
  LeaveApplication,
  LeaveBalance,
  LeaveTypeConfig,
  ApprovalChainPreviewItem,
  LeavePrecheckResult,
  LeaveRuleViolation,
  PaginatedResponse,
} from '@/types'
import { useToast } from '@/components/ui/Toast'
import { UserPicker } from '@/components/ui'
import { usePermissions } from '@/contexts/PermissionsContext'
import {
  DayBreakdown,
  EventList,
  STATUS_COLORS,
  STATUS_FILTERS,
  StepDots,
  ViolationList,
  daysLabel,
  errorViolations,
  typeLabel,
} from './leaveUi'

interface ApplyFormData {
  leave_type: string
  start_date: string
  end_date: string
  half_day: '' | 'am' | 'pm'
  reason: string
}

const EMPTY_FORM: ApplyFormData = { leave_type: '', start_date: '', end_date: '', half_day: '', reason: '' }

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return v
}

const INPUT =
  'block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none'

const SOURCE_NOTE: Record<string, string> = {
  self_approval: 'Nobody else in your company can approve leave, so you will be asked to self-approve. This is recorded.',
}

export default function MyLeaveTab() {
  const queryClient = useQueryClient()
  const { showToast } = useToast()
  const { hasPermission } = usePermissions()
  const canFileForOthers = hasPermission('leave', 'create')

  const [showApplyForm, setShowApplyForm] = useState(false)
  const [form, setForm] = useState<ApplyFormData>(EMPTY_FORM)
  const [onBehalfOf, setOnBehalfOf] = useState<number | null>(null)
  // Editing an existing pending request. Changing it re-runs every leave rule,
  // and if an approver had already approved a step the approvals start over.
  const [editingApp, setEditingApp] = useState<LeaveApplication | null>(null)
  const [submitErrors, setSubmitErrors] = useState<LeaveRuleViolation[]>([])
  const [statusFilter, setStatusFilter] = useState<string>('all')
  const [page, setPage] = useState(1)
  const [cancelConfirmId, setCancelConfirmId] = useState<number | null>(null)
  const [selfApprove, setSelfApprove] = useState<LeaveApplication | null>(null)
  const [selfReason, setSelfReason] = useState('')
  const [expanded, setExpanded] = useState<number | null>(null)

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

  // Live preview: the days this request would cost (from the roster, the
  // company work week and holidays) and anything the policy objects to.
  const halfDayAllowed = !!form.start_date && form.start_date === form.end_date
  const previewInput = useDebounced(
    {
      leave_type: form.leave_type,
      start_date: form.start_date,
      end_date: form.end_date,
      half_day: halfDayAllowed && form.half_day ? form.half_day : null,
      employee_id: onBehalfOf ?? undefined,
      application_id: editingApp?.id,
    },
    350,
  )
  const previewReady =
    !!previewInput.leave_type && !!previewInput.start_date && !!previewInput.end_date &&
    previewInput.end_date >= previewInput.start_date
  const { data: preview, error: previewError } = useQuery<LeavePrecheckResult>({
    queryKey: ['leave-preview', previewInput],
    queryFn: () => api.previewLeave(previewInput),
    enabled: showApplyForm && previewReady,
  })

  // ── Mutations ──────────────────────────────────────────────────────
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['my-leave-applications'] })
    queryClient.invalidateQueries({ queryKey: ['my-leave-balance'] })
    queryClient.invalidateQueries({ queryKey: ['team-leave-applications'] })
  }

  const applyMutation = useMutation({
    mutationFn: (data: ApplyFormData) =>
      editingApp
        ? api.updateLeaveApplication(editingApp.id, {
            leave_type: data.leave_type,
            start_date: data.start_date,
            end_date: data.end_date,
            half_day: halfDayAllowed && data.half_day ? data.half_day : null,
            reason: data.reason,
          })
        : api.createLeaveApplication({
        leave_type: data.leave_type,
        start_date: data.start_date,
        end_date: data.end_date,
        half_day: halfDayAllowed && data.half_day ? data.half_day : null,
        reason: data.reason,
        ...(onBehalfOf ? { employee_id: onBehalfOf } : {}),
      }),
    onSuccess: () => {
      invalidate()
      setShowApplyForm(false)
      setForm(EMPTY_FORM)
      setOnBehalfOf(null)
      setSubmitErrors([])
      showToast(editingApp ? 'Leave request updated; your approver has been told' : 'Leave request submitted', 'success')
      setEditingApp(null)
    },
    onError: (err: Error) => {
      const list = errorViolations(err)
      setSubmitErrors(list)
      showToast(list.length ? 'The leave policy does not allow this request.' : err.message, 'error')
    },
  })

  const cancelMutation = useMutation({
    mutationFn: (id: number) => api.cancelLeaveApplication(id),
    onSuccess: () => {
      invalidate()
      setCancelConfirmId(null)
      showToast('Leave request cancelled', 'success')
    },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  const selfApproveMutation = useMutation({
    mutationFn: ({ id, reason }: { id: number; reason: string }) => api.selfApproveLeaveApplication(id, { reason }),
    onSuccess: () => {
      invalidate()
      setSelfApprove(null)
      setSelfReason('')
      showToast('Leave self-approved and recorded', 'success')
    },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    setSubmitErrors([])
    applyMutation.mutate(form)
  }

  const activeTypes = leaveTypes?.filter((t) => t.is_active) ?? []
  const blocked = !!preview && !preview.allowed

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
                {balance.pool_type === 'shared' && ' · Shared pool'}
              </p>
            )}
          </div>
          {!showApplyForm && (
            <button
              type="button"
              onClick={() => setShowApplyForm(true)}
              className="inline-flex items-center gap-1.5 rounded-md bg-purple-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-purple-700 transition-colors"
            >
              Apply for Leave
            </button>
          )}
        </div>

        {balanceLoading ? (
          <p className="text-sm text-gray-500">Loading balance...</p>
        ) : balance && balance.balances.length > 0 ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {balance.balances.map((b) => {
              const usedPct = b.total_days > 0 ? Math.min(100, (b.used_days / b.total_days) * 100) : 0
              const pendingPct = b.total_days > 0 ? Math.min(100 - usedPct, (b.pending_days / b.total_days) * 100) : 0
              return (
                <div key={b.leave_type} className="bg-white border border-gray-200 rounded-lg p-4">
                  <h4 className="text-sm font-semibold text-gray-900 truncate">{b.leave_type_name || b.leave_type}</h4>
                  <div className="mt-2 flex items-baseline gap-1">
                    <span className={`text-2xl font-bold ${b.available_days < 0 ? 'text-red-600' : 'text-purple-600'}`}>{b.available_days}</span>
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
          <h3 className="text-lg font-semibold text-gray-900">{editingApp ? 'Change leave request' : 'Apply for Leave'}</h3>
          {editingApp && editingApp.approval_steps.some((s) => s.status === 'approved') && (
            <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
              Part of this request is already approved. Saving a change sends it back to the first approver.
            </p>
          )}
          <form onSubmit={handleSubmit} className="space-y-4">
            {canFileForOthers && !editingApp && (
              <div className="max-w-md">
                <UserPicker
                  label="Filing for someone else? (optional)"
                  value={onBehalfOf}
                  onChange={(id) => setOnBehalfOf(id)}
                  placeholder="Leave empty to file for yourself"
                />
              </div>
            )}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
              <div>
                <label htmlFor="apply-type" className="block text-sm font-medium text-gray-700 mb-1">Leave Type</label>
                <select id="apply-type" required value={form.leave_type}
                  onChange={(e) => setForm((p) => ({ ...p, leave_type: e.target.value }))} className={INPUT}>
                  <option value="">Select type</option>
                  {activeTypes.map((lt) => (
                    <option key={lt.code} value={lt.code}>{lt.name}</option>
                  ))}
                </select>
              </div>
              <div>
                <label htmlFor="apply-start" className="block text-sm font-medium text-gray-700 mb-1">Start Date</label>
                <input id="apply-start" type="date" required value={form.start_date}
                  onChange={(e) => setForm((p) => ({ ...p, start_date: e.target.value }))} className={INPUT} />
              </div>
              <div>
                <label htmlFor="apply-end" className="block text-sm font-medium text-gray-700 mb-1">End Date</label>
                <input id="apply-end" type="date" required value={form.end_date} min={form.start_date || undefined}
                  onChange={(e) => setForm((p) => ({ ...p, end_date: e.target.value }))} className={INPUT} />
              </div>
              <div>
                <label htmlFor="apply-half" className="block text-sm font-medium text-gray-700 mb-1">Half day</label>
                <select id="apply-half" value={halfDayAllowed ? form.half_day : ''} disabled={!halfDayAllowed}
                  onChange={(e) => setForm((p) => ({ ...p, half_day: e.target.value as ApplyFormData['half_day'] }))}
                  className={`${INPUT} disabled:bg-gray-50 disabled:text-gray-400`}>
                  <option value="">Full day</option>
                  <option value="am">Morning off (AM)</option>
                  <option value="pm">Afternoon off (PM)</option>
                </select>
                <p className="mt-1 text-xs text-gray-500">
                  {halfDayAllowed ? 'Counts as half a day.' : 'Available when start and end are the same day.'}
                </p>
              </div>
            </div>
            <div>
              <label htmlFor="apply-reason" className="block text-sm font-medium text-gray-700 mb-1">Reason</label>
              <textarea id="apply-reason" required rows={3} value={form.reason}
                onChange={(e) => setForm((p) => ({ ...p, reason: e.target.value }))}
                placeholder="Provide a reason for your leave request" className={INPUT} />
            </div>

            {/* What this request costs, before submitting */}
            {previewReady && preview && (
              <div className="space-y-2">
                {preview.problem ? (
                  <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800" role="alert">{preview.problem}</p>
                ) : (
                  <DayBreakdown items={preview.day_breakdown} total={preview.days_requested} />
                )}
                {Object.keys(preview.days_by_year).length > 1 && (
                  <p className="text-xs text-gray-600">
                    Charged by year:{' '}
                    {Object.entries(preview.days_by_year).map(([y, d]) => `${d} day(s) from ${y}`).join(', ')}.
                  </p>
                )}
                <ViolationList items={preview.violations} tone="block" title="This request cannot be filed:" />
                <ViolationList items={preview.warnings} tone="warn" title="Please check before submitting:" />
              </div>
            )}
            {previewError && <p className="text-sm text-red-700">{(previewError as Error).message}</p>}
            <ViolationList items={submitErrors} tone="block" title="This request cannot be filed:" />

            {/* Approval chain preview (own requests only) */}
            {!onBehalfOf && chainPreview && chainPreview.chain.length > 0 && (
              <div className="bg-purple-50 border border-purple-200 rounded-lg p-3">
                <p className="text-xs font-medium text-purple-700 mb-2">Your request will be reviewed by:</p>
                <div className="flex flex-wrap gap-2">
                  {chainPreview.chain.map((step, i) => (
                    <div key={i} className="flex items-center gap-1">
                      <span className="inline-flex items-center justify-center h-5 w-5 rounded-full bg-purple-200 text-purple-800 text-xs font-bold">
                        {step.step_order}
                      </span>
                      <span className="text-sm text-purple-800">
                        {step.source === 'self_approval' ? 'You (self-approval)' : step.approver_name}
                        {step.is_deputy ? ' (standing in as deputy)' : ''}
                      </span>
                      {i < chainPreview.chain.length - 1 && <span className="mx-1 text-purple-300" aria-hidden>&rarr;</span>}
                    </div>
                  ))}
                </div>
                {chainPreview.chain.map((s) => SOURCE_NOTE[s.source]).filter(Boolean).map((note) => (
                  <p key={note} className="mt-2 text-xs text-purple-800">{note}</p>
                ))}
              </div>
            )}

            <div className="flex items-center gap-3">
              <button type="submit" disabled={applyMutation.isPending || blocked}
                className="inline-flex items-center rounded-md bg-purple-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors">
                {applyMutation.isPending ? 'Saving...' : editingApp ? 'Save changes' : 'Submit request'}
              </button>
              <button type="button"
                onClick={() => { setShowApplyForm(false); setForm(EMPTY_FORM); setOnBehalfOf(null); setSubmitErrors([]); setEditingApp(null) }}
                className="inline-flex items-center rounded-md bg-white px-4 py-2 text-sm font-semibold text-gray-700 shadow-sm ring-1 ring-inset ring-gray-300 hover:bg-gray-50 transition-colors">
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
          <div className="mt-3 flex flex-wrap gap-2">
            {STATUS_FILTERS.map((s) => (
              <button key={s} onClick={() => { setStatusFilter(s); setPage(1) }}
                className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
                  statusFilter === s ? 'bg-purple-100 text-purple-700' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                }`}>
                {s.charAt(0).toUpperCase() + s.slice(1)}
              </button>
            ))}
          </div>
        </div>
        <div className="px-6 py-4">
          {appsLoading ? (
            <p className="text-sm text-gray-500 py-8">Loading...</p>
          ) : applications && applications.items.length > 0 ? (
            <>
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-gray-200">
                  <thead>
                    <tr>
                      {['Type', 'Dates', 'Days', 'Status', 'Approval progress'].map((h) => (
                        <th key={h} className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">{h}</th>
                      ))}
                      <th className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-wider text-gray-500">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {applications.items.map((app) => (
                      <Fragment key={app.id}>
                        <tr className="hover:bg-gray-50 transition-colors">
                          <td className="px-4 py-3 text-sm text-gray-900">
                            <button type="button" className="text-left hover:underline" onClick={() => setExpanded(expanded === app.id ? null : app.id)}
                              aria-expanded={expanded === app.id}>
                              {typeLabel(app)}
                            </button>
                          </td>
                          <td className="px-4 py-3 text-sm text-gray-600">{app.start_date} to {app.end_date}</td>
                          <td className="px-4 py-3 text-sm text-gray-700 font-medium">{daysLabel(app)}</td>
                          <td className="px-4 py-3">
                            <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${STATUS_COLORS[app.status] ?? 'bg-gray-100 text-gray-600'}`}>
                              {app.status}
                            </span>
                          </td>
                          <td className="px-4 py-3"><StepDots app={app} /></td>
                          <td className="px-4 py-3 text-right">
                            <div className="flex items-center justify-end gap-1">
                              {app.actions?.can_self_approve && (
                                <button type="button" onClick={() => setSelfApprove(app)}
                                  className="inline-flex items-center rounded-md bg-amber-50 px-2 py-1 text-xs font-medium text-amber-800 ring-1 ring-inset ring-amber-300 hover:bg-amber-100">
                                  Self-approve (no other approver exists)
                                </button>
                              )}
                              {app.actions?.can_edit && (
                                <button type="button"
                                  onClick={() => {
                                    setEditingApp(app)
                                    setOnBehalfOf(null)
                                    setSubmitErrors([])
                                    setForm({
                                      leave_type: app.leave_type,
                                      start_date: app.start_date,
                                      end_date: app.end_date,
                                      half_day: app.half_day ?? '',
                                      reason: app.reason,
                                    })
                                    setShowApplyForm(true)
                                  }}
                                  className="inline-flex items-center rounded-md px-2 py-1 text-xs font-medium text-purple-700 hover:bg-purple-50">
                                  Change
                                </button>
                              )}
                              {app.actions?.can_cancel && (
                                cancelConfirmId === app.id ? (
                                  <>
                                    <button type="button" onClick={() => cancelMutation.mutate(app.id)} disabled={cancelMutation.isPending}
                                      className="inline-flex items-center rounded-md bg-red-600 px-2 py-1 text-xs font-medium text-white hover:bg-red-700 disabled:opacity-50">
                                      Confirm
                                    </button>
                                    <button type="button" onClick={() => setCancelConfirmId(null)}
                                      className="inline-flex items-center rounded-md bg-gray-100 px-2 py-1 text-xs font-medium text-gray-600 hover:bg-gray-200">
                                      No
                                    </button>
                                  </>
                                ) : (
                                  <button type="button" onClick={() => setCancelConfirmId(app.id)}
                                    className="inline-flex items-center rounded-md px-2 py-1 text-xs font-medium text-red-600 hover:bg-red-50">
                                    Cancel
                                  </button>
                                )
                              )}
                            </div>
                          </td>
                        </tr>
                        {expanded === app.id && (
                          <tr>
                            <td colSpan={6} className="px-4 pb-4 space-y-2">
                              {app.day_breakdown && app.day_breakdown.length > 0 && (
                                <DayBreakdown items={app.day_breakdown} total={app.days_requested} />
                              )}
                              <ViolationList items={app.rule_warnings} tone="warn" title="Shown to your approver:" />
                              {app.reviewer_notes && <p className="text-xs text-gray-600">Decision note: {app.reviewer_notes}</p>}
                              <EventList events={app.events} />
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    ))}
                  </tbody>
                </table>
              </div>
              {applications.total_pages > 1 && (
                <div className="flex items-center justify-between mt-4 pt-4 border-t border-gray-100">
                  <p className="text-sm text-gray-500">
                    Page {applications.page} of {applications.total_pages} ({applications.total} total)
                  </p>
                  <div className="flex gap-2">
                    <button type="button" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1}
                      className="rounded-md px-3 py-1 text-sm font-medium text-gray-700 ring-1 ring-inset ring-gray-300 hover:bg-gray-50 disabled:opacity-50">
                      Previous
                    </button>
                    <button type="button" onClick={() => setPage((p) => p + 1)} disabled={page >= applications.total_pages}
                      className="rounded-md px-3 py-1 text-sm font-medium text-gray-700 ring-1 ring-inset ring-gray-300 hover:bg-gray-50 disabled:opacity-50">
                      Next
                    </button>
                  </div>
                </div>
              )}
            </>
          ) : (
            <p className="text-sm text-gray-500 py-8 text-center">No leave requests found.</p>
          )}
        </div>
      </div>

      {/* ── Self-approve Modal ─────────────────────────────────────── */}
      {selfApprove && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" role="dialog" aria-modal="true" aria-label="Self-approve leave">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-md mx-4 p-6 space-y-4">
            <h3 className="text-lg font-semibold text-gray-900">Self-approve your leave</h3>
            <p className="text-sm text-gray-600">
              Nobody else in your company can approve leave, so you may approve your own{' '}
              {typeLabel(selfApprove)} ({selfApprove.start_date} to {selfApprove.end_date}). This is shown on
              the request and kept in the audit log. If someone else is later given leave approval rights,
              ask them instead.
            </p>
            <div>
              <label htmlFor="self-reason" className="block text-sm font-medium text-gray-700 mb-1">
                Reason <span className="text-red-500">*</span>
              </label>
              <textarea id="self-reason" rows={3} value={selfReason} onChange={(e) => setSelfReason(e.target.value)}
                placeholder="e.g. Sole administrator; no one else can approve" className={INPUT} />
            </div>
            <div className="flex items-center justify-end gap-3">
              <button type="button" onClick={() => { setSelfApprove(null); setSelfReason('') }}
                className="inline-flex items-center rounded-md bg-white px-4 py-2 text-sm font-semibold text-gray-700 shadow-sm ring-1 ring-inset ring-gray-300 hover:bg-gray-50">
                Cancel
              </button>
              <button type="button" disabled={!selfReason.trim() || selfApproveMutation.isPending}
                onClick={() => selfApproveMutation.mutate({ id: selfApprove.id, reason: selfReason.trim() })}
                className="inline-flex items-center rounded-md bg-amber-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-amber-700 disabled:opacity-50">
                {selfApproveMutation.isPending ? 'Saving...' : 'Self-approve'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
