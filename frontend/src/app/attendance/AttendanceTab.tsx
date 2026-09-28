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

const STATUS_CHOICES = [
  { value: '', label: 'Work it out from the times' },
  { value: 'present', label: 'Present' },
  { value: 'late', label: 'Late' },
  { value: 'absent', label: 'Absent' },
  { value: 'half_day', label: 'Half day' },
  { value: 'excused', label: 'Excused' },
]

export default function AttendanceTab() {
  const queryClient = useQueryClient()
  const { showToast } = useToast()
  const { hasPermission } = usePermissions()
  const canEdit = hasPermission('schedules', 'edit')

  const [showModal, setShowModal] = useState(false)
  const [editing, setEditing] = useState<AttendanceRecord | null>(null)
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')

  const { data: records, isLoading, error } = useQuery<AttendanceRecord[]>({
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

  const formatTime = (t?: string | null) => (t ? t.slice(0, 5) : '--')
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
            <p className="mt-1 text-sm text-gray-500">View, record and correct employee attendance.</p>
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
              <label htmlFor="att-start" className="block text-xs font-medium text-gray-500 mb-1">Start Date</label>
              <input
                id="att-start"
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
                className="rounded-md border border-gray-300 px-3 py-1.5 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none"
              />
            </div>
            <div>
              <label htmlFor="att-end" className="block text-xs font-medium text-gray-500 mb-1">End Date</label>
              <input
                id="att-end"
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
          ) : error ? (
            <p className="text-sm text-red-700">Could not load attendance: {(error as Error).message}</p>
          ) : records && records.length > 0 ? (
            <div className="relative overflow-x-auto">
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
                    {canEdit && <th className="px-4 py-3"><span className="sr-only">Actions</span></th>}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {records.map((rec) => (
                    <tr key={rec.id} className="hover:bg-gray-50 transition-colors">
                      <td className="px-4 py-3 text-sm text-gray-900">{rec.employee_name || `#${rec.employee_id}`}</td>
                      <td className="px-4 py-3 text-sm text-gray-700">{rec.date}</td>
                      <td className="px-4 py-3 text-sm text-gray-600">
                        {rec.scheduled_start_time ? `${formatTime(rec.scheduled_start_time)} - ${formatTime(rec.scheduled_end_time)}` : 'Not rostered'}
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
                          {rec.excused_by_leave_id ? 'On leave' : rec.status.replace('_', ' ')}
                        </span>
                        <div className="mt-1 flex flex-wrap gap-1">
                          {rec.self_reported && (
                            <span className="rounded bg-sky-50 px-1.5 py-0.5 text-[11px] font-medium text-sky-800" title="Entered or clocked by the employee">Self-reported</span>
                          )}
                          {rec.is_rest_day_work && (
                            <span className="rounded bg-orange-50 px-1.5 py-0.5 text-[11px] font-medium text-orange-800" title="Worked on a rest day or with no published shift">Rest-day work</span>
                          )}
                          {rec.auto_marked && (
                            <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[11px] font-medium text-gray-700" title="Marked absent automatically: no clock-in for a published shift">Automatic</span>
                          )}
                          {rec.status_override && (
                            <span className="rounded bg-purple-50 px-1.5 py-0.5 text-[11px] font-medium text-purple-800" title="Status set by hand">Set by hand</span>
                          )}
                        </div>
                      </td>
                      {canEdit && (
                        <td className="px-4 py-3 text-right">
                          <button
                            type="button"
                            onClick={() => setEditing(rec)}
                            className="rounded-md bg-purple-50 px-2.5 py-1 text-xs font-medium text-purple-700 hover:bg-purple-100"
                          >
                            Edit
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
                <path strokeLinecap="round" strokeLinejoin="round" d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 012.25-2.25h13.5A2.25 2.25 0 0121 7.5v11.25m-18 0A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75m-18 0v-7.5A2.25 2.25 0 015.25 9h13.5A2.25 2.25 0 0121 11.25v7.5" />
              </svg>
              <h3 className="mt-2 text-sm font-semibold text-gray-900">No attendance records</h3>
              <p className="mt-1 text-sm text-gray-500">{canEdit ? 'Record attendance entries using the button above.' : 'Nothing has been recorded for this range.'}</p>
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

      {editing && (
        <EditAttendanceModal
          record={editing}
          onClose={() => setEditing(null)}
          onDone={() => {
            setEditing(null)
            queryClient.invalidateQueries({ queryKey: ['attendance-records'] })
            showToast('Attendance corrected', 'success')
          }}
        />
      )}
    </div>
  )
}

/** Correct a record. A reason is required: the change is written to the audit
 *  log with before and after, because it changes what payroll pays. */
function EditAttendanceModal({ record, onClose, onDone }: {
  record: AttendanceRecord
  onClose: () => void
  onDone: () => void
}) {
  const { showToast } = useToast()
  const [start, setStart] = useState(record.actual_start_time?.slice(0, 5) ?? '')
  const [end, setEnd] = useState(record.actual_end_time?.slice(0, 5) ?? '')
  const [status, setStatus] = useState(record.status_override ?? '')
  const [notes, setNotes] = useState(record.notes ?? '')
  const [reason, setReason] = useState('')

  const save = useMutation({
    mutationFn: () =>
      api.updateAttendance(record.id, {
        actual_start_time: start ? `${start}:00` : null,
        actual_end_time: end ? `${end}:00` : null,
        status,
        notes,
        reason: reason.trim(),
      }),
    onSuccess: onDone,
    onError: (e: Error) => showToast(e.message, 'error'),
  })

  const reasonOk = reason.trim().length >= 3

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-labelledby="edit-att-title"
        className="w-full max-w-lg rounded-xl bg-white p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <h3 id="edit-att-title" className="text-lg font-semibold text-gray-900">Correct attendance</h3>
        <p className="mt-1 text-sm text-gray-600">
          {record.employee_name || `Employee #${record.employee_id}`}, {record.date}
          {record.scheduled_start_time ? `, rostered ${record.scheduled_start_time.slice(0, 5)} to ${record.scheduled_end_time?.slice(0, 5)}` : ''}.
          Lateness, overtime and pay are worked out again from what you enter.
        </p>
        <div className="mt-4 grid grid-cols-2 gap-3">
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-gray-700">Started</span>
            <input type="time" className="input" value={start} onChange={(e) => setStart(e.target.value)} />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-gray-700">Finished</span>
            <input type="time" className="input" value={end} onChange={(e) => setEnd(e.target.value)} />
            <span className="mt-1 block text-xs text-gray-500">Earlier than the start means the next morning.</span>
          </label>
          <label className="col-span-2 block">
            <span className="mb-1 block text-sm font-medium text-gray-700">Status</span>
            <select className="input" value={status} onChange={(e) => setStatus(e.target.value)}>
              {STATUS_CHOICES.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
            </select>
          </label>
          <label className="col-span-2 block">
            <span className="mb-1 block text-sm font-medium text-gray-700">Notes</span>
            <input className="input" value={notes} onChange={(e) => setNotes(e.target.value)} />
          </label>
          <label className="col-span-2 block">
            <span className="mb-1 block text-sm font-medium text-gray-700">Reason for the change (required)</span>
            <input className="input" value={reason} onChange={(e) => setReason(e.target.value)}
              placeholder="e.g. Badge reader was down" aria-invalid={!reasonOk && reason.length > 0} />
          </label>
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50">Cancel</button>
          <button type="button" onClick={() => save.mutate()} disabled={!reasonOk || save.isPending}
            className="rounded-md bg-purple-600 px-4 py-2 text-sm font-semibold text-white hover:bg-purple-700 disabled:opacity-50">
            {save.isPending ? 'Saving…' : 'Save correction'}
          </button>
        </div>
      </div>
    </div>
  )
}
