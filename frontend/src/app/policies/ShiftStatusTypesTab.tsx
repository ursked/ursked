'use client'

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { ShiftStatusType } from '@/types'
import { useAuth } from '@/contexts/AuthContext'
import { hasAnyRole } from '@/lib/roles'

// Shift status types, moved here from Settings -> General so they sit with the
// other rules about the schedule. The gates are the API's, unchanged by the
// move: every signed-in user may read the list (the grid needs it to draw a
// shift), and creating, editing and deleting a type is for the tenant_admin
// role only (require_role on /settings/status-types), so the buttons show on
// exactly that condition.

const CATEGORY_OPTIONS = [
  { value: 'work', label: 'Work' },
  { value: 'rest', label: 'Rest' },
  { value: 'leave', label: 'Leave' },
]

const CATEGORY_BADGE_CLASSES: Record<string, string> = {
  work: 'bg-green-100 text-green-800',
  rest: 'bg-gray-100 text-gray-800',
  leave: 'bg-amber-100 text-amber-800',
}

interface StatusTypeFormData {
  code: string
  label: string
  short_label: string
  color: string
  bg_class: string
  category: string
  sort_order: number
}

const EMPTY_FORM: StatusTypeFormData = {
  code: '',
  label: '',
  short_label: '',
  color: '#6b7280',
  bg_class: '',
  category: 'work',
  sort_order: 0,
}

