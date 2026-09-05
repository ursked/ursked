'use client'

import { useMemo, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { CompensationItem, CompensationKind, CurrentSalaryRow } from '@/types'
import { useToast } from '@/components/ui/Toast'
import { useCurrency } from '@/lib/currency'

const KINDS: { value: CompensationKind; label: string }[] = [
  { value: 'bonus', label: 'Bonus' },
  { value: 'incentive', label: 'Incentive' },
  { value: 'allowance', label: 'Allowance' },
  { value: 'salary_adjustment', label: 'Salary adjustment' },
]

function today(): string {
  return new Date().toISOString().slice(0, 10)
}

export default function CompensationTab() {
  const queryClient = useQueryClient()
  const { showToast } = useToast()
  const { format: formatCurrency } = useCurrency()
  const [showForm, setShowForm] = useState(false)
  const [kindFilter, setKindFilter] = useState<string>('')
  const [statusFilter, setStatusFilter] = useState<string>('')

  const { data: items, isLoading } = useQuery<CompensationItem[]>({
    queryKey: ['compensation-items', kindFilter, statusFilter],
    queryFn: () => api.getCompensationItems({ kind: kindFilter || undefined, status: statusFilter || undefined }),
  })
  const { data: employees } = useQuery<CurrentSalaryRow[]>({
    queryKey: ['current-salaries'],
    queryFn: () => api.getCurrentSalaries(),
  })

  const nameById = useMemo(() => {
    const m = new Map<number, string>()
    ;(employees ?? []).forEach((e) => m.set(e.employee_id, e.employee_name))
    return m
  }, [employees])

  const voidMut = useMutation({
    mutationFn: (id: number) => api.voidCompensationItem(id, 'Voided by admin'),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['compensation-items'] })
      showToast('Item voided', 'success')
    },
    onError: (e: Error) => showToast(e.message, 'error'),
  })

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-lg font-semibold text-gray-900">Bonuses, Incentives &amp; Allowances</h2>
          <p className="text-sm text-gray-500">
            Add variable pay. Each line is scheduled to a payout date based on your payout
            schedule, then included automatically when that payroll run is computed.
          </p>
        </div>
        <button
          onClick={() => setShowForm(true)}
          className="rounded-md bg-purple-600 px-4 py-2 text-sm font-semibold text-white hover:bg-purple-700"
        >
          Add compensation
        </button>
      </div>

      <div className="flex flex-wrap gap-2">
        <select className="input max-w-[10rem]" value={kindFilter} onChange={(e) => setKindFilter(e.target.value)}>
          <option value="">All kinds</option>
          {KINDS.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
          <option value="leave_cash">Leave cash</option>
        </select>
        <select className="input max-w-[10rem]" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="">All statuses</option>
          <option value="scheduled">Scheduled</option>
          <option value="paid">Paid</option>
          <option value="void">Void</option>
        </select>
      </div>

      {isLoading ? (
        <p className="text-sm text-gray-500">Loading…</p>
      ) : (items ?? []).length === 0 ? (
        <div className="rounded-lg border border-dashed border-gray-300 p-8 text-center text-sm text-gray-500">
          No compensation lines yet. Add a bonus, incentive or allowance.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="min-w-full divide-y divide-gray-200 text-sm">
            <thead className="bg-gray-50 text-left text-xs font-medium uppercase text-gray-500">
              <tr>
                <th className="px-4 py-2">Employee</th>
                <th className="px-4 py-2">Kind</th>
                <th className="px-4 py-2 text-right">Amount</th>
                <th className="px-4 py-2">Earned</th>
                <th className="px-4 py-2">Payout</th>
                <th className="px-4 py-2">Recurs</th>
                <th className="px-4 py-2">Status</th>
                <th className="px-4 py-2">Reason</th>
                <th className="px-4 py-2 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {(items ?? []).map((it) => (
                <tr key={it.id}>
                  <td className="px-4 py-2 text-gray-900">{nameById.get(it.employee_id) ?? `#${it.employee_id}`}</td>
                  <td className="px-4 py-2 capitalize text-gray-600">{it.kind.replace('_', ' ')}</td>
                  <td className="px-4 py-2 text-right font-medium text-gray-900">{formatCurrency(it.amount)}</td>
                  <td className="px-4 py-2 text-gray-500">{it.earned_on}</td>
                  <td className="px-4 py-2 font-medium text-purple-700">{it.payout_date}</td>
                  <td className="px-4 py-2 text-gray-500">{it.recurrence === 'once' ? '—' : it.recurrence}</td>
                  <td className="px-4 py-2">
                    <StatusBadge status={it.status} />
                  </td>
                  <td className="px-4 py-2 max-w-[16rem] truncate text-gray-500" title={it.reason}>{it.reason}</td>
                  <td className="px-4 py-2 text-right">
                    {it.status === 'scheduled' && (
                      <button
                        onClick={() => voidMut.mutate(it.id)}
                        disabled={voidMut.isPending}
                        className="text-xs font-medium text-red-600 hover:underline disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        {voidMut.isPending ? 'Voiding…' : 'Void'}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showForm && (
        <AddModal
          employees={employees ?? []}
          onClose={() => setShowForm(false)}
          onDone={() => {
            setShowForm(false)
            queryClient.invalidateQueries({ queryKey: ['compensation-items'] })
            showToast('Compensation added', 'success')
          }}
        />
      )}
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    scheduled: 'bg-blue-100 text-blue-800',
    paid: 'bg-green-100 text-green-800',
    void: 'bg-gray-200 text-gray-600',
    pending: 'bg-amber-100 text-amber-800',
  }
  return <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${map[status] ?? 'bg-gray-100 text-gray-600'}`}>{status}</span>
}

function AddModal({ employees, onClose, onDone }: {
  employees: CurrentSalaryRow[]; onClose: () => void; onDone: () => void
}) {
  const { showToast } = useToast()
  const { code: currencyCode } = useCurrency()
  const [employeeId, setEmployeeId] = useState<number | ''>('')
  const [applyAll, setApplyAll] = useState(false)
  const [kind, setKind] = useState<CompensationKind>('bonus')
  const [amount, setAmount] = useState('')
  const [earnedOn, setEarnedOn] = useState(today())
  const [recurrence, setRecurrence] = useState<'once' | 'monthly' | 'per_cutoff'>('once')
  const [reason, setReason] = useState('')
  const [resolved, setResolved] = useState<string | null>(null)

  const previewMut = useMutation({
    mutationFn: () => api.previewPayoutDate(earnedOn),
    onSuccess: (r) => setResolved(r.payout_date),
  })

  const saveMut = useMutation({
    mutationFn: async () => {
      const base = { kind, amount: Number(amount), earned_on: earnedOn, recurrence, reason }
      if (applyAll) {
        await api.bulkCreateCompensation({ ...base, employee_ids: employees.map((e) => e.employee_id), employee_id: 0 })
      } else {
        await api.createCompensationItem({ ...base, employee_id: Number(employeeId) })
      }
    },
    onSuccess: onDone,
    onError: (e: Error) => showToast(e.message, 'error'),
  })

  const canSave = amount && reason && (applyAll || employeeId)

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div className="w-full max-w-md rounded-xl bg-white p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <h3 className="mb-4 text-lg font-semibold text-gray-900">Add compensation</h3>
        <div className="space-y-3">
          <label className="flex items-center gap-2 text-sm text-gray-700">
            <input type="checkbox" checked={applyAll} onChange={(e) => setApplyAll(e.target.checked)} />
            Apply to all employees
          </label>
          {!applyAll && (
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-gray-700">Employee</span>
              <select className="input" value={employeeId} onChange={(e) => setEmployeeId(e.target.value ? Number(e.target.value) : '')}>
                <option value="">Select employee</option>
                {employees.map((e) => <option key={e.employee_id} value={e.employee_id}>{e.employee_name}</option>)}
              </select>
            </label>
          )}
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-gray-700">Kind</span>
            <select className="input" value={kind} onChange={(e) => setKind(e.target.value as CompensationKind)}>
              {KINDS.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
            </select>
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-gray-700">Amount ({currencyCode})</span>
            <input type="number" className="input" value={amount} onChange={(e) => setAmount(e.target.value)} />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-gray-700">Earned on</span>
            <div className="flex gap-2">
              <input type="date" className="input" value={earnedOn} onChange={(e) => { setEarnedOn(e.target.value); setResolved(null) }} />
              <button onClick={() => previewMut.mutate()} className="whitespace-nowrap rounded-md border border-gray-300 px-3 text-sm font-medium text-gray-700 hover:bg-gray-50">
                Preview payout
              </button>
            </div>
            {resolved && <span className="mt-1 block text-xs font-medium text-purple-700">→ paid on {resolved}</span>}
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-gray-700">Recurrence</span>
            <select className="input" value={recurrence} onChange={(e) => setRecurrence(e.target.value as typeof recurrence)}>
              <option value="once">One-time</option>
              <option value="monthly">Every month</option>
              <option value="per_cutoff">Every cutoff</option>
            </select>
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-gray-700">Reason</span>
            <input className="input" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Q4 performance bonus" />
          </label>
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <button onClick={onClose} className="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50">Cancel</button>
          <button onClick={() => saveMut.mutate()} disabled={!canSave || saveMut.isPending} className="rounded-md bg-purple-600 px-4 py-2 text-sm font-semibold text-white hover:bg-purple-700 disabled:opacity-50">Add</button>
        </div>
      </div>
    </div>
  )
}
