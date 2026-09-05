'use client'

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { TeamStats, LeaveApplication, PaginatedResponse } from '@/types'

const STATUS_COLORS: Record<string, string> = {
  pending: 'bg-yellow-100 text-yellow-800',
  approved: 'bg-green-100 text-green-800',
  rejected: 'bg-red-100 text-red-800',
  cancelled: 'bg-gray-100 text-gray-600',
}

export default function TeamOverviewTab() {
  const [page, setPage] = useState(1)
  const [statusFilter, setStatusFilter] = useState<string>('all')

  // ── Queries ────────────────────────────────────────────────────────
  const { data: stats, isLoading: statsLoading } = useQuery<TeamStats>({
    queryKey: ['team-stats'],
    queryFn: () => api.getTeamStats(),
  })

  const params: Record<string, string> = { page: String(page), per_page: '10', scope: 'team' }
  if (statusFilter !== 'all') params.status = statusFilter

  const { data: teamApps, isLoading: appsLoading } = useQuery<PaginatedResponse<LeaveApplication>>({
    queryKey: ['team-leave-applications', page, statusFilter],
    queryFn: () => api.getLeaveApplications(params) as Promise<PaginatedResponse<LeaveApplication>>,
  })

  // ── Chart helpers ──────────────────────────────────────────────────
  const maxByType = stats?.by_type.reduce((m, t) => Math.max(m, t.days), 0) ?? 1
  const maxByMonth = stats?.by_month.reduce((m, m2) => Math.max(m, m2.days), 0) ?? 1

  const approvalRate =
    stats && stats.summary.total > 0
      ? Math.round((stats.summary.approved / stats.summary.total) * 100)
      : 0

  return (
    <div className="space-y-6">
      {/* ── Summary Cards ───────────────────────────────────────────── */}
      {statsLoading ? (
        <div className="flex items-center gap-3 text-sm text-gray-500">
          <svg className="h-5 w-5 animate-spin text-purple-600" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          Loading stats...
        </div>
      ) : stats ? (
        <>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <div className="bg-white border border-gray-200 rounded-lg p-4">
              <p className="text-sm text-gray-500">Total Applications</p>
              <p className="mt-1 text-2xl font-bold text-gray-900">{stats.summary.total}</p>
            </div>
            <div className="bg-white border border-gray-200 rounded-lg p-4">
              <p className="text-sm text-gray-500">Pending</p>
              <p className="mt-1 text-2xl font-bold text-yellow-600">{stats.summary.pending}</p>
            </div>
            <div className="bg-white border border-gray-200 rounded-lg p-4">
              <p className="text-sm text-gray-500">Approved</p>
              <p className="mt-1 text-2xl font-bold text-green-600">{stats.summary.approved}</p>
            </div>
            <div className="bg-white border border-gray-200 rounded-lg p-4">
              <p className="text-sm text-gray-500">Approval Rate</p>
              <p className="mt-1 text-2xl font-bold text-purple-600">{approvalRate}%</p>
            </div>
          </div>

          {/* ── Charts ──────────────────────────────────────────────── */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* By Type */}
            <div className="bg-white border border-gray-200 rounded-xl shadow-sm p-6">
              <h4 className="text-sm font-semibold text-gray-900 mb-4">Leave Usage by Type</h4>
              {stats.by_type.length > 0 ? (
                <div className="space-y-3">
                  {stats.by_type.map((t) => (
                    <div key={t.leave_type}>
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-sm text-gray-700">{t.leave_type_name || t.leave_type.replace(/_/g, ' ')}</span>
                        <span className="text-sm font-medium text-gray-900">{t.days} days ({t.count})</span>
                      </div>
                      <div className="h-2.5 bg-gray-100 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-purple-500 rounded-full transition-all"
                          style={{ width: `${maxByType > 0 ? (t.days / maxByType) * 100 : 0}%` }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-gray-500">No data available</p>
              )}
            </div>

            {/* By Month */}
            <div className="bg-white border border-gray-200 rounded-xl shadow-sm p-6">
              <h4 className="text-sm font-semibold text-gray-900 mb-4">Monthly Trend</h4>
              {stats.by_month.length > 0 ? (
                <div className="space-y-3">
                  {stats.by_month.map((m) => (
                    <div key={m.month}>
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-sm text-gray-700">{m.month}</span>
                        <span className="text-sm font-medium text-gray-900">{m.days} days ({m.count})</span>
                      </div>
                      <div className="h-2.5 bg-gray-100 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-indigo-500 rounded-full transition-all"
                          style={{ width: `${maxByMonth > 0 ? (m.days / maxByMonth) * 100 : 0}%` }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-gray-500">No data available</p>
              )}
            </div>
          </div>
        </>
      ) : null}

      {/* ── Team Applications Table ─────────────────────────────────── */}
      <div className="bg-white border border-gray-200 rounded-xl shadow-sm">
        <div className="border-b border-gray-200 px-6 py-4">
          <h3 className="text-lg font-semibold text-gray-900">Team Leave Applications</h3>
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
          ) : teamApps && teamApps.items.length > 0 ? (
            <>
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-gray-200">
                  <thead>
                    <tr>
                      <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Employee</th>
                      <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Type</th>
                      <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Dates</th>
                      <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Days</th>
                      <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Status</th>
                      <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Approval</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {teamApps.items.map((app) => (
                      <tr key={app.id} className="hover:bg-gray-50 transition-colors">
                        <td className="px-4 py-3 text-sm font-medium text-gray-900">{app.employee_name}</td>
                        <td className="px-4 py-3 text-sm text-gray-700">{app.leave_type.replace(/_/g, ' ')}</td>
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
                            <span className="text-xs text-gray-500">--</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {teamApps.total_pages > 1 && (
                <div className="flex items-center justify-between mt-4 pt-4 border-t border-gray-100">
                  <p className="text-sm text-gray-500">
                    Page {teamApps.page} of {teamApps.total_pages} ({teamApps.total} total)
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
                      disabled={page >= teamApps.total_pages}
                      className="rounded-md px-3 py-1 text-sm font-medium text-gray-700 ring-1 ring-inset ring-gray-300 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                    >
                      Next
                    </button>
                  </div>
                </div>
              )}
            </>
          ) : (
            <p className="text-sm text-gray-500 py-8 text-center">No team leave applications found.</p>
          )}
        </div>
      </div>
    </div>
  )
}
