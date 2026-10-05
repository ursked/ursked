'use client'

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { DeductionBracket, DeductionType } from '@/types'
import { useToast } from '@/components/ui/Toast'
import { usePermissions } from '@/contexts/PermissionsContext'
import BracketEditor from './BracketEditor'
import { LoadProblem } from './financeUi'

interface FormData {
  code: string
  name: string
  description: string
  calculation_type: string
  calculation_basis: 'gross' | 'base'
  default_amount: number | null
  default_rate: number | null
  is_mandatory: boolean
  is_employer_contribution: boolean
  sort_order: number
}

const EMPTY_FORM: FormData = {
  code: '',
  name: '',
  description: '',
  calculation_type: 'fixed',
  calculation_basis: 'gross',
  default_amount: null,
  default_rate: null,
  is_mandatory: false,
  is_employer_contribution: false,
  sort_order: 0,
}

/** How many brackets a tiered deduction has. None means it deducts nothing,
 *  which is exactly how statutory contributions went unpaid unnoticed. */
function BracketStatus({ dt }: { dt: DeductionType }) {
  const { data } = useQuery<DeductionBracket[]>({
    queryKey: ['deduction-brackets', dt.id],
    queryFn: () => api.getDeductionBrackets(dt.id),
  })
  if (!data) return null
  if (data.length === 0) {
    return <span className="block text-xs font-medium text-red-700">No brackets: deducts nothing</span>
  }
  return <span className="block text-xs text-gray-500">{data.length} bracket{data.length === 1 ? '' : 's'}</span>
}

