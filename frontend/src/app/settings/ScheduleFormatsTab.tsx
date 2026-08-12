'use client'

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { ScheduleFormatConfig } from '@/types'
import { useToast } from '@/components/ui/Toast'

interface FormData {
  code: string
  name: string
  description: string
  hours_per_day: number | null
  hours_per_week: number | null
  is_flexible: boolean
  paid_break_minutes: number
  unpaid_break_minutes: number
  paid_break_after_hours: number
  unpaid_break_after_hours: number
  sort_order: number
}

const EMPTY_FORM: FormData = {
  code: '',
  name: '',
  description: '',
  hours_per_day: 8,
  hours_per_week: 40,
  is_flexible: false,
  paid_break_minutes: 0,
  unpaid_break_minutes: 0,
  paid_break_after_hours: 4,
  unpaid_break_after_hours: 4,
  sort_order: 0,
}

export default function ScheduleFormatsTab() {
  const queryClient = useQueryClient()
  const { showToast } = useToast()

  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [formData, setFormData] = useState<FormData>(EMPTY_FORM)
  const [deleteConfirmId, setDeleteConfirmId] = useState<number | null>(null)

  const { data: formats, isLoading } = useQuery<ScheduleFormatConfig[]>({
    queryKey: ['schedule-formats-all'],
    queryFn: () => api.getAllScheduleFormats(),
  })

  const createMutation = useMutation({
    mutationFn: (data: FormData) => {
      const payload: Record<string, unknown> = { ...data }
      if (data.is_flexible) {
        payload.hours_per_day = null
      }
      return api.createScheduleFormat(payload as Parameters<typeof api.createScheduleFormat>[0])
    },
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['schedule-formats-all'] }); queryClient.invalidateQueries({ queryKey: ['schedule-formats'] }); resetForm(); showToast('Schedule format created', 'success') },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<FormData> }) => {
      const payload: Record<string, unknown> = { ...data }
      if (data.is_flexible) {
        payload.hours_per_day = null
      }
      return api.updateScheduleFormat(id, payload as Parameters<typeof api.updateScheduleFormat>[1])
    },
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['schedule-formats-all'] }); queryClient.invalidateQueries({ queryKey: ['schedule-formats'] }); resetForm(); showToast('Schedule format updated', 'success') },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.deleteScheduleFormat(id),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['schedule-formats-all'] }); queryClient.invalidateQueries({ queryKey: ['schedule-formats'] }); setDeleteConfirmId(null); showToast('Schedule format deactivated', 'success') },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  const resetForm = () => { setShowForm(false); setEditingId(null); setFormData(EMPTY_FORM) }

  const handleCodeChange = (value: string) => {
    const sanitized = value.toLowerCase().replace(/[^a-z0-9_]/g, '_')
    setFormData((prev) => ({ ...prev, code: sanitized }))
  }

  const handleEdit = (item: ScheduleFormatConfig) => {
    setEditingId(item.id)
    setShowForm(false)
    setFormData({
      code: item.code,
      name: item.name,
      description: item.description ?? '',
      hours_per_day: item.hours_per_day ?? null,
      hours_per_week: item.hours_per_week ?? null,
      is_flexible: item.is_flexible,
      paid_break_minutes: item.paid_break_minutes ?? 0,
      unpaid_break_minutes: item.unpaid_break_minutes ?? 0,
      paid_break_after_hours: item.paid_break_after_hours ?? 4,
      unpaid_break_after_hours: item.unpaid_break_after_hours ?? 4,
      sort_order: item.sort_order,
    })
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (editingId !== null) {
      const { code: _code, ...rest } = formData
      updateMutation.mutate({ id: editingId, data: rest })
    } else {
      createMutation.mutate(formData)
    }
  }

  const isMutating = createMutation.isPending || updateMutation.isPending || deleteMutation.isPending

  const renderForm = () => (
    <form onSubmit={handleSubmit} className="bg-gray-50 border border-gray-200 rounded-lg p-6 space-y-4">
      <h4 className="text-sm font-semibold text-gray-900">{editingId ? 'Edit Schedule Format' : 'New Schedule Format'}</h4>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Code</label>
          <input type="text" required value={formData.code} onChange={(e) => handleCodeChange(e.target.value)}
            disabled={editingId !== null} placeholder="e.g. 10_hour"
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none disabled:opacity-50 disabled:bg-gray-100" />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Name</label>
          <input type="text" required value={formData.name} onChange={(e) => setFormData((p) => ({ ...p, name: e.target.value }))}
            placeholder="e.g. 10-Hour Shift"
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none" />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Description</label>
          <input type="text" value={formData.description} onChange={(e) => setFormData((p) => ({ ...p, description: e.target.value }))}
            placeholder="Optional"
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none" />
        </div>
        <div>
          <label className="flex items-center gap-2 text-sm font-medium text-gray-700 mb-1">
            <input type="checkbox" checked={formData.is_flexible}
              onChange={(e) => setFormData((p) => ({ ...p, is_flexible: e.target.checked, hours_per_day: e.target.checked ? null : 8 }))}
              className="rounded border-gray-300 text-purple-600 focus:ring-purple-500" />
            Flexible Schedule
          </label>
          <p className="text-xs text-gray-500">No fixed daily hours</p>
        </div>
        {!formData.is_flexible && (
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Hours per Day</label>
            <input type="number" step="0.5" min="1" max="24" value={formData.hours_per_day ?? ''}
              onChange={(e) => setFormData((p) => ({ ...p, hours_per_day: parseFloat(e.target.value) || null }))}
              className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none" />
          </div>
        )}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Hours per Week</label>
          <input type="number" step="0.5" min="1" max="168" value={formData.hours_per_week ?? ''}
            onChange={(e) => setFormData((p) => ({ ...p, hours_per_week: parseFloat(e.target.value) || null }))}
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none" />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Paid Break (mins)</label>
          <input type="number" min="0" max="480" value={formData.paid_break_minutes}
            onChange={(e) => setFormData((p) => ({ ...p, paid_break_minutes: parseInt(e.target.value, 10) || 0 }))}
            placeholder="0"
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none" />
          <p className="text-xs text-gray-500 mt-0.5">Included in working hours</p>
        </div>
        {formData.paid_break_minutes > 0 && (
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Paid Break After (hrs)</label>
            <input type="number" step="0.5" min="0" max="24" value={formData.paid_break_after_hours}
              onChange={(e) => setFormData((p) => ({ ...p, paid_break_after_hours: parseFloat(e.target.value) || 0 }))}
              className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none" />
            <p className="text-xs text-gray-500 mt-0.5">Break starts N hours after shift begins</p>
          </div>
        )}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Unpaid Break (mins)</label>
          <input type="number" min="0" max="480" value={formData.unpaid_break_minutes}
            onChange={(e) => setFormData((p) => ({ ...p, unpaid_break_minutes: parseInt(e.target.value, 10) || 0 }))}
            placeholder="0"
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none" />
          <p className="text-xs text-gray-500 mt-0.5">Not included in working hours</p>
        </div>
        {formData.unpaid_break_minutes > 0 && (
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Unpaid Break After (hrs)</label>
            <input type="number" step="0.5" min="0" max="24" value={formData.unpaid_break_after_hours}
              onChange={(e) => setFormData((p) => ({ ...p, unpaid_break_after_hours: parseFloat(e.target.value) || 0 }))}
              className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none" />
            <p className="text-xs text-gray-500 mt-0.5">Break starts N hours after shift begins</p>
          </div>
        )}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Sort Order</label>
          <input type="number" value={formData.sort_order}
            onChange={(e) => setFormData((p) => ({ ...p, sort_order: parseInt(e.target.value, 10) || 0 }))}
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none" />
        </div>
      </div>
      <div className="flex items-center gap-3 pt-2">
        <button type="submit" disabled={isMutating}
          className="inline-flex items-center rounded-md bg-purple-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors">
          {isMutating ? 'Saving...' : editingId ? 'Update' : 'Create'}
        </button>
        <button type="button" onClick={resetForm}
          className="inline-flex items-center rounded-md bg-white px-4 py-2 text-sm font-semibold text-gray-700 shadow-sm ring-1 ring-inset ring-gray-300 hover:bg-gray-50 transition-colors">
          Cancel
        </button>
      </div>
    </form>
  )

  return (
    <div className="space-y-8">
      <div className="bg-white shadow-sm ring-1 ring-gray-900/5 rounded-xl">
        <div className="border-b border-gray-200 px-6 py-4 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Schedule Formats</h2>
            <p className="mt-1 text-sm text-gray-500">Define shift formats and working hour configurations for your organization.</p>
          </div>
          {!showForm && editingId === null && (
            <button type="button" onClick={() => { setShowForm(true); setEditingId(null); setFormData(EMPTY_FORM) }}
              className="inline-flex items-center gap-1.5 rounded-md bg-purple-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-purple-700 transition-colors">
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
              </svg>
              Add Format
            </button>
          )}
        </div>

        <div className="px-6 py-6 space-y-6">
          {(showForm || editingId !== null) && renderForm()}

          {isLoading ? (
            <div className="flex items-center gap-3 text-sm text-gray-500">
              <svg className="h-5 w-5 animate-spin text-purple-600" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              Loading...
            </div>
          ) : formats && formats.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200">
                <thead>
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Code</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Name</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Hours/Day</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Hours/Week</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Paid Break</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Unpaid Break</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Type</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Status</th>
                    <th className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-wider text-gray-500">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {formats.map((item) => (
                    <tr key={item.id} className="hover:bg-gray-50 transition-colors">
                      <td className="px-4 py-3 text-sm font-mono text-gray-900">{item.code}</td>
                      <td className="px-4 py-3 text-sm text-gray-900">{item.name}</td>
                      <td className="px-4 py-3 text-sm text-gray-600">
                        {item.is_flexible ? (
                          <span className="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium bg-amber-100 text-amber-800">Flexible</span>
                        ) : (
                          `${item.hours_per_day}h`
                        )}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-600">{item.hours_per_week ? `${item.hours_per_week}h` : '--'}</td>
                      <td className="px-4 py-3 text-sm text-gray-600">{item.paid_break_minutes ? `${item.paid_break_minutes}m after ${item.paid_break_after_hours}h` : '--'}</td>
                      <td className="px-4 py-3 text-sm text-gray-600">{item.unpaid_break_minutes ? `${item.unpaid_break_minutes}m after ${item.unpaid_break_after_hours}h` : '--'}</td>
                      <td className="px-4 py-3">
                        <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${item.is_system ? 'bg-blue-100 text-blue-800' : 'bg-gray-100 text-gray-800'}`}>
                          {item.is_system ? 'System' : 'Custom'}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${item.is_active ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}`}>
                          {item.is_active ? 'Active' : 'Inactive'}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right">
                        <div className="flex items-center justify-end gap-2">
                          <button type="button" onClick={() => handleEdit(item)}
                            className="inline-flex items-center rounded-md p-1.5 text-gray-400 hover:text-purple-600 hover:bg-purple-50 transition-colors" title="Edit">
                            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                              <path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125M18 14v4.75A2.25 2.25 0 0115.75 21H5.25A2.25 2.25 0 013 18.75V8.25A2.25 2.25 0 015.25 6H10" />
                            </svg>
                          </button>
                          {deleteConfirmId === item.id ? (
                            <div className="flex items-center gap-1">
                              <button type="button" onClick={() => deleteMutation.mutate(item.id)} disabled={deleteMutation.isPending}
                                className="inline-flex items-center rounded-md bg-red-600 px-2 py-1 text-xs font-medium text-white hover:bg-red-700 disabled:opacity-50 transition-colors">Confirm</button>
                              <button type="button" onClick={() => setDeleteConfirmId(null)}
                                className="inline-flex items-center rounded-md bg-gray-100 px-2 py-1 text-xs font-medium text-gray-600 hover:bg-gray-200 transition-colors">Cancel</button>
                            </div>
                          ) : (
                            <button type="button" onClick={() => setDeleteConfirmId(item.id)}
                              className="inline-flex items-center rounded-md p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 transition-colors" title="Deactivate">
                              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
                              </svg>
                            </button>
                          )}
                        </div>
                      </td>
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
              <h3 className="mt-2 text-sm font-semibold text-gray-900">No schedule formats</h3>
              <p className="mt-1 text-sm text-gray-500">Define schedule formats to manage shift configurations.</p>
              <div className="mt-6">
                <button type="button" onClick={() => { setShowForm(true); setEditingId(null); setFormData(EMPTY_FORM) }}
                  className="inline-flex items-center gap-1.5 rounded-md bg-purple-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-purple-700 transition-colors">
                  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
                  </svg>
                  Add Format
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