export default function ShiftStatusTypesTab() {
  const queryClient = useQueryClient()
  const { user } = useAuth()
  const canManage = !!user && hasAnyRole(user, ['tenant_admin'])

  const [showAddForm, setShowAddForm] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [formData, setFormData] = useState<StatusTypeFormData>(EMPTY_FORM)
  const [deleteConfirmId, setDeleteConfirmId] = useState<number | null>(null)

  const { data: statusTypes, isLoading: statusTypesLoading } = useQuery<ShiftStatusType[]>({
    queryKey: ['status-types'],
    queryFn: () => api.getStatusTypes(),
  })

  const createStatusTypeMutation = useMutation({
    mutationFn: (data: StatusTypeFormData) => api.createStatusType(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['status-types'] })
      resetForm()
    },
  })

  const updateStatusTypeMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<StatusTypeFormData> }) =>
      api.updateStatusType(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['status-types'] })
      resetForm()
    },
  })

  const deleteStatusTypeMutation = useMutation({
    mutationFn: (id: number) => api.deleteStatusType(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['status-types'] })
      setDeleteConfirmId(null)
    },
  })

  const resetForm = () => {
    setShowAddForm(false)
    setEditingId(null)
    setFormData(EMPTY_FORM)
  }

  const handleCodeChange = (value: string) => {
    const sanitized = value.toLowerCase().replace(/[^a-z0-9_]/g, '_')
    setFormData((prev) => ({ ...prev, code: sanitized }))
  }

  const handleEditClick = (st: ShiftStatusType) => {
    setEditingId(st.id)
    setShowAddForm(false)
    setFormData({
      code: st.code,
      label: st.label,
      short_label: st.short_label,
      color: st.color,
      bg_class: st.bg_class ?? '',
      category: st.category,
      sort_order: st.sort_order ?? 0,
    })
  }

  const handleFormSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (editingId !== null) {
      updateStatusTypeMutation.mutate({ id: editingId, data: formData })
    } else {
      createStatusTypeMutation.mutate(formData)
    }
  }

  const isMutating =
    createStatusTypeMutation.isPending ||
    updateStatusTypeMutation.isPending ||
    deleteStatusTypeMutation.isPending

  const renderStatusTypeForm = () => (
    <form onSubmit={handleFormSubmit} className="bg-gray-50 border border-gray-200 rounded-lg p-6 space-y-4">
      <h4 className="text-sm font-semibold text-gray-900">
        {editingId !== null ? 'Edit Status Type' : 'New Status Type'}
      </h4>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        <div>
          <label htmlFor="status-code" className="block text-sm font-medium text-gray-700 mb-1">Code</label>
          <input id="status-code" type="text" required value={formData.code}
            onChange={(e) => handleCodeChange(e.target.value)} placeholder="e.g. sick_leave"
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-brand-500 focus:ring-brand-500 focus:outline-none" />
          <p className="mt-1 text-xs text-gray-500">Lowercase letters, numbers, and underscores only</p>
        </div>
        <div>
          <label htmlFor="status-label" className="block text-sm font-medium text-gray-700 mb-1">Label</label>
          <input id="status-label" type="text" required value={formData.label}
            onChange={(e) => setFormData((prev) => ({ ...prev, label: e.target.value }))} placeholder="e.g. Sick Leave"
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-brand-500 focus:ring-brand-500 focus:outline-none" />
        </div>
        <div>
          <label htmlFor="status-short-label" className="block text-sm font-medium text-gray-700 mb-1">Short Label</label>
          <input id="status-short-label" type="text" required value={formData.short_label}
            onChange={(e) => setFormData((prev) => ({ ...prev, short_label: e.target.value }))} placeholder="e.g. SL"
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-brand-500 focus:ring-brand-500 focus:outline-none" />
        </div>
        <div>
          <label htmlFor="status-color" className="block text-sm font-medium text-gray-700 mb-1">Color</label>
          <div className="flex items-center gap-2">
            <input id="status-color" type="color" value={formData.color}
              onChange={(e) => setFormData((prev) => ({ ...prev, color: e.target.value }))}
              className="h-9 w-12 cursor-pointer rounded border border-gray-300 p-0.5" />
            <input type="text" value={formData.color}
              onChange={(e) => setFormData((prev) => ({ ...prev, color: e.target.value }))}
              placeholder="#6b7280" pattern="^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$"
              className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-brand-500 focus:ring-brand-500 focus:outline-none" />
          </div>
        </div>
        <div>
          <label htmlFor="status-bg-class" className="block text-sm font-medium text-gray-700 mb-1">Background Class</label>
          <input id="status-bg-class" type="text" value={formData.bg_class}
            onChange={(e) => setFormData((prev) => ({ ...prev, bg_class: e.target.value }))} placeholder="e.g. bg-brand-100"
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-brand-500 focus:ring-brand-500 focus:outline-none" />
        </div>
        <div>
          <label htmlFor="status-category" className="block text-sm font-medium text-gray-700 mb-1">Category</label>
          <select id="status-category" required value={formData.category}
            onChange={(e) => setFormData((prev) => ({ ...prev, category: e.target.value }))}
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-brand-500 focus:ring-brand-500 focus:outline-none">
            {CATEGORY_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="status-sort-order" className="block text-sm font-medium text-gray-700 mb-1">Sort Order</label>
          <input id="status-sort-order" type="number" value={formData.sort_order}
            onChange={(e) => setFormData((prev) => ({ ...prev, sort_order: parseInt(e.target.value, 10) || 0 }))}
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-brand-500 focus:ring-brand-500 focus:outline-none" />
        </div>
      </div>
      <div className="flex items-center gap-3 pt-2">
        <button type="submit" disabled={isMutating}
          className="inline-flex items-center rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-brand-700 focus:outline-none focus:ring-2 focus:ring-brand-500 focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed transition-colors">
          {isMutating ? 'Saving...' : editingId !== null ? 'Update Status Type' : 'Create Status Type'}
        </button>
        <button type="button" onClick={resetForm}
          className="inline-flex items-center rounded-md bg-white px-4 py-2 text-sm font-semibold text-gray-700 shadow-sm ring-1 ring-inset ring-gray-300 hover:bg-gray-50 transition-colors">
          Cancel
        </button>
      </div>
    </form>
  )

  return (
    <div className="bg-white shadow-sm ring-1 ring-gray-900/5 rounded-xl">
      <div className="border-b border-gray-200 px-6 py-4 flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-gray-900">Shift Status Types</h2>
          <p className="mt-1 text-sm text-gray-500">Define the status types available for scheduling shifts.</p>
        </div>
        {canManage && !showAddForm && editingId === null && (
          <button type="button" onClick={() => { setShowAddForm(true); setEditingId(null); setFormData(EMPTY_FORM) }}
            className="inline-flex items-center gap-1.5 rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-brand-700 focus:outline-none focus:ring-2 focus:ring-brand-500 focus:ring-offset-2 transition-colors">
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
            </svg>
            Add Status Type
          </button>
        )}
      </div>

      <div className="px-6 py-6 space-y-6">
        {canManage && (showAddForm || editingId !== null) && renderStatusTypeForm()}

        {statusTypesLoading ? (
          <div className="flex items-center gap-3 text-sm text-gray-500">
            <svg className="h-5 w-5 animate-spin text-brand-600" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            Loading status types...
          </div>
        ) : statusTypes && statusTypes.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead>
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Code</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Label</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Short Label</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Color</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Category</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">System</th>
                  {canManage && (
                    <th className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-wider text-gray-500">Actions</th>
                  )}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {statusTypes.map((st) => (
                  <tr key={st.id} className="hover:bg-gray-50 transition-colors">
                    <td className="px-4 py-3 text-sm font-mono text-gray-900">{st.code}</td>
                    <td className="px-4 py-3 text-sm text-gray-900">{st.label}</td>
                    <td className="px-4 py-3 text-sm text-gray-600">{st.short_label}</td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <span className="inline-block h-5 w-5 rounded-full border border-gray-200 flex-shrink-0"
                          style={{ backgroundColor: st.color }} title={st.color} />
                        <span className="text-xs text-gray-500 font-mono">{st.color}</span>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${CATEGORY_BADGE_CLASSES[st.category] ?? 'bg-gray-100 text-gray-800'}`}>
                        {st.category}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      {st.is_system ? (
                        <span className="inline-flex items-center rounded-full bg-brand-100 text-brand-800 px-2.5 py-0.5 text-xs font-medium">System</span>
                      ) : (
                        <span className="text-sm text-gray-500">--</span>
                      )}
                    </td>
                    {canManage && (
                      <td className="px-4 py-3 text-right">
                        <div className="flex items-center justify-end gap-2">
                          <button type="button" onClick={() => handleEditClick(st)}
                            className="inline-flex items-center rounded-md p-1.5 text-gray-400 hover:text-brand-600 hover:bg-brand-50 transition-colors" title="Edit">
                            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                              <path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125M18 14v4.75A2.25 2.25 0 0115.75 21H5.25A2.25 2.25 0 013 18.75V8.25A2.25 2.25 0 015.25 6H10" />
                            </svg>
                          </button>
                          {deleteConfirmId === st.id ? (
                            <div className="flex items-center gap-1">
                              <button type="button" onClick={() => deleteStatusTypeMutation.mutate(st.id)}
                                disabled={deleteStatusTypeMutation.isPending}
                                className="inline-flex items-center rounded-md bg-red-600 px-2 py-1 text-xs font-medium text-white hover:bg-red-700 disabled:opacity-50 transition-colors">
                                Confirm
                              </button>
                              <button type="button" onClick={() => setDeleteConfirmId(null)}
                                className="inline-flex items-center rounded-md bg-gray-100 px-2 py-1 text-xs font-medium text-gray-600 hover:bg-gray-200 transition-colors">
                                Cancel
                              </button>
                            </div>
                          ) : (
                            <button type="button" onClick={() => setDeleteConfirmId(st.id)} disabled={st.is_system}
                              className="inline-flex items-center rounded-md p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 transition-colors disabled:opacity-30 disabled:cursor-not-allowed disabled:hover:text-gray-400 disabled:hover:bg-transparent"
                              title={st.is_system ? 'System types cannot be deleted' : 'Delete'}>
                              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
                              </svg>
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
              <path strokeLinecap="round" strokeLinejoin="round" d="M9.568 3H5.25A2.25 2.25 0 003 5.25v4.318c0 .597.237 1.17.659 1.591l9.581 9.581c.699.699 1.78.872 2.607.33a18.095 18.095 0 005.223-5.223c.542-.827.369-1.908-.33-2.607L11.16 3.66A2.25 2.25 0 009.568 3z" />
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 6h.008v.008H6V6z" />
            </svg>
            <h3 className="mt-2 text-sm font-semibold text-gray-900">No status types</h3>
            {canManage && (
              <>
                <p className="mt-1 text-sm text-gray-500">Get started by adding a new status type.</p>
                <div className="mt-6">
                  <button type="button" onClick={() => { setShowAddForm(true); setEditingId(null); setFormData(EMPTY_FORM) }}
                    className="inline-flex items-center gap-1.5 rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-brand-700 focus:outline-none focus:ring-2 focus:ring-brand-500 focus:ring-offset-2 transition-colors">
                    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
                    </svg>
                    Add Status Type
                  </button>
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
