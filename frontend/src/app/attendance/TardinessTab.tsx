'use client'

import { useEffect, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { SuggestedDeduction, TardinessRecord } from '@/types'
import { useToast } from '@/components/ui/Toast'
import { usePermissions } from '@/contexts/PermissionsContext'
import { useCurrency } from '@/lib/currency'

const RESOLUTION_BADGE: Record<string, string> = {
  salary_deduction: 'bg-red-100 text-red-800',
  leave_deduction: 'bg-orange-100 text-orange-800',
  excused: 'bg-green-100 text-green-800',
  warning: 'bg-yellow-100 text-yellow-800',
}

const RESOLUTION_OPTIONS = [
  { value: 'salary_deduction', label: 'Salary Deduction' },
  { value: 'leave_deduction', label: 'Leave Deduction' },
  { value: 'excused', label: 'Excused' },
  { value: 'warning', label: 'Warning' },
]

export default function TardinessTab() {
  const queryClient = useQueryClient()
  const { showToast } = useToast()
  const { hasPermission } = usePermissions()
  const canEdit = hasPermission('schedules', 'edit')

  const { format: money } = useCurrency()
  const [resolutionFilter, setResolutionFilter] = useState('')
  const [resolving, setResolving] = useState<TardinessRecord | null>(null)

  const { data: records, isLoading } = useQuery<TardinessRecord[]>({
    queryKey: ['tardiness-records', resolutionFilter],
    queryFn: () => api.listTardinessRecords({ resolution_type: resolutionFilter || undefined }),
  })

  const formatMinutes = (m: number) => {
    const h = Math.floor(m / 60)
    const min = m % 60
    return h > 0 ? `${h}h ${min}m` : `${min}m`
  }

  return (
    <div className="space-y-6">
      <div className="bg-white shadow-sm ring-1 ring-gray-900/5 rounded-xl">
        <div className="border-b border-gray-200 px-6 py-4">
          <h2 className="text-lg font-semibold text-gray-900">Tardiness Records</h2>
          <p className="mt-1 text-sm text-gray-500">
            View and resolve tardiness records. Resolution options: salary deduction, leave deduction, excused, or warning.
          </p>
        </div>

        <div className="px-6 py-4 border-b border-gray-100">
          <div className="flex items-center gap-4">
            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1">Resolution Type</label>
              <select
                value={resolutionFilter}
                onChange={(e) => setResolutionFilter(e.target.value)}
                className="rounded-md border border-gray-300 px-3 py-1.5 text-sm shadow-sm focus:border-brand-500 focus:ring-brand-500 focus:outline-none"
              >
                <option value="">All</option>
                {RESOLUTION_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            </div>
          </div>
        </div>

        <div className="px-6 py-6">
          {isLoading ? (
            <div className="flex items-center gap-3 text-sm text-gray-500">
              <svg className="h-5 w-5 animate-spin text-brand-600" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              Loading...
            </div>
          ) : records && records.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200">
                <thead>
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Employee</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Date</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Late By</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Resolution</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Deduction</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Notes</th>
                    {canEdit && (
                      <th className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-wider text-gray-500">Actions</th>
                    )}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {records.map((rec) => (
                    <tr key={rec.id} className="hover:bg-gray-50 transition-colors">
                      <td className="px-4 py-3 text-sm text-gray-900">{rec.employee_name || `#${rec.employee_id}`}</td>
                      <td className="px-4 py-3 text-sm text-gray-700">{rec.date}</td>
                      <td className="px-4 py-3 text-sm font-medium text-red-600">{formatMinutes(rec.tardiness_minutes)}</td>
                      <td className="px-4 py-3">
                        {rec.resolution_type ? (
                          <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${RESOLUTION_BADGE[rec.resolution_type] ?? 'bg-gray-100 text-gray-800'}`}>
                            {rec.resolution_type.replace('_', ' ')}
                          </span>
                        ) : (
                          <span className="text-xs text-gray-500 italic">Unresolved</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-600">
                        {rec.deduction_amount != null ? money(rec.deduction_amount) : ''}
                        {rec.amount_hidden ? 'From pay rate (hidden)' : ''}
                        {rec.leave_credits_deducted != null ? `${rec.leave_credits_deducted.toFixed(4)} day credits` : ''}
                        {rec.deduction_amount == null && rec.leave_credits_deducted == null && !rec.amount_hidden ? '--' : ''}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-500 max-w-[200px] truncate">{rec.notes || '--'}</td>
                      {canEdit && (
                        <td className="px-4 py-3 text-right">
                          <button
                            type="button"
                            onClick={() => setResolving(rec)}
                            className="inline-flex items-center rounded-md bg-brand-50 px-2.5 py-1 text-xs font-medium text-brand-700 hover:bg-brand-100 transition-colors"
                          >
                            {rec.resolution_type ? 'Re-resolve' : 'Resolve'}
                          </button>
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="text-center py-12">
              <svg className="mx-auto h-12 w-12 text-gray-300" fill="none" viewBox="0 0 24 24" strokeWidth={1} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <h3 className="mt-2 text-sm font-semibold text-gray-900">No tardiness records</h3>
              <p className="mt-1 text-sm text-gray-500">Tardiness records are created when late arrivals are detected in attendance.</p>
            </div>
          )}
        </div>
      </div>

      {resolving && (
        <ResolveDialog
          record={resolving}
          onClose={() => setResolving(null)}
          onDone={() => {
            setResolving(null)
            queryClient.invalidateQueries({ queryKey: ['tardiness-records'] })
            showToast('Tardiness resolved', 'success')
          }}
        />
      )}
    </div>
  )
}

/** Resolve one late arrival. For a salary deduction the amount starts at the
 *  employee's per-minute rate x minutes late (the same rate payroll uses) and
 *  can be changed; it used to have no amount at all, so it deducted nothing.
 *  People without salary access cannot see the figure; it is worked out when
 *  they save. */
function ResolveDialog({ record, onClose, onDone }: { record: TardinessRecord; onClose: () => void; onDone: () => void }) {
  const { showToast } = useToast()
  const { format: money, code } = useCurrency()
  const [type, setType] = useState<string>(record.resolution_type || 'warning')
  const [notes, setNotes] = useState(record.notes || '')
  const [amount, setAmount] = useState<string>('')

  const { data: suggestion, isLoading: suggesting } = useQuery<SuggestedDeduction>({
    queryKey: ['tardiness-suggestion', record.id],
    queryFn: () => api.getSuggestedTardinessDeduction(record.id),
    enabled: type === 'salary_deduction',
  })

  useEffect(() => {
    if (!suggestion || suggestion.amount == null) return
    let alive = true
    void Promise.resolve().then(() => {
      if (alive) setAmount((prev) => (prev === '' ? String(record.deduction_amount ?? suggestion.amount) : prev))
    })
    return () => {
      alive = false
    }
  }, [suggestion, record.deduction_amount])

  const amountNumber = amount.trim() === '' ? undefined : Number(amount)
  const amountInvalid = amountNumber !== undefined && (!Number.isFinite(amountNumber) || amountNumber < 0)
  const noSalary = type === 'salary_deduction' && suggestion && !suggestion.has_salary

  const save = useMutation({
    mutationFn: () =>
      api.resolveTardiness(record.id, {
        resolution_type: type,
        notes: notes || undefined,
        deduction_amount: type === 'salary_deduction' && suggestion && !suggestion.amount_hidden ? amountNumber : undefined,
      }),
    onSuccess: onDone,
    onError: (e: Error) => showToast(e.message, 'error'),
  })

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-labelledby="resolve-title"
        className="w-full max-w-md rounded-xl bg-white p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <h3 id="resolve-title" className="text-lg font-semibold text-gray-900">Resolve late arrival</h3>
        <p className="mt-1 text-sm text-gray-600">
          {record.employee_name || `Employee #${record.employee_id}`}, {record.date}: {record.tardiness_minutes} minutes late.
        </p>
        <div className="mt-4 space-y-3">
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-gray-700">Resolution</span>
            <select className="input" value={type} onChange={(e) => setType(e.target.value)}>
              {RESOLUTION_OPTIONS.map((opt) => <option key={opt.value} value={opt.value}>{opt.label}</option>)}
            </select>
          </label>
          {type === 'salary_deduction' && (
            <div className="rounded-lg bg-gray-50 p-3 text-sm">
              {suggesting ? (
                <p className="text-gray-500">Working out the amount…</p>
              ) : noSalary ? (
                <p className="text-red-700">This employee has no salary on that date, so there is nothing to deduct from. Assign a salary under Finances first.</p>
              ) : suggestion?.amount_hidden ? (
                <p className="text-gray-700">The amount is the employee&apos;s pay rate x {record.tardiness_minutes} minutes. It is worked out when you save; only people with salary access can see it.</p>
              ) : (
                <label className="block">
                  <span className="mb-1 block font-medium text-gray-700">Amount to deduct ({code})</span>
                  <input type="number" min="0" step="0.01" className="input" value={amount}
                    onChange={(e) => setAmount(e.target.value)} aria-invalid={amountInvalid} />
                  <span className="mt-1 block text-xs text-gray-500">
                    Suggested {suggestion?.amount != null ? money(suggestion.amount) : ''}: the employee&apos;s per-minute rate x {record.tardiness_minutes} minutes. Payroll deducts this amount.
                  </span>
                  {amountInvalid && <span className="mt-1 block text-xs text-red-700">Enter an amount of zero or more.</span>}
                </label>
              )}
            </div>
          )}
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-gray-700">Notes</span>
            <input className="input" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Optional" />
          </label>
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50">Cancel</button>
          <button type="button" onClick={() => save.mutate()}
            disabled={save.isPending || amountInvalid || !!noSalary || (type === 'salary_deduction' && suggesting)}
            className="rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-50">
            {save.isPending ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  )
}
