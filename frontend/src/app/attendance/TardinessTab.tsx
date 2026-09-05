'use client'

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { TardinessRecord } from '@/types'
import { useToast } from '@/components/ui/Toast'
import { usePermissions } from '@/contexts/PermissionsContext'

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

  const [resolutionFilter, setResolutionFilter] = useState('')
  const [resolvingId, setResolvingId] = useState<number | null>(null)
  const [resolveType, setResolveType] = useState('warning')
  const [resolveNotes, setResolveNotes] = useState('')

  const { data: records, isLoading } = useQuery<TardinessRecord[]>({
    queryKey: ['tardiness-records', resolutionFilter],
    queryFn: () => api.listTardinessRecords({ resolution_type: resolutionFilter || undefined }),
  })

  const resolveMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: { resolution_type: string; notes?: string } }) =>
      api.resolveTardiness(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tardiness-records'] })
      setResolvingId(null)
      setResolveNotes('')
      showToast('Tardiness resolved', 'success')
    },
    onError: (err: Error) => showToast(err.message, 'error'),
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
                className="rounded-md border border-gray-300 px-3 py-1.5 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none"
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
              <svg className="h-5 w-5 animate-spin text-purple-600" fill="none" viewBox="0 0 24 24">
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
                        {rec.deduction_amount != null ? `$${rec.deduction_amount.toFixed(2)}` : ''}
                        {rec.leave_credits_deducted != null ? `${rec.leave_credits_deducted.toFixed(4)} day credits` : ''}
                        {rec.deduction_amount == null && rec.leave_credits_deducted == null ? '--' : ''}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-500 max-w-[200px] truncate">{rec.notes || '--'}</td>
                      {canEdit && (
                        <td className="px-4 py-3 text-right">
                          {resolvingId === rec.id ? (
                            <div className="flex items-center justify-end gap-2">
                              <select
                                value={resolveType}
                                onChange={(e) => setResolveType(e.target.value)}
                                className="rounded-md border border-gray-300 px-2 py-1 text-xs"
                              >
                                {RESOLUTION_OPTIONS.map((opt) => (
                                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                                ))}
                              </select>
                              <input
                                type="text"
                                value={resolveNotes}
                                onChange={(e) => setResolveNotes(e.target.value)}
                                placeholder="Notes..."
                                className="rounded-md border border-gray-300 px-2 py-1 text-xs w-24"
                              />
                              <button
                                type="button"
                                disabled={resolveMutation.isPending}
                                onClick={() =>
                                  resolveMutation.mutate({
                                    id: rec.id,
                                    data: {
                                      resolution_type: resolveType,
                                      notes: resolveNotes || undefined,
                                    },
                                  })
                                }
                                className="inline-flex items-center rounded-md bg-purple-600 px-2 py-1 text-xs font-medium text-white hover:bg-purple-700 disabled:opacity-50 transition-colors"
                              >
                                Save
                              </button>
                              <button
                                type="button"
                                onClick={() => setResolvingId(null)}
                                className="inline-flex items-center rounded-md bg-gray-100 px-2 py-1 text-xs font-medium text-gray-600 hover:bg-gray-200 transition-colors"
                              >
                                Cancel
                              </button>
                            </div>
                          ) : (
                            <button
                              type="button"
                              onClick={() => { setResolvingId(rec.id); setResolveType(rec.resolution_type || 'warning') }}
                              className="inline-flex items-center rounded-md bg-purple-50 px-2.5 py-1 text-xs font-medium text-purple-700 hover:bg-purple-100 transition-colors"
                            >
                              {rec.resolution_type ? 'Re-resolve' : 'Resolve'}
                            </button>
                          )}
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
    </div>
  )
}
