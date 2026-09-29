'use client'

import { useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { PayoutSchedule, PayrollPeriod, PayrollItem } from '@/types'
import { useToast } from '@/components/ui/Toast'
import { useCurrency } from '@/lib/currency'
import { useAuth } from '@/contexts/AuthContext'
import { usePermissions } from '@/contexts/PermissionsContext'
import { LoadProblem, SalaryAccessGate, useSalaryAccess } from './financeUi'

interface PeriodFormData {
  name: string
  period_type: string
  start_date: string
  end_date: string
  payout_date: string
  schedule_id: number | null
  notes: string
}

const EMPTY_PERIOD: PeriodFormData = {
  name: '',
  period_type: 'monthly',
  start_date: '',
  end_date: '',
  payout_date: '',
  schedule_id: null,
  notes: '',
}

const STATUS_COLORS: Record<string, string> = {
  draft: 'bg-gray-100 text-gray-700',
  computing: 'bg-yellow-100 text-yellow-700',
  computed: 'bg-blue-100 text-blue-700',
  compute_failed: 'bg-red-100 text-red-700',
  approved: 'bg-green-100 text-green-700',
  finalized: 'bg-purple-100 text-purple-700',
}

const STATUS_LABEL: Record<string, string> = {
  compute_failed: 'Compute failed',
}

/** Polls one computing period until it lands on computed or compute_failed.
 *  Compute runs in the background; the screen used to say "computed
 *  successfully" the moment it started and never looked again. Backs off
 *  from 1 s to 10 s and stops when unmounted. */
function ComputeWatcher({ periodId, onDone }: { periodId: number; onDone: (p: PayrollPeriod) => void }) {
  const attempts = useRef(0)
  const reported = useRef(false)
  const { data } = useQuery<PayrollPeriod>({
    queryKey: ['payroll-period', periodId],
    queryFn: () => api.getPayrollPeriod(periodId),
    refetchInterval: (query) => {
      const status = (query.state.data?.status as string | undefined) ?? 'computing'
      if (status !== 'computing') return false
      attempts.current += 1
      return Math.min(10_000, 1000 * 2 ** Math.min(attempts.current - 1, 4))
    },
  })
  useEffect(() => {
    if (data && (data.status as string) !== 'computing' && !reported.current) {
      reported.current = true
      onDone(data)
    }
  }, [data, onDone])
  return null
}

export default function PayrollTab() {
  const queryClient = useQueryClient()
  const { showToast } = useToast()
  const { user } = useAuth()
  const { hasPermission } = usePermissions()
  const canCreate = hasPermission('finances', 'create')
  // The period calendar is structure (finances:view). Computing produces
  // everyone's figures, and signing a run off means reading them, so both need
  // salary access on top of finances:edit, whatever the role. Signing off is
  // maker-checker: never by whoever computed the run (the API refuses them;
  // here they see the button disabled with the reason).
  const { isViewer, pendingViewerId } = useSalaryAccess()
  const canCompute = hasPermission('finances', 'edit') && isViewer
  const canSignOff = hasPermission('finances', 'edit') && isViewer
  const isPreparer = (p: PayrollPeriod) => !!user && p.computed_by != null && p.computed_by === user.id

  const [showForm, setShowForm] = useState(false)
  const [formData, setFormData] = useState<PeriodFormData>(EMPTY_PERIOD)
  const [selectedPeriodId, setSelectedPeriodId] = useState<number | null>(null)

  const { data: periods, isLoading, error } = useQuery<PayrollPeriod[]>({
    queryKey: ['payroll-periods'],
    queryFn: () => api.getPayrollPeriods(),
  })

  const { data: schedules } = useQuery<PayoutSchedule[]>({
    queryKey: ['payout-schedules'],
    queryFn: () => api.getPayoutSchedules(),
  })
  const scheduleName = (id?: number | null) => schedules?.find((s) => s.id === id)?.name
  const activeSchedule = schedules?.find((s) => s.is_active)

  const { data: items, isLoading: itemsLoading, error: itemsError } = useQuery<PayrollItem[]>({
    queryKey: ['payroll-items', selectedPeriodId],
    queryFn: () => api.getPayrollItems(selectedPeriodId!),
    enabled: !!selectedPeriodId && isViewer,
  })

  const createMutation = useMutation({
    mutationFn: (data: PeriodFormData) =>
      api.createPayrollPeriod({
        name: data.name,
        period_type: data.period_type,
        start_date: data.start_date,
        end_date: data.end_date,
        payout_date: data.payout_date || undefined,
        schedule_id: data.schedule_id ?? undefined,
        notes: data.notes || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['payroll-periods'] })
      setShowForm(false)
      setFormData(EMPTY_PERIOD)
      showToast('Payroll period created', 'success')
    },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  const computeMutation = useMutation({
    mutationFn: (periodId: number) => api.computePayroll(periodId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['payroll-periods'] })
      showToast('Computing payroll. This page updates when it is done.', 'info')
    },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  const approveMutation = useMutation({
    mutationFn: (periodId: number) => api.approvePayroll(periodId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['payroll-periods'] })
      showToast('Payroll approved', 'success')
    },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  const finalizeMutation = useMutation({
    mutationFn: (periodId: number) => api.finalizePayroll(periodId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['payroll-periods'] })
      showToast('Payroll finalized', 'success')
    },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  const fillPayoutFromSchedule = useMutation({
    mutationFn: () => api.previewPayoutDate(formData.end_date),
    onSuccess: (r) => {
      if (!r.payout_date) {
        showToast('The payout schedule has no cutoff for that end date.', 'error')
        return
      }
      setFormData((f) => ({ ...f, payout_date: r.payout_date as string, schedule_id: activeSchedule?.id ?? null }))
    },
    onError: (e: Error) => showToast(e.message, 'error'),
  })

  const onComputeDone = (p: PayrollPeriod) => {
    queryClient.invalidateQueries({ queryKey: ['payroll-periods'] })
    queryClient.invalidateQueries({ queryKey: ['payroll-items', p.id] })
    if ((p.status as string) === 'compute_failed') {
      showToast(`Payroll for ${p.name} could not be computed. See the details below.`, 'error')
      setSelectedPeriodId(p.id)
    } else {
      const skipped = p.compute_progress?.skipped?.length ?? 0
      const warnings = p.compute_progress?.warnings?.length ?? 0
      showToast(
        `Payroll for ${p.name} computed${skipped ? `, ${skipped} employee(s) skipped` : ''}${warnings ? `, ${warnings} warning(s)` : ''}.`,
        skipped || warnings ? 'info' : 'success',
      )
    }
  }

  const selectedPeriod = periods?.find((p) => p.id === selectedPeriodId)
  const computing = (periods ?? []).filter((p) => (p.status as string) === 'computing')

  const { format: formatCurrency } = useCurrency()

  function handleCreateSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (formData.end_date < formData.start_date) {
      showToast('The end date must be on or after the start date.', 'error')
      return
    }
    createMutation.mutate(formData)
  }

  return (
    <div className="space-y-6">
      {computing.map((p) => (
        <ComputeWatcher key={p.id} periodId={p.id} onDone={onComputeDone} />
      ))}

      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-gray-900">Payroll Periods</h2>
        {!showForm && canCreate && !error && (
          <button
            onClick={() => setShowForm(true)}
            className="rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700"
          >
            New Period
          </button>
        )}
      </div>

      {/* Create Period Form */}
      {showForm && (
        <form onSubmit={handleCreateSubmit} className="rounded-lg border border-gray-200 bg-white p-4 space-y-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="sm:col-span-2">
              <label htmlFor="pp-name" className="block text-sm font-medium text-gray-700">Period Name</label>
              <input
                id="pp-name"
                type="text"
                required
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-purple-500 focus:ring-purple-500"
                placeholder="e.g. January 2026"
              />
            </div>
            <div>
              <label htmlFor="pp-type" className="block text-sm font-medium text-gray-700">Type</label>
              <select
                id="pp-type"
                value={formData.period_type}
                onChange={(e) => setFormData({ ...formData, period_type: e.target.value })}
                className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-purple-500 focus:ring-purple-500"
              >
                <option value="monthly">Monthly</option>
                <option value="semi_monthly">Semi-Monthly</option>
                <option value="biweekly">Every two weeks</option>
                <option value="weekly">Weekly</option>
              </select>
            </div>
            <div />
            <div>
              <label htmlFor="pp-start" className="block text-sm font-medium text-gray-700">Start Date</label>
              <input
                id="pp-start"
                type="date"
                required
                value={formData.start_date}
                onChange={(e) => setFormData({ ...formData, start_date: e.target.value })}
                className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-purple-500 focus:ring-purple-500"
              />
            </div>
            <div>
              <label htmlFor="pp-end" className="block text-sm font-medium text-gray-700">End Date</label>
              <input
                id="pp-end"
                type="date"
                required
                value={formData.end_date}
                onChange={(e) => setFormData({ ...formData, end_date: e.target.value })}
                className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-purple-500 focus:ring-purple-500"
              />
            </div>
          </div>
          <div>
            <label htmlFor="pp-payout" className="block text-sm font-medium text-gray-700">Payout Date (optional)</label>
            <div className="mt-1 flex flex-wrap gap-2">
              <input
                id="pp-payout"
                type="date"
                value={formData.payout_date}
                onChange={(e) => setFormData({ ...formData, payout_date: e.target.value, schedule_id: null })}
                className="block w-full max-w-xs rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-purple-500 focus:ring-purple-500"
              />
              {activeSchedule && (
                <button
                  type="button"
                  disabled={!formData.end_date || fillPayoutFromSchedule.isPending}
                  onClick={() => fillPayoutFromSchedule.mutate()}
                  className="rounded-md border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
                >
                  Use {activeSchedule.name}
                </button>
              )}
            </div>
            {formData.schedule_id && (
              <p className="mt-1 text-xs text-purple-700">From payout schedule {scheduleName(formData.schedule_id)}.</p>
            )}
            <p className="mt-1 text-xs text-gray-500">
              When set, this run also pays every bonus, incentive, allowance and leave-cash
              line scheduled for this payout date — even if earned in an earlier period.
            </p>
          </div>
          <div>
            <label htmlFor="pp-notes" className="block text-sm font-medium text-gray-700">Notes</label>
            <input
              id="pp-notes"
              type="text"
              value={formData.notes}
              onChange={(e) => setFormData({ ...formData, notes: e.target.value })}
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-purple-500 focus:ring-purple-500"
            />
          </div>
          <div className="flex justify-end gap-2">
            <button type="button" onClick={() => { setShowForm(false); setFormData(EMPTY_PERIOD) }} className="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50">
              Cancel
            </button>
            <button type="submit" disabled={createMutation.isPending} className="rounded-md bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50">
              Create
            </button>
          </div>
        </form>
      )}

      {/* Periods List */}
      {isLoading ? (
        <div className="text-center py-8 text-gray-500">Loading...</div>
      ) : error ? (
        <LoadProblem error={error} what="payroll periods" />
      ) : !periods?.length ? (
        <div className="text-center py-8 text-gray-500">
          No payroll periods yet.{canCreate ? ' Create one to get started.' : ''}
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Period</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Type</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Date Range</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Payout</th>
                <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase">Status</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Employees</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Total Gross</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Total Net</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 bg-white">
              {periods.map((p) => {
                const status = p.status as string
                const progress = p.compute_progress
                return (
                  <tr
                    key={p.id}
                    onClick={() => setSelectedPeriodId(p.id === selectedPeriodId ? null : p.id)}
                    className={`cursor-pointer hover:bg-gray-50 ${selectedPeriodId === p.id ? 'bg-purple-50' : ''}`}
                  >
                    <td className="px-4 py-3 text-sm font-medium text-gray-900">{p.name}</td>
                    <td className="px-4 py-3 text-sm text-gray-500 capitalize">{p.period_type.replace('_', '-')}</td>
                    <td className="px-4 py-3 text-sm text-gray-500">{p.start_date} — {p.end_date}</td>
                    <td className="px-4 py-3 text-sm text-gray-500">
                      {p.payout_date || '—'}
                      {p.schedule_id && scheduleName(p.schedule_id) && (
                        <span className="block text-xs text-gray-400">{scheduleName(p.schedule_id)}</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-center">
                      <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium capitalize ${STATUS_COLORS[status] || 'bg-gray-100 text-gray-700'}`}>
                        {STATUS_LABEL[status] ?? status}
                      </span>
                      {status === 'computing' && progress?.total ? (
                        <span className="mt-1 block text-xs text-gray-500">
                          {progress.done ?? 0} of {progress.total}
                        </span>
                      ) : null}
                      {status === 'computed' && (progress?.skipped?.length || progress?.warnings?.length) ? (
                        <span className="mt-1 block text-xs text-amber-700">Needs a look</span>
                      ) : null}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-500 text-right">{p.item_count || 0}</td>
                    {p.figures_hidden ? (
                      <>
                        <td className="px-4 py-3 text-sm text-gray-400 text-right" title="Needs salary access">Hidden</td>
                        <td className="px-4 py-3 text-sm text-gray-400 text-right" title="Needs salary access">Hidden</td>
                      </>
                    ) : (
                      <>
                        <td className="px-4 py-3 text-sm text-gray-900 text-right">{formatCurrency(p.total_gross || 0)}</td>
                        <td className="px-4 py-3 text-sm text-gray-900 text-right">{formatCurrency(p.total_net || 0)}</td>
                      </>
                    )}
                    <td className="px-4 py-3 text-right space-x-1" onClick={(e) => e.stopPropagation()}>
                      {canCompute && (status === 'draft' || status === 'computed' || status === 'compute_failed') && (
                        <button
                          onClick={() => computeMutation.mutate(p.id)}
                          disabled={computeMutation.isPending}
                          className="text-sm text-blue-600 hover:text-blue-800 disabled:opacity-50"
                        >
                          {status === 'compute_failed' ? 'Retry' : status === 'computed' ? 'Recompute' : 'Compute'}
                        </button>
                      )}
                      {status === 'computing' && <span className="text-sm text-gray-500">Computing…</span>}
                      {canSignOff && status === 'computed' && (
                        <SignOffButton
                          label="Approve"
                          verb="approve"
                          preparer={isPreparer(p)}
                          busy={approveMutation.isPending}
                          onClick={() => approveMutation.mutate(p.id)}
                          className="text-green-600 hover:text-green-800"
                        />
                      )}
                      {canSignOff && status === 'approved' && (
                        <SignOffButton
                          label="Finalize"
                          verb="finalize"
                          preparer={isPreparer(p)}
                          busy={finalizeMutation.isPending}
                          onClick={() => finalizeMutation.mutate(p.id)}
                          className="text-purple-600 hover:text-purple-800"
                        />
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Selected Period Details */}
      {selectedPeriodId && selectedPeriod && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-md font-semibold text-gray-900">
              {selectedPeriod.name} — Payroll Items
            </h3>
            <button
              onClick={() => setSelectedPeriodId(null)}
              className="text-sm text-gray-500 hover:text-gray-700"
            >
              Close
            </button>
          </div>

          <PeriodOutcome
            period={selectedPeriod}
            canRetry={canCompute}
            onRetry={() => computeMutation.mutate(selectedPeriod.id)}
            retrying={computeMutation.isPending}
          />

          {!isViewer ? (
            <SalaryAccessGate what="this run's payroll figures" pendingId={pendingViewerId} />
          ) : (
          <>
          {/* Summary Cards */}
          {items && items.length > 0 && (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <div className="rounded-lg border border-gray-200 bg-white p-3">
                <p className="text-xs text-gray-500">Total Gross</p>
                <p className="text-lg font-semibold text-gray-900">
                  {formatCurrency(items.reduce((s, i) => s + i.gross_pay, 0))}
                </p>
              </div>
              <div className="rounded-lg border border-gray-200 bg-white p-3">
                <p className="text-xs text-gray-500">Total Deductions</p>
                <p className="text-lg font-semibold text-red-600">
                  {formatCurrency(items.reduce((s, i) => s + i.total_deductions, 0))}
                </p>
              </div>
              <div className="rounded-lg border border-gray-200 bg-white p-3">
                <p className="text-xs text-gray-500">Employer Contributions</p>
                <p className="text-lg font-semibold text-orange-600">
                  {formatCurrency(items.reduce((s, i) => s + i.total_contributions, 0))}
                </p>
              </div>
              <div className="rounded-lg border border-gray-200 bg-white p-3">
                <p className="text-xs text-gray-500">Total Net Pay</p>
                <p className="text-lg font-semibold text-green-600">
                  {formatCurrency(items.reduce((s, i) => s + i.net_pay, 0))}
                </p>
              </div>
            </div>
          )}

          {/* Items Table */}
          {itemsLoading ? (
            <div className="text-center py-4 text-gray-500">Loading items...</div>
          ) : itemsError ? (
            <LoadProblem error={itemsError} what="this run's payroll items" />
          ) : !items?.length ? (
            <div className="text-center py-4 text-gray-500">
              No payroll items yet.{canCompute ? ' Click "Compute" to generate payroll for this period.' : ''}
            </div>
          ) : (
            <div className="overflow-x-auto rounded-lg border border-gray-200">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Employee</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Grade</th>
                    <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Base Pay</th>
                    <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">OT &amp; Premiums</th>
                    <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Gross</th>
                    <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Deductions</th>
                    <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Employer share</th>
                    <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Net Pay</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200 bg-white">
                  {items.map((item) => {
                    const warnings = (item.breakdown?.warnings as string[] | undefined) ?? []
                    return (
                      <tr key={item.id}>
                        <td className="px-4 py-3 text-sm text-gray-900">
                          {item.employee_name || `Employee #${item.employee_id}`}
                          {warnings.map((w) => (
                            <span key={w} className="mt-0.5 block text-xs text-amber-700">{w}</span>
                          ))}
                        </td>
                        <td className="px-4 py-3 text-sm text-gray-500">{item.grade_name || '—'}</td>
                        <td className="px-4 py-3 text-sm text-gray-900 text-right">{formatCurrency(item.base_pay)}</td>
                        <td className="px-4 py-3 text-sm text-gray-900 text-right">{item.overtime_pay > 0 ? formatCurrency(item.overtime_pay) : '—'}</td>
                        <td className="px-4 py-3 text-sm font-medium text-gray-900 text-right">{formatCurrency(item.gross_pay)}</td>
                        <td className="px-4 py-3 text-sm text-red-600 text-right">{formatCurrency(item.total_deductions)}</td>
                        <td className="px-4 py-3 text-sm text-orange-600 text-right">{item.total_contributions > 0 ? formatCurrency(item.total_contributions) : '—'}</td>
                        <td className="px-4 py-3 text-sm font-semibold text-green-700 text-right">{formatCurrency(item.net_pay)}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
          </>
          )}
        </div>
      )}
    </div>
  )
}

/** Approve or Finalize. For whoever computed the run it stays visible but
 *  disabled, with the reason, so they know the next step is someone else's. */
function SignOffButton({ label, verb, preparer, busy, onClick, className }: {
  label: string
  verb: 'approve' | 'finalize'
  preparer: boolean
  busy: boolean
  onClick: () => void
  className: string
}) {
  if (preparer) {
    const why = `You computed this run; someone else must ${verb} it`
    return (
      <span className="inline-flex flex-col items-end">
        <button disabled title={why} className="text-sm text-gray-400 cursor-not-allowed">
          {label}
        </button>
        <span className="text-xs text-gray-500">{why}</span>
      </span>
    )
  }
  return (
    <button onClick={onClick} disabled={busy} className={`text-sm disabled:opacity-50 ${className}`}>
      {label}
    </button>
  )
}

/** What the last compute left behind: the failure reason with Retry, who was
 *  skipped for having no salary (with a way to assign one), and warnings such
 *  as a tiered deduction with no brackets. None of this was ever shown. */
function PeriodOutcome({ period, canRetry, onRetry, retrying }: {
  period: PayrollPeriod
  canRetry: boolean
  onRetry: () => void
  retrying: boolean
}) {
  const status = period.status as string
  const progress = period.compute_progress
  if (status === 'computing') {
    const pct = progress?.total ? Math.round(((progress.done ?? 0) / progress.total) * 100) : null
    return (
      <div className="rounded-lg border border-yellow-200 bg-yellow-50 p-3 text-sm text-yellow-900" role="status">
        Computing payroll{pct != null ? `: ${progress?.done ?? 0} of ${progress?.total} employees (${pct}%)` : '…'}
        {pct != null && (
          <div className="mt-2 h-2 w-full rounded-full bg-yellow-100">
            <div className="h-2 rounded-full bg-yellow-500" style={{ width: `${pct}%` }} />
          </div>
        )}
      </div>
    )
  }
  if (status === 'compute_failed') {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-900" role="alert">
        <p className="font-medium">This payroll could not be computed.</p>
        <p className="mt-1">{progress?.error || period.notes || 'No reason was recorded.'}</p>
        {canRetry && (
          <button onClick={onRetry} disabled={retrying}
            className="mt-2 rounded-md bg-red-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-red-700 disabled:opacity-50">
            Retry
          </button>
        )}
      </div>
    )
  }
  const skipped = progress?.skipped ?? []
  const warnings = progress?.warnings ?? []
  if (!skipped.length && !warnings.length) return null
  return (
    <div className="space-y-3">
      {skipped.length > 0 && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
          <p className="font-medium">
            {skipped.length} employee{skipped.length === 1 ? ' was' : 's were'} left out: no salary on {period.end_date}.
          </p>
          <ul className="mt-1 list-disc pl-5">
            {skipped.map((s) => <li key={s.employee_id}>{s.employee_name}</li>)}
          </ul>
          <Link href="/finances?tab=employee-salaries" className="mt-2 inline-block font-semibold text-purple-700 underline">
            Assign salaries
          </Link>
          <span className="text-amber-800">, then compute again.</span>
        </div>
      )}
      {warnings.length > 0 && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
          <p className="font-medium">Warnings from the last compute</p>
          <ul className="mt-1 list-disc pl-5">
            {warnings.map((w, i) => <li key={i}><span className="font-medium">{w.employee_name}:</span> {w.message}</li>)}
          </ul>
        </div>
      )}
    </div>
  )
}
