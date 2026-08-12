'use client'

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { SalaryGrade } from '@/types'
import { useToast } from '@/components/ui/Toast'
import { useCurrency } from '@/lib/currency'

interface FormData {
  code: string
  name: string
  description: string
  monthly_rate: number
  daily_rate: number | null
  hourly_rate: number | null
  sort_order: number
}

const EMPTY_FORM: FormData = {
  code: '',
  name: '',
  description: '',
  monthly_rate: 0,
  daily_rate: null,
  hourly_rate: null,
  sort_order: 0,
}

export default function SalaryGradesTab() {
  const queryClient = useQueryClient()
  const { showToast } = useToast()

  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [formData, setFormData] = useState<FormData>(EMPTY_FORM)
  const [deleteConfirmId, setDeleteConfirmId] = useState<number | null>(null)

  const { data: grades, isLoading } = useQuery<SalaryGrade[]>({
    queryKey: ['salary-grades-all'],
    queryFn: () => api.getAllSalaryGrades(),
  })

  const createMutation = useMutation({
    mutationFn: (data: FormData) =>
      api.createSalaryGrade({
        code: data.code,
        name: data.name,
        monthly_rate: data.monthly_rate,
        daily_rate: data.daily_rate ?? undefined,
        hourly_rate: data.hourly_rate ?? undefined,
        description: data.description || undefined,
        sort_order: data.sort_order,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['salary-grades-all'] })
      resetForm()
      showToast('Salary grade created', 'success')
    },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Record<string, unknown> }) =>
      api.updateSalaryGrade(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['salary-grades-all'] })
      resetForm()
      showToast('Salary grade updated', 'success')
    },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.deleteSalaryGrade(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['salary-grades-all'] })
      setDeleteConfirmId(null)
      showToast('Salary grade removed', 'success')
    },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  function resetForm() {
    setShowForm(false)
    setEditingId(null)
    setFormData(EMPTY_FORM)
  }

  function startEdit(grade: SalaryGrade) {
    setFormData({
      code: grade.code,
      name: grade.name,
      description: grade.description || '',
      monthly_rate: grade.monthly_rate,
      daily_rate: grade.daily_rate ?? null,
      hourly_rate: grade.hourly_rate ?? null,
      sort_order: grade.sort_order,
    })
    setEditingId(grade.id)
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

  const { format: formatCurrency } = useCurrency()

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-gray-900">Salary Grades</h2>
        {!showForm && (
          <button
            onClick={() => { resetForm(); setShowForm(true) }}
            className="rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700"
          >
            Add Grade
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
                className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-purple-500 focus:ring-purple-500 disabled:bg-gray-100"
                placeholder="e.g. SG-1"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">Name</label>
              <input
                type="text"
                required
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-purple-500 focus:ring-purple-500"
                placeholder="e.g. Grade 1 - Entry Level"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">Monthly Rate</label>
              <input
                type="number"
                required
                step="0.01"
                min="0"
                value={formData.monthly_rate}
                onChange={(e) => setFormData({ ...formData, monthly_rate: parseFloat(e.target.value) || 0 })}
                className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-purple-500 focus:ring-purple-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">Daily Rate (optional)</label>
              <input
                type="number"
                step="0.01"
                min="0"
                value={formData.daily_rate ?? ''}
                onChange={(e) => setFormData({ ...formData, daily_rate: e.target.value ? parseFloat(e.target.value) : null })}
                className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-purple-500 focus:ring-purple-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">Hourly Rate (optional)</label>
              <input
                type="number"
                step="0.01"
                min="0"
                value={formData.hourly_rate ?? ''}
                onChange={(e) => setFormData({ ...formData, hourly_rate: e.target.value ? parseFloat(e.target.value) : null })}
                className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-purple-500 focus:ring-purple-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">Sort Order</label>
              <input
                type="number"
                value={formData.sort_order}
                onChange={(e) => setFormData({ ...formData, sort_order: parseInt(e.target.value) || 0 })}
                className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-purple-500 focus:ring-purple-500"
              />
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700">Description</label>
            <input
              type="text"
              value={formData.description}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-purple-500 focus:ring-purple-500"
            />
          </div>
          <div className="flex justify-end gap-2">
            <button type="button" onClick={resetForm} className="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50">
              Cancel
            </button>
            <button type="submit" disabled={createMutation.isPending || updateMutation.isPending} className="rounded-md bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50">
              {editingId ? 'Update' : 'Create'}
            </button>
          </div>
        </form>
      )}

      {isLoading ? (
        <div className="text-center py-8 text-gray-500">Loading...</div>
      ) : !grades?.length ? (
        <div className="text-center py-8 text-gray-500">No salary grades defined yet.</div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Code</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Name</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Monthly</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Daily</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Hourly</th>
                <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase">Status</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 bg-white">
              {grades.map((g) => (
                <tr key={g.id} className={!g.is_active ? 'opacity-50' : ''}>
                  <td className="px-4 py-3 text-sm font-mono text-gray-900">{g.code}</td>
                  <td className="px-4 py-3 text-sm text-gray-900">{g.name}</td>
                  <td className="px-4 py-3 text-sm text-gray-900 text-right">{formatCurrency(g.monthly_rate)}</td>
                  <td className="px-4 py-3 text-sm text-gray-500 text-right">{g.daily_rate ? formatCurrency(g.daily_rate) : '—'}</td>
                  <td className="px-4 py-3 text-sm text-gray-500 text-right">{g.hourly_rate ? formatCurrency(g.hourly_rate) : '—'}</td>
                  <td className="px-4 py-3 text-center">
                    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${g.is_active ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'}`}>
                      {g.is_active ? 'Active' : 'Inactive'}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right space-x-2">
                    <button onClick={() => startEdit(g)} className="text-sm text-purple-600 hover:text-purple-800">Edit</button>
                    {deleteConfirmId === g.id ? (
                      <>
                        <button onClick={() => deleteMutation.mutate(g.id)} className="text-sm text-red-600 hover:text-red-800">Confirm</button>
                        <button onClick={() => setDeleteConfirmId(null)} className="text-sm text-gray-500 hover:text-gray-700">Cancel</button>
                      </>
                    ) : (
                      <button onClick={() => setDeleteConfirmId(g.id)} className="text-sm text-red-600 hover:text-red-800">Delete</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
