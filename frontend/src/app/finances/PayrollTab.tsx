'use client'

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { PayrollPeriod, PayrollItem } from '@/types'
import { useToast } from '@/components/ui/Toast'
import { useCurrency } from '@/lib/currency'

interface PeriodFormData {
  name: string
  period_type: string
  start_date: string
  end_date: string
  payout_date: string
  notes: string
}

const EMPTY_PERIOD: PeriodFormData = {
  name: '',
  period_type: 'monthly',
  start_date: '',
  end_date: '',
  payout_date: '',
  notes: '',
}

const STATUS_COLORS: Record<string, string> = {
  draft: 'bg-gray-100 text-gray-700',
  computing: 'bg-yellow-100 text-yellow-700',
  computed: 'bg-blue-100 text-blue-700',
  approved: 'bg-green-100 text-green-700',
  finalized: 'bg-purple-100 text-purple-700',
}

export default function PayrollTab() {
  const queryClient = useQueryClient()
  const { showToast } = useToast()

  const [showForm, setShowForm] = useState(false)
  const [formData, setFormData] = useState<PeriodFormData>(EMPTY_PERIOD)
  const [selectedPeriodId, setSelectedPeriodId] = useState<number | null>(null)

  const { data: periods, isLoading } = useQuery<PayrollPeriod[]>({
    queryKey: ['payroll-periods'],
    queryFn: () => api.getPayrollPeriods(),
  })

  const { data: items, isLoading: itemsLoading } = useQuery<PayrollItem[]>({
    queryKey: ['payroll-items', selectedPeriodId],
    queryFn: () => api.getPayrollItems(selectedPeriodId!),
    enabled: !!selectedPeriodId,
  })

  const createMutation = useMutation({
    mutationFn: (data: PeriodFormData) =>
      api.createPayrollPeriod({
        name: data.name,
        period_type: data.period_type,
        start_date: data.start_date,
        end_date: data.end_date,
        payout_date: data.payout_date || undefined,
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
      queryClient.invalidateQueries({ queryKey: ['payroll-items', selectedPeriodId] })
      showToast('Payroll computed successfully', 'success')
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

  const selectedPeriod = periods?.find((p) => p.id === selectedPeriodId)

  const { format: formatCurrency } = useCurrency()

  function handleCreateSubmit(e: React.FormEvent) {
    e.preventDefault()
    createMutation.mutate(formData)
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-gray-900">Payroll Periods</h2>
        {!showForm && (
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
              <label className="block text-sm font-medium text-gray-700">Period Name</label>
              <input
                type="text"
                required
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-purple-500 focus:ring-purple-500"
                placeholder="e.g. January 2026"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">Type</label>
              <select
                value={formData.period_type}
                onChange={(e) => setFormData({ ...formData, period_type: e.target.value })}
                className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-purple-500 focus:ring-purple-500"
              >
                <option value="monthly">Monthly</option>
                <option value="semi_monthly">Semi-Monthly</option>
              </select>
            </div>
            <div />
            <div>
              <label className="block text-sm font-medium text-gray-700">Start Date</label>
              <input
                type="date"
                required
                value={formData.start_date}
                onChange={(e) => setFormData({ ...formData, start_date: e.target.value })}
                className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-purple-500 focus:ring-purple-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">End Date</label>
              <input
                type="date"
                required
                value={formData.end_date}
                onChange={(e) => setFormData({ ...formData, end_date: e.target.value })}
                className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-purple-500 focus:ring-purple-500"
              />
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700">Payout Date (optional)</label>
            <input
              type="date"
              value={formData.payout_date}
              onChange={(e) => setFormData({ ...formData, payout_date: e.target.value })}
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-purple-500 focus:ring-purple-500"
            />
            <p className="mt-1 text-xs text-gray-500">
              When set, this run also pays every bonus, incentive, allowance and leave-cash
              line scheduled for this payout date — even if earned in an earlier period.
            </p>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700">Notes</label>
            <input
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
      ) : !periods?.length ? (
        <div className="text-center py-8 text-gray-500">No payroll periods yet. Create one to get started.</div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Period</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Type</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Date Range</th>
                <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase">Status</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Employees</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Total Gross</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Total Net</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 bg-white">
              {periods.map((p) => (
                <tr
                  key={p.id}
                  onClick={() => setSelectedPeriodId(p.id === selectedPeriodId ? null : p.id)}
                  className={`cursor-pointer hover:bg-gray-50 ${selectedPeriodId === p.id ? 'bg-purple-50' : ''}`}
                >
                  <td className="px-4 py-3 text-sm font-medium text-gray-900">{p.name}</td>
                  <td className="px-4 py-3 text-sm text-gray-500 capitalize">{p.period_type.replace('_', '-')}</td>
                  <td className="px-4 py-3 text-sm text-gray-500">{p.start_date} — {p.end_date}</td>
                  <td className="px-4 py-3 text-center">
                    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium capitalize ${STATUS_COLORS[p.status] || 'bg-gray-100 text-gray-700'}`}>
                      {p.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-500 text-right">{p.item_count || 0}</td>
                  <td className="px-4 py-3 text-sm text-gray-900 text-right">{formatCurrency(p.total_gross || 0)}</td>
                  <td className="px-4 py-3 text-sm text-gray-900 text-right">{formatCurrency(p.total_net || 0)}</td>
                  <td className="px-4 py-3 text-right space-x-1" onClick={(e) => e.stopPropagation()}>
                    {(p.status === 'draft' || p.status === 'computed') && (
                      <button
                        onClick={() => computeMutation.mutate(p.id)}
                        disabled={computeMutation.isPending}
                        className="text-sm text-blue-600 hover:text-blue-800 disabled:opacity-50"
                      >
                        {computeMutation.isPending ? 'Computing...' : p.status === 'computed' ? 'Recompute' : 'Compute'}
                      </button>
                    )}
                    {p.status === 'computed' && (
                      <button
                        onClick={() => approveMutation.mutate(p.id)}
                        disabled={approveMutation.isPending}
                        className="text-sm text-green-600 hover:text-green-800 disabled:opacity-50"
                      >
                        Approve
                      </button>
                    )}
                    {p.status === 'approved' && (
                      <button
                        onClick={() => finalizeMutation.mutate(p.id)}
                        disabled={finalizeMutation.isPending}
                        className="text-sm text-purple-600 hover:text-purple-800 disabled:opacity-50"
                      >
                        Finalize
                      </button>
                    )}
                  </td>
                </tr>
              ))}
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
          ) : !items?.length ? (
            <div className="text-center py-4 text-gray-500">
              No payroll items yet. Click &quot;Compute&quot; to generate payroll for this period.
            </div>
          ) : (
            <div className="overflow-x-auto rounded-lg border border-gray-200">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Employee</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Grade</th>
                    <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Base Pay</th>
                    <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">OT Pay</th>
                    <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Gross</th>
                    <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Deductions</th>
                    <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Net Pay</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200 bg-white">
                  {items.map((item) => (
                    <tr key={item.id}>
                      <td className="px-4 py-3 text-sm text-gray-900">{item.employee_name || `Employee #${item.employee_id}`}</td>
                      <td className="px-4 py-3 text-sm text-gray-500">{item.grade_name || '—'}</td>
                      <td className="px-4 py-3 text-sm text-gray-900 text-right">{formatCurrency(item.base_pay)}</td>
                      <td className="px-4 py-3 text-sm text-gray-900 text-right">{item.overtime_pay > 0 ? formatCurrency(item.overtime_pay) : '—'}</td>
                      <td className="px-4 py-3 text-sm font-medium text-gray-900 text-right">{formatCurrency(item.gross_pay)}</td>
                      <td className="px-4 py-3 text-sm text-red-600 text-right">{formatCurrency(item.total_deductions)}</td>
                      <td className="px-4 py-3 text-sm font-semibold text-green-700 text-right">{formatCurrency(item.net_pay)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
