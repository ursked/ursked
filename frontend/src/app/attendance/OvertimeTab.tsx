'use client'

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { OvertimeLog } from '@/types'
import { useToast } from '@/components/ui/Toast'
import { usePermissions } from '@/contexts/PermissionsContext'

const STATUS_BADGE: Record<string, string> = {
  pending: 'bg-yellow-100 text-yellow-800',
  approved: 'bg-green-100 text-green-800',
  converted: 'bg-blue-100 text-blue-800',
  rejected: 'bg-red-100 text-red-800',
}

export default function OvertimeTab() {
  const queryClient = useQueryClient()
  const { showToast } = useToast()
  const { hasPermission } = usePermissions()
  const canEdit = hasPermission('schedules', 'edit')
  const [statusFilter, setStatusFilter] = useState('')

  const { data: logs, isLoading } = useQuery<OvertimeLog[]>({
    queryKey: ['overtime-logs', statusFilter],
    queryFn: () => api.listOvertimeLogs({ status: statusFilter || undefined }),
  })

  const approveMutation = useMutation({
    mutationFn: (logId: number) => api.approveOvertime(logId),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['overtime-logs'] }); showToast('Overtime approved', 'success') },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  const rejectMutation = useMutation({
    mutationFn: (logId: number) => api.rejectOvertime(logId),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['overtime-logs'] }); showToast('Overtime rejected', 'success') },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  const convertMutation = useMutation({
    mutationFn: (logId: number) => api.convertOvertimeToLeave(logId),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['overtime-logs'] }); showToast('Overtime converted to leave credits', 'success') },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  const formatMinutes = (m: number) => {
    const h = Math.floor(m / 60)
    const min = m % 60
    return h > 0 ? `${h}h ${min}m` : `${min}m`
  }

  const isMutating = approveMutation.isPending || rejectMutation.isPending || convertMutation.isPending

  return (
    <div className="space-y-6">
      <div className="bg-white shadow-sm ring-1 ring-gray-900/5 rounded-xl">
        <div className="border-b border-gray-200 px-6 py-4">
          <h2 className="text-lg font-semibold text-gray-900">Overtime Logs</h2>
          <p className="mt-1 text-sm text-gray-500">
            Review, approve, reject, or convert overtime to leave credits.
          </p>
        </div>

        <div className="px-6 py-4 border-b border-gray-100">
          <div className="flex items-center gap-4">
            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1">Status</label>
              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                className="rounded-md border border-gray-300 px-3 py-1.5 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none"
              >
                <option value="">All</option>
                <option value="pending">Pending</option>
                <option value="approved">Approved</option>
                <option value="converted">Converted</option>
                <option value="rejected">Rejected</option>
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
          ) : logs && logs.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200">
                <thead>
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Employee</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Date</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Duration</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Category</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Multiplier</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Credits</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Status</th>
                    {canEdit && (
                      <th className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-wider text-gray-500">Actions</th>
                    )}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {logs.map((log) => (
                    <tr key={log.id} className="hover:bg-gray-50 transition-colors">
                      <td className="px-4 py-3 text-sm text-gray-900">{log.employee_name || `#${log.employee_id}`}</td>
                      <td className="px-4 py-3 text-sm text-gray-700">{log.date}</td>
                      <td className="px-4 py-3 text-sm font-medium text-gray-700">{formatMinutes(log.overtime_minutes)}</td>
                      <td className="px-4 py-3 text-sm text-gray-600">{log.overtime_category_name || '--'}</td>
                      <td className="px-4 py-3 text-sm text-gray-600">{log.pay_multiplier ? `${log.pay_multiplier}x` : '--'}</td>
                      <td className="px-4 py-3 text-sm text-gray-600">
                        {log.leave_credits_earned != null ? `${log.leave_credits_earned.toFixed(4)} days` : '--'}
                      </td>
                      <td className="px-4 py-3">
                        <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${STATUS_BADGE[log.status] ?? 'bg-gray-100 text-gray-800'}`}>
                          {log.status}
                        </span>
                      </td>
                      {canEdit && (
                        <td className="px-4 py-3 text-right">
                          <div className="flex items-center justify-end gap-1.5">
                            {log.status === 'pending' && (
                              <>
                                <button
                                  type="button"
                                  disabled={isMutating}
                                  onClick={() => approveMutation.mutate(log.id)}
                                  className="inline-flex items-center rounded-md bg-green-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-green-700 disabled:opacity-50 transition-colors"
                                >
                                  Approve
                                </button>
                                <button
                                  type="button"
                                  disabled={isMutating}
                                  onClick={() => rejectMutation.mutate(log.id)}
                                  className="inline-flex items-center rounded-md bg-red-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-red-700 disabled:opacity-50 transition-colors"
                                >
                                  Reject
                                </button>
                              </>
                            )}
                            {log.status === 'approved' && (
                              <button
                                type="button"
                                disabled={isMutating}
                                onClick={() => convertMutation.mutate(log.id)}
                                className="inline-flex items-center rounded-md bg-blue-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50 transition-colors"
                              >
                                Convert to Leave
                              </button>
                            )}
                          </div>
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
              <h3 className="mt-2 text-sm font-semibold text-gray-900">No overtime logs</h3>
              <p className="mt-1 text-sm text-gray-500">Overtime logs are automatically created when attendance with extra hours is recorded.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
