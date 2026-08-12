'use client'

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { EmployeeTypeConfig } from '@/types'
import { useToast } from '@/components/ui/Toast'

interface FormData {
  code: string
  name: string
  description: string
  sort_order: number
}

const EMPTY_FORM: FormData = {
  code: '',
  name: '',
  description: '',
  sort_order: 0,
}

export default function EmployeeTypesTab() {
  const queryClient = useQueryClient()
  const { showToast } = useToast()

  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [formData, setFormData] = useState<FormData>(EMPTY_FORM)
  const [deleteConfirmId, setDeleteConfirmId] = useState<number | null>(null)

  const { data: types, isLoading } = useQuery<EmployeeTypeConfig[]>({
    queryKey: ['employee-types-all'],
    queryFn: () => api.getAllEmployeeTypes(),
  })

  const createMutation = useMutation({
    mutationFn: (data: FormData) => api.createEmployeeType(data),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['employee-types-all'] }); queryClient.invalidateQueries({ queryKey: ['employee-types'] }); resetForm(); showToast('Employee type created', 'success') },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<FormData> }) => api.updateEmployeeType(id, data),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['employee-types-all'] }); queryClient.invalidateQueries({ queryKey: ['employee-types'] }); resetForm(); showToast('Employee type updated', 'success') },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.deleteEmployeeType(id),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['employee-types-all'] }); queryClient.invalidateQueries({ queryKey: ['employee-types'] }); setDeleteConfirmId(null); showToast('Employee type deactivated', 'success') },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  const resetForm = () => { setShowForm(false); setEditingId(null); setFormData(EMPTY_FORM) }

  const handleCodeChange = (value: string) => {
    const sanitized = value.toLowerCase().replace(/[^a-z0-9_]/g, '_')
    setFormData((prev) => ({ ...prev, code: sanitized }))
  }

  const handleEdit = (item: EmployeeTypeConfig) => {
    setEditingId(item.id)
    setShowForm(false)
    setFormData({
      code: item.code,
      name: item.name,
      description: item.description ?? '',
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
      <h4 className="text-sm font-semibold text-gray-900">{editingId ? 'Edit Employee Type' : 'New Employee Type'}</h4>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Code</label>
          <input type="text" required value={formData.code} onChange={(e) => handleCodeChange(e.target.value)}
            disabled={editingId !== null} placeholder="e.g. part_time"
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none disabled:opacity-50 disabled:bg-gray-100" />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Name</label>
          <input type="text" required value={formData.name} onChange={(e) => setFormData((p) => ({ ...p, name: e.target.value }))}
            placeholder="e.g. Part Time"
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none" />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Description</label>
          <input type="text" value={formData.description} onChange={(e) => setFormData((p) => ({ ...p, description: e.target.value }))}
            placeholder="Optional"
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none" />
        </div>
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
            <h2 className="text-lg font-semibold text-gray-900">Employee Types</h2>
            <p className="mt-1 text-sm text-gray-500">Define the employment classifications used across your organization.</p>
          </div>
          {!showForm && editingId === null && (
            <button type="button" onClick={() => { setShowForm(true); setEditingId(null); setFormData(EMPTY_FORM) }}
              className="inline-flex items-center gap-1.5 rounded-md bg-purple-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-purple-700 transition-colors">
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
              </svg>
              Add Type
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
          ) : types && types.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200">
                <thead>
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Code</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Name</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Description</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Type</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Status</th>
                    <th className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-wider text-gray-500">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {types.map((item) => (
                    <tr key={item.id} className="hover:bg-gray-50 transition-colors">
                      <td className="px-4 py-3 text-sm font-mono text-gray-900">{item.code}</td>
                      <td className="px-4 py-3 text-sm text-gray-900">{item.name}</td>
                      <td className="px-4 py-3 text-sm text-gray-500">{item.description || '--'}</td>
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
                <path strokeLinecap="round" strokeLinejoin="round" d="M15 19.128a9.38 9.38 0 002.625.372 9.337 9.337 0 004.121-.952 4.125 4.125 0 00-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 018.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0111.964-3.07M12 6.375a3.375 3.375 0 11-6.75 0 3.375 3.375 0 016.75 0zm8.25 2.25a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z" />
              </svg>
              <h3 className="mt-2 text-sm font-semibold text-gray-900">No employee types</h3>
              <p className="mt-1 text-sm text-gray-500">Define employee types to classify your workforce.</p>
              <div className="mt-6">
                <button type="button" onClick={() => { setShowForm(true); setEditingId(null); setFormData(EMPTY_FORM) }}
                  className="inline-flex items-center gap-1.5 rounded-md bg-purple-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-purple-700 transition-colors">
                  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
                  </svg>
                  Add Type
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
