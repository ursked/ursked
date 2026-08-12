'use client'

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { OvertimeCategory, LeaveTypeConfig } from '@/types'
import { useToast } from '@/components/ui/Toast'

const COMPENSATION_OPTIONS = [
  { value: 'paid', label: 'Paid (Cash)', description: 'Overtime is compensated through additional pay' },
  { value: 'leave_credit', label: 'Leave Credit', description: 'Overtime is converted to leave credits' },
  { value: 'both', label: 'Paid + Leave Credit', description: 'Overtime earns both additional pay and leave credits' },
  { value: 'none', label: 'No Compensation', description: 'Overtime is tracked but not compensated' },
]

const COMPENSATION_BADGE: Record<string, string> = {
  paid: 'bg-green-100 text-green-800',
  leave_credit: 'bg-blue-100 text-blue-800',
  both: 'bg-purple-100 text-purple-800',
  none: 'bg-gray-100 text-gray-800',
}

const COMPENSATION_LABEL: Record<string, string> = {
  paid: 'Paid',
  leave_credit: 'Leave Credit',
  both: 'Paid + Credit',
  none: 'None',
}

interface OTFormData {
  code: string
  name: string
  description: string
  multiplier_rate: number
  compensation_type: string
  leave_credit_rate: number | null
  leave_credit_type_id: number | null
  sort_order: number
}

const EMPTY_FORM: OTFormData = {
  code: '',
  name: '',
  description: '',
  multiplier_rate: 1.25,
  compensation_type: 'paid',
  leave_credit_rate: null,
  leave_credit_type_id: null,
  sort_order: 0,
}

