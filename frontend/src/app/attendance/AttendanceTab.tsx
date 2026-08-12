'use client'

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { AttendanceRecord } from '@/types'
import { useToast } from '@/components/ui/Toast'
import { usePermissions } from '@/contexts/PermissionsContext'
import RecordAttendanceModal from './RecordAttendanceModal'

const STATUS_BADGE: Record<string, string> = {
  present: 'bg-green-100 text-green-800',
  late: 'bg-yellow-100 text-yellow-800',
  absent: 'bg-red-100 text-red-800',
  half_day: 'bg-blue-100 text-blue-800',
  excused: 'bg-gray-100 text-gray-800',
}

export default function AttendanceTab() {
  const queryClient = useQueryClient()
  const { showToast } = useToast()
  const { hasPermission } = usePermissions()
  const canEdit = hasPermission('schedules', 'edit')

  const [showModal, setShowModal] = useState(false)
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')

  const { data: records, isLoading } = useQuery<AttendanceRecord[]>({
    queryKey: ['attendance-records', startDate, endDate],
    queryFn: () =>
      api.listAttendance({
        start_date: startDate || undefined,
        end_date: endDate || undefined,
        limit: 100,
      }),
  })

  const createMutation = useMutation({
    mutationFn: (data: Parameters<typeof api.recordAttendance>[0]) => api.recordAttendance(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['attendance-records'] })
      setShowModal(false)
      showToast('Attendance recorded', 'success')
    },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  const formatTime = (t?: string) => (t ? t.slice(0, 5) : '--')
  const formatMinutes = (m: number) => {
    if (m === 0) return '--'
    const h = Math.floor(m / 60)
    const min = m % 60
    return h > 0 ? `${h}h ${min}m` : `${min}m`
  }

  return (
    <div className="space-y-6">
      <div className="bg-white shadow-sm ring-1 ring-gray-900/5 rounded-xl">
        <div className="border-b border-gray-200 px-6 py-4 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Attendance Records</h2>
            <p className="mt-1 text-sm text-gray-500">View and record employee attendance.</p>
          </div>
          {canEdit && (
            <button
              type="button"
              onClick={() => setShowModal(true)}
              className="inline-flex items-center gap-1.5 rounded-md bg-purple-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-purple-700 transition-colors"
            >
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
              </svg>
              Record Attendance
            </button>
          )}
        </div>

        <div className="px-6 py-4 border-b border-gray-100">
          <div className="flex items-center gap-4">
            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1">Start Date</label>
              <input
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
                className="rounded-md border border-gray-300 px-3 py-1.5 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1">End Date</label>
              <input
                type="date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
                className="rounded-md border border-gray-300 px-3 py-1.5 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none"
              />
            </div>
            {(startDate || endDate) && (
              <button
                type="button"
                onClick={() => { setStartDate(''); setEndDate('') }}
                className="mt-5 text-xs text-gray-500 hover:text-gray-700"
              >
                Clear
              </button>
            )}
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
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Scheduled</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Actual</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Hours</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Late</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">OT</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {records.map((rec) => (
                    <tr key={rec.id} className="hover:bg-gray-50 transition-colors">
                      <td className="px-4 py-3 text-sm text-gray-900">{rec.employee_name || `#${rec.employee_id}`}</td>
                      <td className="px-4 py-3 text-sm text-gray-700">{rec.date}</td>
                      <td className="px-4 py-3 text-sm text-gray-600">
                        {formatTime(rec.scheduled_start_time)} - {formatTime(rec.scheduled_end_time)}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-600">
                        {formatTime(rec.actual_start_time)} - {formatTime(rec.actual_end_time)}
                      </td>
                      <td className="px-4 py-3 text-sm font-medium text-gray-700">
                        {rec.hours_worked != null ? `${rec.hours_worked.toFixed(1)}h` : '--'}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-600">{formatMinutes(rec.tardiness_minutes)}</td>
                      <td className="px-4 py-3 text-sm text-gray-600">{formatMinutes(rec.overtime_minutes)}</td>
                      <td className="px-4 py-3">
                        <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${STATUS_BADGE[rec.status] ?? 'bg-gray-100 text-gray-800'}`}>
                          {rec.status.replace('_', ' ')}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="text-center py-12">
              <svg className="mx-auto h-12 w-12 text-gray-300" fill="none" viewBox="0 0 24 24" strokeWidth={1} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 012.25-2.25h13.5A2.25 2.25 0 0121 7.5v11.25m-18 0A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75m-18 0v-7.5A2.25 2.25 0 015.25 9h13.5A2.25 2.25 0 0121 11.25v7.5" />
              </svg>
              <h3 className="mt-2 text-sm font-semibold text-gray-900">No attendance records</h3>
              <p className="mt-1 text-sm text-gray-500">Record attendance entries using the button above.</p>
            </div>
          )}
        </div>
      </div>

      {showModal && (
        <RecordAttendanceModal
          onClose={() => setShowModal(false)}
          onSubmit={(data) => createMutation.mutate(data)}
          isPending={createMutation.isPending}
        />
      )}
    </div>
  )
}
