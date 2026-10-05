'use client'

import { useMemo, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { hasAnyRole } from '@/lib/roles'
import { useAuth } from '@/contexts/AuthContext'
import { usePermissions } from '@/contexts/PermissionsContext'
import { DateRemark, HolidayRegion, HolidaySourceConfig, HolidaySyncItem, HolidaySyncResult } from '@/types'
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

// Holidays apply to the whole company. They are configuration: an
// administrator changes them from the admin dashboard (the role is in force
// only in an admin session, which has no schedules permission at all), and so
// may people who schedule everyone, from the regular one (the schedules
// permission AND one of these roles, FULL_SCOPE_ROLES["schedules"] in
// permission_service). The buttons follow the same rule, so nobody is offered
// an action that will be refused.
const FULL_SCOPE_SCHEDULE_ROLES = ['hr', 'schedule_editor']

function formatDate(dateStr: string): string {
  const d = new Date(dateStr + 'T00:00:00')
  return d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' })
}

function Pill({ children, className, title }: { children: React.ReactNode; className: string; title?: string }) {
  return (
    <span title={title} className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ${className}`}>
      {children}
    </span>
  )
}

export default function HolidaysTab() {
  const queryClient = useQueryClient()
  const { showToast } = useToast()
  const { user } = useAuth()
  const { hasPermission } = usePermissions()
  const isAdmin = user ? hasAnyRole(user, ['tenant_admin']) : false
  const fullScope = user ? hasAnyRole(user, FULL_SCOPE_SCHEDULE_ROLES) : false
  const canCreate = isAdmin || (fullScope && hasPermission('schedules', 'create'))
  const canEdit = isAdmin || (fullScope && hasPermission('schedules', 'edit'))
  const canDelete = isAdmin || (fullScope && hasPermission('schedules', 'delete'))
  const canViewSource = isAdmin || hasPermission('schedules', 'view')

  const currentYear = new Date().getFullYear()
  const [selectedYear, setSelectedYear] = useState<number>(currentYear)
  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editingRecurringOn, setEditingRecurringOn] = useState<string | null>(null)
  const [formData, setFormData] = useState<HolidayFormData>(EMPTY_FORM)
  const [deleteConfirmId, setDeleteConfirmId] = useState<number | null>(null)

  // ── Queries ─────────────────────────────────────────────────────────
  const { data: holidays, isLoading } = useQuery<DateRemark[]>({
    queryKey: ['holidays', selectedYear],
    queryFn: () => api.getHolidays(selectedYear) as Promise<DateRemark[]>,
  })

  const { data: source } = useQuery<HolidaySourceConfig>({
    queryKey: ['holiday-source'],
    queryFn: () => api.getHolidaySource(),
    enabled: canViewSource,
  })
  const regionLabels = useMemo(() => {
    const m = new Map<string, string>()
    for (const r of source?.discovered_regions ?? []) m.set(r.code, r.label)
    return m
  }, [source])

  // ── Mutations ─────────────────────────────────────────────────────
  const createMutation = useMutation({
    mutationFn: (data: HolidayFormData) =>
      api.createDateRemark({
        date: data.date,
        title: data.title,
        description: data.description.trim() || undefined,
        is_holiday: true,
        is_special: data.is_special,
        is_recurring: data.is_recurring,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['holidays'] })
      queryClient.invalidateQueries({ queryKey: ['schedule-grid'] })
      resetForm()
      showToast('Holiday created', 'success')
    },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: HolidayFormData }) =>
      api.updateDateRemark(id, {
        ...data,
        // null clears the description (sending nothing used to leave it as it was).
        description: data.description.trim() || null,
        is_holiday: true,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['holidays'] })
      queryClient.invalidateQueries({ queryKey: ['schedule-grid'] })
      resetForm()
      showToast('Holiday updated', 'success')
    },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.deleteDateRemark(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['holidays'] })
      queryClient.invalidateQueries({ queryKey: ['schedule-grid'] })
      setDeleteConfirmId(null)
      showToast('Holiday deleted', 'success')
    },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  // ── Helpers ───────────────────────────────────────────────────────
  const resetForm = () => {
    setShowForm(false)
    setEditingId(null)
    setEditingRecurringOn(null)
    setFormData(EMPTY_FORM)
  }

  const handleEdit = (holiday: DateRemark) => {
    setEditingId(holiday.id)
    setShowForm(false)
    // A recurring holiday listed in another year shows that year's date; the
    // edit must change the stored row, not move it to this year.
    const stored = holiday.stored_date ?? holiday.date
    setEditingRecurringOn(holiday.is_recurring && stored !== holiday.date ? holiday.date : null)
    setFormData({
      date: stored,
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
      {editingRecurringOn && (
        <p className="text-xs text-gray-600">
          This holiday repeats every year. You are editing the holiday itself (first dated{' '}
          {formatDate(formData.date)}), so changes apply to every year, including {formatDate(editingRecurringOn)}.
        </p>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div>
          <label htmlFor="holiday-date" className="block text-sm font-medium text-gray-700 mb-1">Date</label>
          <input
            id="holiday-date"
            type="date"
            required
            value={formData.date}
            onChange={(e) => setFormData((p) => ({ ...p, date: e.target.value }))}
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-brand-500 focus:ring-brand-500 focus:outline-none"
          />
        </div>
        <div>
          <label htmlFor="holiday-title" className="block text-sm font-medium text-gray-700 mb-1">Holiday Name</label>
          <input
            id="holiday-title"
            type="text"
            required
            value={formData.title}
            onChange={(e) => setFormData((p) => ({ ...p, title: e.target.value }))}
            placeholder="e.g. New Year's Day"
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-brand-500 focus:ring-brand-500 focus:outline-none"
          />
        </div>
        <div>
          <label htmlFor="holiday-description" className="block text-sm font-medium text-gray-700 mb-1">Description</label>
          <input
            id="holiday-description"
            type="text"
            value={formData.description}
            onChange={(e) => setFormData((p) => ({ ...p, description: e.target.value }))}
            placeholder="Optional"
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-brand-500 focus:ring-brand-500 focus:outline-none"
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
              className="h-4 w-4 rounded border-gray-300 text-brand-600 focus:ring-brand-500"
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
              className="h-4 w-4 rounded border-gray-300 text-brand-600 focus:ring-brand-500"
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
          className="inline-flex items-center rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-brand-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
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

  const addButton = (
    <button
      type="button"
      onClick={() => {
        setShowForm(true)
        setEditingId(null)
        setEditingRecurringOn(null)
        setFormData(EMPTY_FORM)
      }}
      className="inline-flex items-center gap-1.5 rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-brand-700 transition-colors"
    >
      <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
      </svg>
      Add Holiday
    </button>
  )

  return (
    <div className="space-y-8">
      {canViewSource && (
        <HolidaySourceCard source={source} canManage={canEdit} />
      )}

      <div className="bg-white shadow-sm ring-1 ring-gray-900/5 rounded-xl">
        <div className="border-b border-gray-200 px-6 py-4 flex items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Holidays</h2>
            <p className="mt-1 text-sm text-gray-500">
              Manage company holidays. Holiday pay and leave credit conversions are calculated based on the actual hours worked on holiday dates.
            </p>
          </div>
          {canCreate && !showForm && editingId === null && addButton}
        </div>

        <div className="px-6 py-6 space-y-6">
          {/* Year filter */}
          <div className="flex items-center gap-3">
            <span className="text-sm font-medium text-gray-700">Year:</span>
            <div className="flex flex-wrap items-center gap-1">
              {yearOptions.map((year) => (
                <button
                  key={year}
                  type="button"
                  onClick={() => setSelectedYear(year)}
                  aria-pressed={selectedYear === year}
                  className={`px-3 py-1.5 text-sm rounded-md font-medium transition-colors ${
                    selectedYear === year
                      ? 'bg-brand-600 text-white'
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
              <svg className="h-5 w-5 animate-spin text-brand-600" fill="none" viewBox="0 0 24 24">
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
                    {(canEdit || canDelete) && (
                      <th className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-wider text-gray-500">Actions</th>
                    )}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {holidays.map((holiday) => (
                    <tr key={`${holiday.id}-${holiday.date}`} className="hover:bg-gray-50 transition-colors">
                      <td className="px-4 py-3 text-sm text-gray-900 whitespace-nowrap">
                        {formatDate(holiday.date)}
                      </td>
                      <td className="px-4 py-3 text-sm font-medium text-gray-900">
                        <div>{holiday.title}</div>
                        <div className="mt-1 flex flex-wrap gap-1">
                          {holiday.source === 'feed' && (
                            <Pill className="bg-sky-100 text-sky-800" title="Kept up to date from the holiday calendar source">From feed</Pill>
                          )}
                          {holiday.locally_modified && (
                            <Pill className="bg-gray-100 text-gray-700" title="Edited here; the feed will not overwrite it">Edited</Pill>
                          )}
                          {holiday.is_tentative && (
                            <Pill className="bg-yellow-100 text-yellow-800" title="The date is not confirmed yet and may move">Tentative</Pill>
                          )}
                          {holiday.needs_review && (
                            <Pill className="bg-orange-100 text-orange-800" title="The feed did not say whether this is a regular or special holiday. It was saved as regular; edit it to confirm.">Needs review</Pill>
                          )}
                          {holiday.region && (
                            <Pill className="bg-violet-100 text-violet-800" title={holiday.region}>
                              Regional: {holiday.region.split(',').map((c) => regionLabels.get(c) ?? c).join(', ')}
                            </Pill>
                          )}
                        </div>
                      </td>
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
                      {(canEdit || canDelete) && (
                        <td className="px-4 py-3 text-right">
                          <div className="flex items-center justify-end gap-2">
                            {canEdit && (
                              <button
                                type="button"
                                onClick={() => handleEdit(holiday)}
                                className="inline-flex items-center rounded-md p-1.5 text-gray-400 hover:text-brand-600 hover:bg-brand-50 transition-colors"
                                title="Edit"
                                aria-label={`Edit ${holiday.title}`}
                              >
                                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                                  <path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125M18 14v4.75A2.25 2.25 0 0115.75 21H5.25A2.25 2.25 0 013 18.75V8.25A2.25 2.25 0 015.25 6H10" />
                                </svg>
                              </button>
                            )}
                            {canDelete && (deleteConfirmId === holiday.id ? (
                              <div className="flex items-center gap-1">
                                <button
                                  type="button"
                                  onClick={() => deleteMutation.mutate(holiday.id)}
                                  disabled={deleteMutation.isPending}
                                  className="inline-flex items-center rounded-md bg-red-600 px-2 py-1 text-xs font-medium text-white hover:bg-red-700 disabled:opacity-50 transition-colors"
                                >
                                  Delete{holiday.is_recurring ? ' every year' : ''}
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
                                title={holiday.source === 'feed' ? 'Delete (the feed will not add it back)' : 'Delete'}
                                aria-label={`Delete ${holiday.title}`}
                              >
                                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                                  <path strokeLinecap="round" strokeLinejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
                                </svg>
                              </button>
                            ))}
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
                <path strokeLinecap="round" strokeLinejoin="round" d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 012.25-2.25h13.5A2.25 2.25 0 0121 7.5v11.25m-18 0A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75m-18 0v-7.5A2.25 2.25 0 015.25 9h13.5A2.25 2.25 0 0121 11.25v7.5" />
              </svg>
              <h3 className="mt-2 text-sm font-semibold text-gray-900">No holidays for {selectedYear}</h3>
              <p className="mt-1 text-sm text-gray-500">
                Add holidays to configure holiday pay and leave credit rules{canEdit ? ', or sync them from a holiday calendar above' : ''}.
              </p>
              {canCreate && <div className="mt-6">{addButton}</div>}
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

// ── Holiday calendar source ─────────────────────────────────────────────
//
// Holidays move (Eid follows the moon, governments proclaim extra days), so a
// list typed in once is wrong within months. The source card points the
// company at a live feed and keeps it in sync; the admin still decides what
// is kept, edited or deleted.

const OTHER = '__other'
const CUSTOM = '__custom'

function HolidaySourceCard({ source, canManage }: { source?: HolidaySourceConfig; canManage: boolean }) {
  if (!source) return null
  // Re-mount the form whenever the saved source changes, so it starts from
  // what the server has (no state-syncing effect needed).
  const key = `${source.provider}|${source.country_slug}|${source.feed_url}|${source.include_regions.join(',')}|${source.auto_sync}|${source.last_synced_at}`
  return <SourceForm key={key} source={source} canManage={canManage} />
}

function SourceForm({ source, canManage }: { source: HolidaySourceConfig; canManage: boolean }) {
  const queryClient = useQueryClient()
  const { showToast } = useToast()
  const known = new Set(source.countries.map((c) => c.slug))
  const initialSlug = source.country_slug ?? source.suggested_country_slug ?? 'philippines'

  const [choice, setChoice] = useState<string>(
    source.provider === 'ics_url' ? CUSTOM : known.has(initialSlug) ? initialSlug : OTHER,
  )
  const [otherSlug, setOtherSlug] = useState(known.has(initialSlug) ? '' : initialSlug)
  const [feedUrl, setFeedUrl] = useState(source.feed_url ?? '')
  const [regions, setRegions] = useState<string[]>(source.include_regions)
  const [autoSync, setAutoSync] = useState(source.auto_sync)
  const [availableRegions, setAvailableRegions] = useState<HolidayRegion[] | null>(source.discovered_regions)
  const [preview, setPreview] = useState<HolidaySyncResult | null>(null)

  const provider = choice === CUSTOM ? 'ics_url' : 'officeholidays'
  const slug = choice === CUSTOM ? null : choice === OTHER ? otherSlug.trim().toLowerCase() : choice
  const body = {
    provider: provider as 'officeholidays' | 'ics_url',
    country_slug: slug,
    feed_url: provider === 'ics_url' ? feedUrl.trim() : null,
    include_regions: regions,
    auto_sync: autoSync,
  }
  const dirty =
    !source.configured ||
    source.provider !== body.provider ||
    (source.country_slug ?? null) !== body.country_slug ||
    (source.feed_url ?? null) !== (body.feed_url || null) ||
    source.auto_sync !== autoSync ||
    [...source.include_regions].sort().join(',') !== [...regions].sort().join(',')

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['holiday-source'] })
    queryClient.invalidateQueries({ queryKey: ['holidays'] })
    queryClient.invalidateQueries({ queryKey: ['schedule-grid'] })
  }

  const saveIfDirty = async () => {
    if (dirty) await api.setHolidaySource(body)
  }

  const saveMutation = useMutation({
    mutationFn: () => api.setHolidaySource(body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['holiday-source'] })
      showToast('Holiday calendar source saved', 'success')
    },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  const regionsMutation = useMutation({
    mutationFn: async () => {
      await saveIfDirty()
      return api.getHolidayRegions(true)
    },
    onSuccess: (r) => setAvailableRegions(r),
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  const previewMutation = useMutation({
    mutationFn: async () => {
      await saveIfDirty()
      return api.syncHolidays(true)
    },
    onSuccess: (res) => {
      setPreview(res)
      setAvailableRegions(res.regions)
    },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  const syncMutation = useMutation({
    mutationFn: async () => {
      await saveIfDirty()
      return api.syncHolidays(false)
    },
    onSuccess: (res) => {
      setPreview(null)
      refresh()
      const parts = [`${res.added.length} added`, `${res.changed.length} updated`, `${res.removed.length} removed`]
      showToast(`Holidays synced: ${parts.join(', ')}`, 'success')
    },
    onError: (err: Error) => {
      queryClient.invalidateQueries({ queryKey: ['holiday-source'] })
      showToast(err.message, 'error')
    },
  })

  const busy = saveMutation.isPending || previewMutation.isPending || syncMutation.isPending || regionsMutation.isPending
  const canSubmit = provider === 'ics_url' ? feedUrl.trim().startsWith('https://') : !!slug

  const lastSynced = source.last_synced_at ? new Date(source.last_synced_at).toLocaleString() : null
  const label = (c: string) => availableRegions?.find((r) => r.code === c)?.label ?? c

  return (
    <div className="bg-white shadow-sm ring-1 ring-gray-900/5 rounded-xl">
      <div className="border-b border-gray-200 px-6 py-4">
        <h2 className="text-lg font-semibold text-gray-900">Holiday calendar source</h2>
        <p className="mt-1 text-sm text-gray-500">
          Keep public holidays up to date from a live calendar instead of typing them in each year.
          Holidays you add, edit or delete here are never overwritten by it.
        </p>
      </div>
      <div className="px-6 py-6 space-y-5">
        <fieldset disabled={!canManage || busy} className="space-y-5">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label htmlFor="holiday-country" className="block text-sm font-medium text-gray-700 mb-1">Country</label>
              <select
                id="holiday-country"
                value={choice}
                onChange={(e) => { setChoice(e.target.value); setAvailableRegions(null); setRegions([]); setPreview(null) }}
                className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
              >
                {source.countries.map((c) => (
                  <option key={c.slug} value={c.slug}>{c.name}</option>
                ))}
                <option value={OTHER}>Other (type the country as it appears on officeholidays.com)</option>
                <option value={CUSTOM}>Custom iCal URL</option>
              </select>
            </div>
            {choice === OTHER && (
              <div>
                <label htmlFor="holiday-slug" className="block text-sm font-medium text-gray-700 mb-1">Country name in the link</label>
                <input
                  id="holiday-slug"
                  value={otherSlug}
                  onChange={(e) => setOtherSlug(e.target.value)}
                  placeholder="e.g. south-africa"
                  className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                />
                <p className="mt-1 text-xs text-gray-500">
                  The part after /ics/ in officeholidays.com/ics/<span className="font-mono">…</span>
                </p>
              </div>
            )}
            {choice === CUSTOM && (
              <div>
                <label htmlFor="holiday-url" className="block text-sm font-medium text-gray-700 mb-1">iCal address</label>
                <input
                  id="holiday-url"
                  value={feedUrl}
                  onChange={(e) => setFeedUrl(e.target.value)}
                  placeholder="https://…/holidays.ics"
                  className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                />
                <p className="mt-1 text-xs text-gray-500">Must start with https://. Addresses on your private network are refused.</p>
              </div>
            )}
          </div>

          <div>
            <div className="flex items-center justify-between gap-2">
              <span className="block text-sm font-medium text-gray-700">Regional holidays to include</span>
              <button
                type="button"
                onClick={() => regionsMutation.mutate()}
                disabled={!canSubmit}
                className="text-xs font-medium text-brand-700 hover:text-brand-900 disabled:opacity-50"
              >
                {regionsMutation.isPending ? 'Reading the calendar…' : availableRegions ? 'Refresh the list' : 'Load regions from the calendar'}
              </button>
            </div>
            <p className="text-xs text-gray-500 mt-0.5">
              National holidays are always included. Tick the regions where you have staff.
            </p>
            {availableRegions && availableRegions.length === 0 && (
              <p className="mt-2 text-xs text-gray-500">This calendar has no regional holidays.</p>
            )}
            {availableRegions && availableRegions.length > 0 && (
              <div className="mt-2 max-h-48 overflow-y-auto rounded-md border border-gray-200 p-2 grid grid-cols-1 sm:grid-cols-2 gap-1">
                {availableRegions.map((r) => (
                  <label key={r.code} className="flex items-start gap-2 text-xs text-gray-700" title={r.samples.join(', ')}>
                    <input
                      type="checkbox"
                      checked={regions.includes(r.code)}
                      onChange={() => setRegions((prev) => prev.includes(r.code) ? prev.filter((x) => x !== r.code) : [...prev, r.code])}
                      className="mt-0.5 rounded border-gray-300 text-brand-600 focus:ring-brand-500"
                    />
                    <span>
                      {r.label}{r.label !== r.code && !r.code.startsWith('other:') ? ` (${r.code})` : ''}
                      <span className="text-gray-400"> · {r.count} day{r.count !== 1 ? 's' : ''}, e.g. {r.samples[0]}</span>
                    </span>
                  </label>
                ))}
              </div>
            )}
            {!availableRegions && regions.length > 0 && (
              <p className="mt-2 text-xs text-gray-600">Included: {regions.map(label).join(', ')}</p>
            )}
          </div>

          <label className="flex items-start gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={autoSync}
              onChange={(e) => setAutoSync(e.target.checked)}
              className="mt-0.5 h-4 w-4 rounded border-gray-300 text-brand-600 focus:ring-brand-500"
            />
            <span>
              <span className="block text-sm font-medium text-gray-900">Sync automatically every day</span>
              <span className="block text-xs text-gray-500">
                New and moved holidays arrive on their own. Holidays already in the past are never removed.
              </span>
            </span>
          </label>
        </fieldset>

        {canManage && (
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => saveMutation.mutate()}
              disabled={busy || !canSubmit || !dirty}
              className="rounded-md border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
            >
              {saveMutation.isPending ? 'Saving…' : 'Save'}
            </button>
            <button
              type="button"
              onClick={() => previewMutation.mutate()}
              disabled={busy || !canSubmit}
              className="rounded-md border border-brand-300 bg-brand-50 px-3 py-2 text-sm font-medium text-brand-700 hover:bg-brand-100 disabled:opacity-50"
            >
              {previewMutation.isPending ? 'Checking…' : 'Preview sync'}
            </button>
            <button
              type="button"
              onClick={() => syncMutation.mutate()}
              disabled={busy || !canSubmit}
              className="rounded-md bg-brand-600 px-3 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
            >
              {syncMutation.isPending ? 'Syncing…' : 'Sync now'}
            </button>
          </div>
        )}

        {source.configured && (
          <div className="text-xs text-gray-600 space-y-0.5">
            <p>
              Last synced: {lastSynced ?? 'never'}
              {source.last_status === 'ok' && source.last_counts && (
                <> · {source.last_counts.added ?? 0} added, {source.last_counts.changed ?? 0} updated, {source.last_counts.removed ?? 0} removed</>
              )}
            </p>
            {source.last_status === 'error' && source.last_error && (
              <p className="text-red-700">Last attempt failed: {source.last_error}</p>
            )}
          </div>
        )}

        {preview && <SyncPreview result={preview} />}

        <p className="text-xs text-gray-400">
          Holiday data from{' '}
          <a href="https://www.officeholidays.com/countries" target="_blank" rel="noopener noreferrer" className="underline hover:text-gray-600">
            officeholidays.com
          </a>
          {provider === 'ics_url' ? ' or the calendar address you entered' : ''}.
        </p>
      </div>
    </div>
  )
}

function SyncPreview({ result }: { result: HolidaySyncResult }) {
  const sections: { title: string; items: HolidaySyncItem[]; tone: string; note?: string }[] = [
    { title: 'Will be added', items: result.added, tone: 'text-green-800' },
    { title: 'Will be updated', items: result.changed, tone: 'text-blue-800' },
    { title: 'Will be removed', items: result.removed, tone: 'text-red-800', note: 'Future holidays no longer in the calendar.' },
    { title: 'Needs review after syncing', items: result.needs_review, tone: 'text-orange-800', note: 'The calendar does not say whether these are regular or special; they are saved as regular.' },
    { title: 'Left as they are', items: result.skipped, tone: 'text-gray-700' },
  ]
  const nothing = !result.added.length && !result.changed.length && !result.removed.length
  return (
    <div className="rounded-lg border border-gray-200 bg-gray-50 p-4 space-y-3">
      <p className="text-sm font-medium text-gray-900">
        {nothing ? 'Everything is already up to date. Nothing will change.' : 'Preview: nothing has changed yet.'}
      </p>
      {sections.filter((s) => s.items.length > 0).map((s) => (
        <div key={s.title}>
          <p className={`text-xs font-semibold ${s.tone}`}>{s.title} ({s.items.length})</p>
          {s.note && <p className="text-[11px] text-gray-500">{s.note}</p>}
          <ul className="mt-1 max-h-40 overflow-y-auto space-y-0.5 text-xs text-gray-700">
            {s.items.map((i, n) => (
              <li key={`${i.date}-${n}`}>
                <span className="font-mono text-gray-500">{i.date}</span> {i.title}
                {i.before && i.before.title !== i.title ? <span className="text-gray-500"> (was {i.before.title})</span> : null}
                {i.is_special ? ' · special' : ''}{i.is_tentative ? ' · tentative' : ''}
                {i.reason ? <span className="text-gray-500"> · {i.reason}</span> : null}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  )
}