export default function OvertimeTab() {
  const queryClient = useQueryClient()
  const { showToast } = useToast()

  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [formData, setFormData] = useState<OTFormData>(EMPTY_FORM)
  const [deleteConfirmId, setDeleteConfirmId] = useState<number | null>(null)

  // ── Queries ─────────────────────────────────────────────────────────
  const { data: categories, isLoading } = useQuery<OvertimeCategory[]>({
    queryKey: ['overtime-categories'],
    queryFn: () => api.getOvertimeCategories(),
  })

  const { data: leaveTypes } = useQuery<LeaveTypeConfig[]>({
    queryKey: ['leave-types'],
    queryFn: () => api.getLeaveTypes(),
  })

  const activeLeaveTypes = (leaveTypes ?? []).filter((lt) => lt.is_active)

  // ── Mutations ─────────────────────────────────────────────────────
  const createMutation = useMutation({
    mutationFn: (data: OTFormData) => {
      const payload: Record<string, unknown> = { ...data }
      if (!data.leave_credit_rate) delete payload.leave_credit_rate
      if (!data.leave_credit_type_id) delete payload.leave_credit_type_id
      return api.createOvertimeCategory(payload)
    },
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['overtime-categories'] }); resetForm(); showToast('Overtime category created', 'success') },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<OTFormData> }) => {
      const payload: Record<string, unknown> = { ...data }
      if (data.leave_credit_rate === null || data.leave_credit_rate === 0) delete payload.leave_credit_rate
      if (data.leave_credit_type_id === null) payload.leave_credit_type_id = null
      return api.updateOvertimeCategory(id, payload)
    },
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['overtime-categories'] }); resetForm(); showToast('Overtime category updated', 'success') },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.deleteOvertimeCategory(id),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['overtime-categories'] }); setDeleteConfirmId(null); showToast('Overtime category deactivated', 'success') },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  // ── Helpers ───────────────────────────────────────────────────────
  const resetForm = () => { setShowForm(false); setEditingId(null); setFormData(EMPTY_FORM) }

  const handleCodeChange = (value: string) => {
    const sanitized = value.toLowerCase().replace(/[^a-z0-9_]/g, '_')
    setFormData((prev) => ({ ...prev, code: sanitized }))
  }

  const handleEdit = (cat: OvertimeCategory) => {
    setEditingId(cat.id)
    setShowForm(false)
    setFormData({
      code: cat.code,
      name: cat.name,
      description: cat.description ?? '',
      multiplier_rate: cat.multiplier_rate,
      compensation_type: cat.compensation_type,
      leave_credit_rate: cat.leave_credit_rate ?? null,
      leave_credit_type_id: cat.leave_credit_type_id ?? null,
      sort_order: cat.sort_order,
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

  const needsLeaveCredit = formData.compensation_type === 'leave_credit' || formData.compensation_type === 'both'
  const needsPayRate = formData.compensation_type === 'paid' || formData.compensation_type === 'both'

  // Build conversion summary text
  const conversionSummary = () => {
    if (!needsLeaveCredit) return null
    const creditRate = formData.leave_credit_rate || 8
    const leaveTypeName = formData.leave_credit_type_id
      ? activeLeaveTypes.find((lt) => lt.id === formData.leave_credit_type_id)?.name ?? 'leave'
      : 'leave'
    return `${creditRate} hour${creditRate !== 1 ? 's' : ''} of overtime = 1 day of ${leaveTypeName}`
  }

  // ── Render: Form ──────────────────────────────────────────────────
  const renderForm = () => (
    <form onSubmit={handleSubmit} className="bg-gray-50 border border-gray-200 rounded-lg p-6 space-y-5">
      <h4 className="text-sm font-semibold text-gray-900">{editingId ? 'Edit Overtime Category' : 'New Overtime Category'}</h4>

      {/* Row 1: Code, Name, Description */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Code</label>
          <input type="text" required value={formData.code} onChange={(e) => handleCodeChange(e.target.value)}
            disabled={editingId !== null} placeholder="e.g. regular_ot"
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none disabled:opacity-50 disabled:bg-gray-100" />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Name</label>
          <input type="text" required value={formData.name} onChange={(e) => setFormData((p) => ({ ...p, name: e.target.value }))}
            placeholder="e.g. Regular Overtime"
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none" />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Description</label>
          <input type="text" value={formData.description} onChange={(e) => setFormData((p) => ({ ...p, description: e.target.value }))}
            placeholder="Optional"
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none" />
        </div>
      </div>

      {/* Row 2: Pay Rate — only relevant when compensation involves cash */}
      {needsPayRate && (
        <div className="max-w-md">
          <label className="block text-sm font-medium text-gray-700 mb-1">Pay Rate</label>
          <div className="flex items-center gap-3">
            <div className="relative flex-1">
              <input type="number" step="5" min="100" required
                value={Math.round(formData.multiplier_rate * 100)}
                onChange={(e) => {
                  const pct = parseInt(e.target.value, 10) || 100
                  setFormData((p) => ({ ...p, multiplier_rate: pct / 100 }))
                }}
                className="block w-full rounded-md border border-gray-300 px-3 py-2 pr-8 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none" />
              <span className="absolute right-3 top-1/2 -translate-y-1/2 text-sm text-gray-400 pointer-events-none">%</span>
            </div>
            <span className="text-sm text-gray-500 whitespace-nowrap">of regular rate</span>
          </div>
          <p className="mt-1.5 text-xs text-gray-500">
            {formData.multiplier_rate > 1
              ? `Employee earns ${Math.round(formData.multiplier_rate * 100)}% of their regular rate (+${Math.round((formData.multiplier_rate - 1) * 100)}% premium)`
              : formData.multiplier_rate === 1
                ? 'Same as regular rate (no overtime premium)'
                : `${Math.round(formData.multiplier_rate * 100)}% of regular rate (reduced rate)`}
          </p>
        </div>
      )}

      {/* Row 3: Compensation Type */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">How is overtime compensated?</label>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2">
          {COMPENSATION_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              type="button"
              onClick={() => setFormData((p) => ({
                ...p,
                compensation_type: opt.value,
                ...(opt.value !== 'leave_credit' && opt.value !== 'both'
                  ? { leave_credit_rate: null, leave_credit_type_id: null }
                  : {}),
                ...(opt.value === 'leave_credit' || opt.value === 'none'
                  ? { multiplier_rate: 1.0 }
                  : {}),
              }))}
              className={`text-left p-3 rounded-lg border-2 transition-all ${
                formData.compensation_type === opt.value
                  ? 'border-purple-500 bg-purple-50 ring-1 ring-purple-500'
                  : 'border-gray-200 bg-white hover:border-gray-300'
              }`}
            >
              <span className={`text-sm font-medium ${
                formData.compensation_type === opt.value ? 'text-purple-900' : 'text-gray-700'
              }`}>
                {opt.label}
              </span>
              <p className="text-xs text-gray-500 mt-0.5">{opt.description}</p>
            </button>
          ))}
        </div>
      </div>

      {/* Row 4: Leave Credit Configuration (conditional) */}
      {needsLeaveCredit && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 space-y-4">
          <div className="flex items-center gap-2 mb-1">
            <svg className="h-4 w-4 text-blue-600" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 012.25-2.25h13.5A2.25 2.25 0 0121 7.5v11.25m-18 0A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75m-18 0v-7.5A2.25 2.25 0 015.25 9h13.5A2.25 2.25 0 0121 11.25v7.5" />
            </svg>
            <span className="text-sm font-medium text-blue-900">Leave Credit Configuration</span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Credit to which leave type?</label>
              <select
                value={formData.leave_credit_type_id ?? ''}
                onChange={(e) => setFormData((p) => ({ ...p, leave_credit_type_id: parseInt(e.target.value, 10) || null }))}
                className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none"
              >
                <option value="">Select leave type...</option>
                {activeLeaveTypes.map((lt) => (
                  <option key={lt.id} value={lt.id}>{lt.name}</option>
                ))}
              </select>
              <p className="mt-1 text-xs text-gray-500">The leave type that overtime hours will be converted to.</p>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Conversion rate</label>
              <div className="flex items-center gap-2">
                <input type="number" step="0.5" min="0.5"
                  value={formData.leave_credit_rate ?? ''}
                  onChange={(e) => setFormData((p) => ({ ...p, leave_credit_rate: parseFloat(e.target.value) || null }))}
                  placeholder="8"
                  className="block w-24 rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none" />
                <span className="text-sm text-gray-600">hours OT = 1 day of leave</span>
              </div>
              <p className="mt-1 text-xs text-gray-500">How many overtime hours equal 1 day of leave credit.</p>
            </div>
          </div>

          {/* Conversion preview */}
          {conversionSummary() && (
            <div className="bg-white border border-blue-100 rounded-md p-3 mt-2">
              <p className="text-xs font-medium text-blue-800 mb-1">Conversion preview</p>
              <p className="text-sm text-blue-900">{conversionSummary()}</p>
              {formData.leave_credit_rate && (
                <p className="text-xs text-blue-600 mt-1">
                  e.g. An employee who works {formData.leave_credit_rate * 2} hours of overtime earns 2 days of {
                    formData.leave_credit_type_id
                      ? activeLeaveTypes.find((lt) => lt.id === formData.leave_credit_type_id)?.name ?? 'leave'
                      : 'leave'
                  }
                </p>
              )}
            </div>
          )}
        </div>
      )}

      {/* Sort order */}
      <div className="max-w-[200px]">
        <label className="block text-sm font-medium text-gray-700 mb-1">Display Order</label>
        <input type="number" value={formData.sort_order}
          onChange={(e) => setFormData((p) => ({ ...p, sort_order: parseInt(e.target.value, 10) || 0 }))}
          className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none" />
        <p className="mt-1 text-xs text-gray-500">Controls the order categories appear in dropdowns and lists. Lower numbers appear first.</p>
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
            <h2 className="text-lg font-semibold text-gray-900">Overtime Categories</h2>
            <p className="mt-1 text-sm text-gray-500">Define overtime types with pay rates and compensation rules.</p>
          </div>
          {!showForm && editingId === null && (
            <button type="button" onClick={() => { setShowForm(true); setEditingId(null); setFormData(EMPTY_FORM) }}
              className="inline-flex items-center gap-1.5 rounded-md bg-purple-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-purple-700 transition-colors">
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
              </svg>
              Add Category
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
          ) : categories && categories.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200">
                <thead>
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Code</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Name</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Pay Rate</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Compensation</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Leave Conversion</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Status</th>
                    <th className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-wider text-gray-500">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {categories.map((cat) => (
                    <tr key={cat.id} className="hover:bg-gray-50 transition-colors">
                      <td className="px-4 py-3 text-sm font-mono text-gray-900">{cat.code}</td>
                      <td className="px-4 py-3 text-sm text-gray-900">{cat.name}</td>
                      <td className="px-4 py-3">
                        {cat.compensation_type === 'paid' || cat.compensation_type === 'both' ? (
                          <>
                            <span className="text-sm font-medium text-gray-700">{Math.round(cat.multiplier_rate * 100)}%</span>
                            {cat.multiplier_rate > 1 && (
                              <span className="ml-1.5 text-xs text-gray-400">
                                (+{Math.round((cat.multiplier_rate - 1) * 100)}%)
                              </span>
                            )}
                          </>
                        ) : (
                          <span className="text-sm text-gray-400">--</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${COMPENSATION_BADGE[cat.compensation_type] ?? 'bg-gray-100 text-gray-800'}`}>
                          {COMPENSATION_LABEL[cat.compensation_type] ?? cat.compensation_type}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-600">
                        {(cat.compensation_type === 'leave_credit' || cat.compensation_type === 'both') ? (
                          <div>
                            <span>{cat.leave_credit_rate ?? 8}h = 1 day</span>
                            {cat.leave_credit_type_name && (
                              <span className="ml-1 text-xs text-blue-600">({cat.leave_credit_type_name})</span>
                            )}
                          </div>
                        ) : (
                          <span className="text-gray-400">--</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${cat.is_active ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}`}>
                          {cat.is_active ? 'Active' : 'Inactive'}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right">
                        <div className="flex items-center justify-end gap-2">
                          <button type="button" onClick={() => handleEdit(cat)}
                            className="inline-flex items-center rounded-md p-1.5 text-gray-400 hover:text-purple-600 hover:bg-purple-50 transition-colors" title="Edit">
                            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                              <path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125M18 14v4.75A2.25 2.25 0 0115.75 21H5.25A2.25 2.25 0 013 18.75V8.25A2.25 2.25 0 015.25 6H10" />
                            </svg>
                          </button>
                          {deleteConfirmId === cat.id ? (
                            <div className="flex items-center gap-1">
                              <button type="button" onClick={() => deleteMutation.mutate(cat.id)} disabled={deleteMutation.isPending}
                                className="inline-flex items-center rounded-md bg-red-600 px-2 py-1 text-xs font-medium text-white hover:bg-red-700 disabled:opacity-50 transition-colors">Deactivate</button>
                              <button type="button" onClick={() => setDeleteConfirmId(null)}
                                className="inline-flex items-center rounded-md bg-gray-100 px-2 py-1 text-xs font-medium text-gray-600 hover:bg-gray-200 transition-colors">Cancel</button>
                            </div>
                          ) : (
                            <button type="button" onClick={() => setDeleteConfirmId(cat.id)}
                              className="inline-flex items-center rounded-md p-1.5 text-gray-400 hover:text-amber-600 hover:bg-amber-50 transition-colors" title="Deactivate this category">
                              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" d="M3.98 8.223A10.477 10.477 0 001.934 12C3.226 16.338 7.244 19.5 12 19.5c.993 0 1.953-.138 2.863-.395M6.228 6.228A10.45 10.45 0 0112 4.5c4.756 0 8.773 3.162 10.065 7.498a10.523 10.523 0 01-4.293 5.774M6.228 6.228L3 3m3.228 3.228l3.65 3.65m7.894 7.894L21 21m-3.228-3.228l-3.65-3.65m0 0a3 3 0 10-4.243-4.243m4.242 4.242L9.88 9.88" />
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
              <h3 className="mt-2 text-sm font-semibold text-gray-900">No overtime categories</h3>
              <p className="mt-1 text-sm text-gray-500">Define overtime categories to manage compensation rules.</p>
              <div className="mt-6">
                <button type="button" onClick={() => { setShowForm(true); setEditingId(null); setFormData(EMPTY_FORM) }}
                  className="inline-flex items-center gap-1.5 rounded-md bg-purple-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-purple-700 transition-colors">
                  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
                  </svg>
                  Add Category
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
