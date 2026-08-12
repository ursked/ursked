'use client'

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { DateRemark } from '@/types'
import { useToast } from '@/components/ui/Toast'

interface HolidayFormData {
  date: string
  title: string
  description: string
  is_recurring: boolean
  is_special: boolean
}

const EMPTY_FORM: HolidayFormData = {
  date: '',
  title: '',
  description: '',
  is_recurring: false,
  is_special: false,
}

function formatDate(dateStr: string): string {
  const d = new Date(dateStr + 'T00:00:00')
  return d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' })
}

export default function HolidaysTab() {
  const queryClient = useQueryClient()
  const { showToast } = useToast()

  const currentYear = new Date().getFullYear()
  const [selectedYear, setSelectedYear] = useState<number>(currentYear)
  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [formData, setFormData] = useState<HolidayFormData>(EMPTY_FORM)
  const [deleteConfirmId, setDeleteConfirmId] = useState<number | null>(null)

  // ── Queries ─────────────────────────────────────────────────────────
  const { data: holidays, isLoading } = useQuery<DateRemark[]>({
    queryKey: ['holidays', selectedYear],
    queryFn: () => api.getHolidays(selectedYear) as Promise<DateRemark[]>,
  })

  // ── Mutations ─────────────────────────────────────────────────────
  const createMutation = useMutation({
    mutationFn: (data: HolidayFormData) =>
      api.createDateRemark({
        date: data.date,
        title: data.title,
        description: data.description || undefined,
        is_holiday: true,
        is_special: data.is_special,
        is_recurring: data.is_recurring,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['holidays'] })
      resetForm()
      showToast('Holiday created', 'success')
    },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<HolidayFormData> }) =>
      api.updateDateRemark(id, {
        ...data,
        description: data.description || undefined,
        is_holiday: true,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['holidays'] })
      resetForm()
      showToast('Holiday updated', 'success')
    },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.deleteDateRemark(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['holidays'] })
      setDeleteConfirmId(null)
      showToast('Holiday deleted', 'success')
    },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  // ── Helpers ───────────────────────────────────────────────────────
  const resetForm = () => {
    setShowForm(false)
    setEditingId(null)
    setFormData(EMPTY_FORM)
  }

  const handleEdit = (holiday: DateRemark) => {
    setEditingId(holiday.id)
    setShowForm(false)
    setFormData({
      date: holiday.date,
      title: holiday.title,
      description: holiday.description ?? '',
      is_recurring: holiday.is_recurring,
      is_special: holiday.is_special,
    })
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (editingId !== null) {
      updateMutation.mutate({ id: editingId, data: formData })
    } else {
      createMutation.mutate(formData)
    }
  }

  const isMutating = createMutation.isPending || updateMutation.isPending || deleteMutation.isPending

  const yearOptions = Array.from({ length: 5 }, (_, i) => currentYear - 1 + i)

  // ── Render: Form ──────────────────────────────────────────────────
  const renderForm = () => (
    <form onSubmit={handleSubmit} className="bg-gray-50 border border-gray-200 rounded-lg p-6 space-y-5">
      <h4 className="text-sm font-semibold text-gray-900">
        {editingId ? 'Edit Holiday' : 'New Holiday'}
      </h4>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Date</label>
          <input
            type="date"
            required
            value={formData.date}
            onChange={(e) => setFormData((p) => ({ ...p, date: e.target.value }))}
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Holiday Name</label>
          <input
            type="text"
            required
            value={formData.title}
            onChange={(e) => setFormData((p) => ({ ...p, title: e.target.value }))}
            placeholder="e.g. New Year's Day"
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Description</label>
          <input
            type="text"
            value={formData.description}
            onChange={(e) => setFormData((p) => ({ ...p, description: e.target.value }))}
            placeholder="Optional"
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none"
          />
        </div>
      </div>

      <div className="flex flex-wrap gap-6">
        <label className="relative flex items-start gap-3 cursor-pointer">
          <div className="flex h-6 items-center">
            <input
              type="checkbox"
              checked={formData.is_recurring}
              onChange={(e) => setFormData((p) => ({ ...p, is_recurring: e.target.checked }))}
              className="h-4 w-4 rounded border-gray-300 text-purple-600 focus:ring-purple-500"
            />
          </div>
          <div>
            <span className="text-sm font-medium text-gray-700">Recurring</span>
            <p className="text-xs text-gray-500">Repeats every year on the same date</p>
          </div>
        </label>

        <label className="relative flex items-start gap-3 cursor-pointer">
          <div className="flex h-6 items-center">
            <input
              type="checkbox"
              checked={formData.is_special}
              onChange={(e) => setFormData((p) => ({ ...p, is_special: e.target.checked }))}
              className="h-4 w-4 rounded border-gray-300 text-purple-600 focus:ring-purple-500"
            />
          </div>
          <div>
            <span className="text-sm font-medium text-gray-700">Special Non-Working Holiday</span>
            <p className="text-xs text-gray-500">Distinguished from regular holidays for pay rules</p>
          </div>
        </label>
      </div>

      <div className="flex items-center gap-3 pt-2">
        <button
          type="submit"
          disabled={isMutating}
          className="inline-flex items-center rounded-md bg-purple-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {isMutating ? 'Saving...' : editingId ? 'Update' : 'Create'}
        </button>
        <button
          type="button"
          onClick={resetForm}
          className="inline-flex items-center rounded-md bg-white px-4 py-2 text-sm font-semibold text-gray-700 shadow-sm ring-1 ring-inset ring-gray-300 hover:bg-gray-50 transition-colors"
        >
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
            <h2 className="text-lg font-semibold text-gray-900">Holidays</h2>
            <p className="mt-1 text-sm text-gray-500">
              Manage company holidays. Holiday pay and leave credit conversions are calculated based on the actual hours worked on holiday dates.
            </p>
          </div>
          {!showForm && editingId === null && (
            <button
              type="button"
              onClick={() => {
                setShowForm(true)
                setEditingId(null)
                setFormData(EMPTY_FORM)
              }}
              className="inline-flex items-center gap-1.5 rounded-md bg-purple-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-purple-700 transition-colors"
            >
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
              </svg>
              Add Holiday
            </button>
          )}
        </div>

        <div className="px-6 py-6 space-y-6">
          {/* Year filter */}
          <div className="flex items-center gap-3">
            <label className="text-sm font-medium text-gray-700">Year:</label>
            <div className="flex items-center gap-1">
              {yearOptions.map((year) => (
                <button
                  key={year}
                  type="button"
                  onClick={() => setSelectedYear(year)}
                  className={`px-3 py-1.5 text-sm rounded-md font-medium transition-colors ${
                    selectedYear === year
                      ? 'bg-purple-600 text-white'
                      : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                  }`}
                >
                  {year}
                </button>
              ))}
            </div>
          </div>

          {(showForm || editingId !== null) && renderForm()}

          {isLoading ? (
            <div className="flex items-center gap-3 text-sm text-gray-500">
              <svg className="h-5 w-5 animate-spin text-purple-600" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              Loading...
            </div>
          ) : holidays && holidays.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200">
                <thead>
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Date</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Holiday Name</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Description</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Type</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Recurring</th>
                    <th className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-wider text-gray-500">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {holidays.map((holiday) => (
                    <tr key={holiday.id} className="hover:bg-gray-50 transition-colors">
                      <td className="px-4 py-3 text-sm text-gray-900 whitespace-nowrap">
                        {formatDate(holiday.date)}
                      </td>
                      <td className="px-4 py-3 text-sm font-medium text-gray-900">{holiday.title}</td>
                      <td className="px-4 py-3 text-sm text-gray-600">{holiday.description || '--'}</td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${
                            holiday.is_special
                              ? 'bg-amber-100 text-amber-800'
                              : 'bg-red-100 text-red-800'
                          }`}
                        >
                          {holiday.is_special ? 'Special' : 'Regular'}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        {holiday.is_recurring ? (
                          <span className="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium bg-blue-100 text-blue-800">
                            Yearly
                          </span>
                        ) : (
                          <span className="text-sm text-gray-400">One-time</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <div className="flex items-center justify-end gap-2">
                          <button
                            type="button"
                            onClick={() => handleEdit(holiday)}
                            className="inline-flex items-center rounded-md p-1.5 text-gray-400 hover:text-purple-600 hover:bg-purple-50 transition-colors"
                            title="Edit"
                          >
                            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                              <path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125M18 14v4.75A2.25 2.25 0 0115.75 21H5.25A2.25 2.25 0 013 18.75V8.25A2.25 2.25 0 015.25 6H10" />
                            </svg>
                          </button>
                          {deleteConfirmId === holiday.id ? (
                            <div className="flex items-center gap-1">
                              <button
                                type="button"
                                onClick={() => deleteMutation.mutate(holiday.id)}
                                disabled={deleteMutation.isPending}
                                className="inline-flex items-center rounded-md bg-red-600 px-2 py-1 text-xs font-medium text-white hover:bg-red-700 disabled:opacity-50 transition-colors"
                              >
                                Delete
                              </button>
                              <button
                                type="button"
                                onClick={() => setDeleteConfirmId(null)}
                                className="inline-flex items-center rounded-md bg-gray-100 px-2 py-1 text-xs font-medium text-gray-600 hover:bg-gray-200 transition-colors"
                              >
                                Cancel
                              </button>
                            </div>
                          ) : (
                            <button
                              type="button"
                              onClick={() => setDeleteConfirmId(holiday.id)}
                              className="inline-flex items-center rounded-md p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 transition-colors"
                              title="Delete"
                            >
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
                <path strokeLinecap="round" strokeLinejoin="round" d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 012.25-2.25h13.5A2.25 2.25 0 0121 7.5v11.25m-18 0A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75m-18 0v-7.5A2.25 2.25 0 015.25 9h13.5A2.25 2.25 0 0121 11.25v7.5" />
              </svg>
              <h3 className="mt-2 text-sm font-semibold text-gray-900">No holidays for {selectedYear}</h3>
              <p className="mt-1 text-sm text-gray-500">Add holidays to configure holiday pay and leave credit rules.</p>
              <div className="mt-6">
                <button
                  type="button"
                  onClick={() => {
                    setShowForm(true)
                    setEditingId(null)
                    setFormData(EMPTY_FORM)
                  }}
                  className="inline-flex items-center gap-1.5 rounded-md bg-purple-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-purple-700 transition-colors"
                >
                  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
                  </svg>
                  Add Holiday
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* How It Works info box */}
      <details className="bg-white shadow-sm ring-1 ring-gray-900/5 rounded-xl">
        <summary className="px-6 py-4 cursor-pointer text-sm font-medium text-gray-700 hover:text-gray-900">
          How Holiday Pay Works
        </summary>
        <div className="px-6 pb-5 text-sm text-gray-600 space-y-3">
          <p>
            Holiday pay and leave credit conversions are calculated based on <strong>actual hours worked on the holiday date</strong>,
            not the total shift duration. This is important for overnight shifts that span across midnight.
          </p>
          <div className="bg-gray-50 rounded-lg p-4 space-y-2">
            <p className="font-medium text-gray-700">Example:</p>
            <p>
              Employee works from 10:00 PM on January 1 (Holiday) to 6:00 AM on January 2 (Regular Day).
            </p>
            <ul className="list-disc list-inside space-y-1 ml-2">
              <li><strong>Holiday hours:</strong> 2 hours (10:00 PM - 12:00 AM on Jan 1)</li>
              <li><strong>Regular hours:</strong> 6 hours (12:00 AM - 6:00 AM on Jan 2)</li>
            </ul>
            <p>
              Only the 2 hours on the actual holiday date qualify for holiday pay or leave credit conversion.
            </p>
          </div>
          <p>
            <strong>Recurring holidays</strong> automatically apply every year on the same date (e.g., January 1 for New Year).
            <strong> Special holidays</strong> can be distinguished from regular holidays for different pay rules via policy configuration.
          </p>
        </div>
      </details>
    </div>
  )
}