export default function DeductionsTab() {
  const queryClient = useQueryClient()
  const { showToast } = useToast()
  const { hasPermission } = usePermissions()
  const canCreate = hasPermission('finances', 'create')
  const canEdit = hasPermission('finances', 'edit')
  const canDelete = hasPermission('finances', 'delete')

  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [formData, setFormData] = useState<FormData>(EMPTY_FORM)
  const [deleteConfirmId, setDeleteConfirmId] = useState<number | null>(null)
  const [bracketsFor, setBracketsFor] = useState<DeductionType | null>(null)

  const { data: deductions, isLoading, error } = useQuery<DeductionType[]>({
    queryKey: ['deduction-types-all'],
    queryFn: () => api.getAllDeductionTypes(),
  })

  const createMutation = useMutation({
    mutationFn: (data: FormData) => {
      const payload = {
        code: data.code,
        name: data.name,
        description: data.description || undefined,
        calculation_type: data.calculation_type,
        calculation_basis: data.calculation_basis,
        default_amount: data.default_amount ?? undefined,
        default_rate: data.default_rate ?? undefined,
        is_mandatory: data.is_mandatory,
        is_employer_contribution: data.is_employer_contribution,
        sort_order: data.sort_order,
      }
      return api.createDeductionType(payload)
    },
    onSuccess: (dt) => {
      queryClient.invalidateQueries({ queryKey: ['deduction-types-all'] })
      resetForm()
      showToast('Deduction type created', 'success')
      // A tiered type is useless until its table exists; go straight there.
      if (dt.calculation_type === 'tiered') setBracketsFor(dt)
    },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Record<string, unknown> }) =>
      api.updateDeductionType(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['deduction-types-all'] })
      resetForm()
      showToast('Deduction type updated', 'success')
    },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.deleteDeductionType(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['deduction-types-all'] })
      setDeleteConfirmId(null)
      showToast('Deduction type removed', 'success')
    },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  function resetForm() {
    setShowForm(false)
    setEditingId(null)
    setFormData(EMPTY_FORM)
  }

  function startEdit(dt: DeductionType) {
    setFormData({
      code: dt.code,
      name: dt.name,
      description: dt.description || '',
      calculation_type: dt.calculation_type,
      calculation_basis: dt.calculation_basis === 'base' ? 'base' : 'gross',
      default_amount: dt.default_amount ?? null,
      default_rate: dt.default_rate ?? null,
      is_mandatory: dt.is_mandatory,
      is_employer_contribution: dt.is_employer_contribution,
      sort_order: dt.sort_order,
    })
    setEditingId(dt.id)
    setShowForm(true)
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (editingId) {
      updateMutation.mutate({ id: editingId, data: { ...formData, description: formData.description || null } })
    } else {
      createMutation.mutate(formData)
    }
  }

  const calcLabel = (type: string) => {
    switch (type) {
      case 'fixed': return 'Fixed Amount'
      case 'percentage': return 'Percentage'
      case 'tiered': return 'Tiered'
      default: return type
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-gray-900">Deduction &amp; Contribution Types</h2>
        {!showForm && canCreate && (
          <button
            onClick={() => { resetForm(); setShowForm(true) }}
            className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700"
          >
            Add Type
          </button>
        )}
      </div>

      {showForm && (
        <form onSubmit={handleSubmit} className="rounded-lg border border-gray-200 bg-white p-4 space-y-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label className="block text-sm font-medium text-gray-700">Code</label>
              <input
                type="text"
                required
                disabled={!!editingId}
                value={formData.code}
                onChange={(e) => setFormData({ ...formData, code: e.target.value })}
                className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-brand-500 focus:ring-brand-500 disabled:bg-gray-100"
                placeholder="e.g. sss"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">Name</label>
              <input
                type="text"
                required
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-brand-500 focus:ring-brand-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">Calculation Type</label>
              <select
                value={formData.calculation_type}
                onChange={(e) => setFormData({ ...formData, calculation_type: e.target.value })}
                className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-brand-500 focus:ring-brand-500"
              >
                <option value="fixed">Fixed Amount</option>
                <option value="percentage">Percentage</option>
                <option value="tiered">Tiered</option>
              </select>
            </div>
            {formData.calculation_type === 'tiered' ? (
              <div className="text-sm text-gray-600 sm:pt-6">
                The amount comes from the brackets table. Save, then set its brackets.
              </div>
            ) : formData.calculation_type === 'fixed' ? (
              <div>
                <label className="block text-sm font-medium text-gray-700">Default Amount</label>
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  value={formData.default_amount ?? ''}
                  onChange={(e) => setFormData({ ...formData, default_amount: e.target.value ? parseFloat(e.target.value) : null })}
                  className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-brand-500 focus:ring-brand-500"
                />
              </div>
            ) : (
              <div>
                <label className="block text-sm font-medium text-gray-700">Rate (e.g. 0.025 = 2.5%)</label>
                <input
                  type="number"
                  step="0.001"
                  min="0"
                  max="1"
                  value={formData.default_rate ?? ''}
                  onChange={(e) => setFormData({ ...formData, default_rate: e.target.value ? parseFloat(e.target.value) : null })}
                  className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-brand-500 focus:ring-brand-500"
                />
              </div>
            )}
            {formData.calculation_type !== 'fixed' && (
              <div>
                <label className="block text-sm font-medium text-gray-700">Worked out from</label>
                <select
                  value={formData.calculation_basis}
                  onChange={(e) => setFormData({ ...formData, calculation_basis: e.target.value as 'gross' | 'base' })}
                  className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-brand-500 focus:ring-brand-500"
                >
                  <option value="gross">Gross pay</option>
                  <option value="base">Base pay</option>
                </select>
              </div>
            )}
            <div>
              <label className="block text-sm font-medium text-gray-700">Sort Order</label>
              <input
                type="number"
                value={formData.sort_order}
                onChange={(e) => setFormData({ ...formData, sort_order: parseInt(e.target.value) || 0 })}
                className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-brand-500 focus:ring-brand-500"
              />
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700">Description</label>
            <input
              type="text"
              value={formData.description}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-brand-500 focus:ring-brand-500"
            />
          </div>
          <div className="flex gap-6">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={formData.is_mandatory}
                onChange={(e) => setFormData({ ...formData, is_mandatory: e.target.checked })}
                className="rounded border-gray-300 text-brand-600 focus:ring-brand-500"
              />
              Mandatory (auto-applied)
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={formData.is_employer_contribution}
                onChange={(e) => setFormData({ ...formData, is_employer_contribution: e.target.checked })}
                className="rounded border-gray-300 text-brand-600 focus:ring-brand-500"
              />
              Employer Contribution
            </label>
          </div>
          <div className="flex justify-end gap-2">
            <button type="button" onClick={resetForm} className="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50">
              Cancel
            </button>
            <button type="submit" disabled={createMutation.isPending || updateMutation.isPending} className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50">
              {editingId ? 'Update' : 'Create'}
            </button>
          </div>
        </form>
      )}

      {isLoading ? (
        <div className="text-center py-8 text-gray-500">Loading...</div>
      ) : error ? (
        <LoadProblem error={error} what="deduction types" />
      ) : !deductions?.length ? (
        <div className="text-center py-8 text-gray-500">No deduction types defined yet.</div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Code</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Name</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Type</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Amount/Rate</th>
                <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase">Mandatory</th>
                <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase">Employer</th>
                <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase">Status</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 bg-white">
              {deductions.map((dt) => (
                <tr key={dt.id} className={!dt.is_active ? 'opacity-50' : ''}>
                  <td className="px-4 py-3 text-sm font-mono text-gray-900">{dt.code}</td>
                  <td className="px-4 py-3 text-sm text-gray-900">{dt.name}</td>
                  <td className="px-4 py-3 text-sm text-gray-500">
                    {calcLabel(dt.calculation_type)}
                    {dt.calculation_type === 'tiered' && <BracketStatus dt={dt} />}
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-900 text-right">
                    {dt.calculation_type === 'percentage'
                      ? `${((dt.default_rate || 0) * 100).toFixed(1)}%`
                      : dt.calculation_type === 'tiered'
                        ? 'From brackets'
                        : dt.default_amount != null
                          ? dt.default_amount.toLocaleString()
                          : '—'}
                  </td>
                  <td className="px-4 py-3 text-center text-sm">{dt.is_mandatory ? '✓' : ''}</td>
                  <td className="px-4 py-3 text-center text-sm">{dt.is_employer_contribution ? '✓' : ''}</td>
                  <td className="px-4 py-3 text-center">
                    <button
                      type="button"
                      onClick={() => updateMutation.mutate({ id: dt.id, data: { is_active: !dt.is_active } })}
                      disabled={updateMutation.isPending || !canEdit}
                      className={`relative inline-flex h-5 w-9 disabled:opacity-50 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-brand-500 focus:ring-offset-2 ${dt.is_active ? 'bg-brand-600' : 'bg-gray-200'}`}
                      title={dt.is_active ? 'Click to deactivate' : 'Click to activate'}
                    >
                      <span className={`pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${dt.is_active ? 'translate-x-4' : 'translate-x-0'}`} />
                    </button>
                  </td>
                  <td className="px-4 py-3 text-right space-x-2">
                    {dt.calculation_type === 'tiered' && (
                      <button onClick={() => setBracketsFor(dt)} className="text-sm text-brand-600 hover:text-brand-800">
                        {canEdit ? 'Brackets' : 'View brackets'}
                      </button>
                    )}
                    {canEdit && (
                      <button onClick={() => startEdit(dt)} className="text-sm text-brand-600 hover:text-brand-800">Edit</button>
                    )}
                    {!canDelete ? null : deleteConfirmId === dt.id ? (
                      <>
                        <button onClick={() => deleteMutation.mutate(dt.id)} disabled={deleteMutation.isPending} className="text-sm text-red-600 hover:text-red-800 disabled:opacity-50 disabled:cursor-not-allowed">{deleteMutation.isPending ? 'Deleting…' : 'Confirm'}</button>
                        <button onClick={() => setDeleteConfirmId(null)} className="text-sm text-gray-500 hover:text-gray-700">Cancel</button>
                      </>
                    ) : (
                      <button onClick={() => setDeleteConfirmId(dt.id)} className="text-sm text-red-600 hover:text-red-800">Delete</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {bracketsFor && (
        <BracketEditor deduction={bracketsFor} canEdit={canEdit} onClose={() => setBracketsFor(null)} />
      )}
    </div>
  )
}
