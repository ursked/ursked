'use client'

import { useEffect, useMemo, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { AppSettings, ShiftStatusType, ScheduleVisibilityGrant, User, OrgTreeNode, OrgTreeResponse } from '@/types'
import { useToast } from '@/components/ui/Toast'
import { CURATED_CURRENCIES, normalizeCurrency, formatMoney } from '@/lib/currency'

const WEEK_START_OPTIONS = [
  { value: 'monday', label: 'Monday' },
  { value: 'sunday', label: 'Sunday' },
  { value: 'saturday', label: 'Saturday' },
]

const SCHEDULE_VISIBILITY_OPTIONS = [
  { value: 'own_node', label: 'Same org unit only', description: 'Employees can only see schedules of people in their own org unit.' },
  { value: 'own_and_children', label: 'Own unit + child units', description: 'Employees can see their own unit and any units below it.' },
  { value: 'own_and_parent', label: 'Own unit + parent unit', description: 'Employees can see their own unit and one level above.' },
  { value: 'all', label: 'Everyone (no restriction)', description: 'All employees can see the full organization schedule.' },
]

/**
 * Numeric setting that commits on blur (or Enter) rather than on every keystroke.
 *
 * These fields feed payroll computation, so keystroke-level saving is wrong twice
 * over: typing "1.25" would PATCH the intermediate values 1 and 1.2, and "1." is
 * not a valid number at all. Hold a local draft, clamp to the field's bounds, and
 * only save when the admin has finished typing and the value actually changed.
 */
function NumberSetting({
  id, label, help, value, min, max, step = 1, disabled, onCommit,
}: {
  id: string
  label: string
  help?: string
  value: number | undefined
  min: number
  max: number
  step?: number
  disabled?: boolean
  onCommit: (n: number) => void
}) {
  const [draft, setDraft] = useState(String(value ?? ''))
  useEffect(() => { setDraft(String(value ?? '')) }, [value])

  const commit = () => {
    const n = Number(draft)
    if (draft.trim() === '' || Number.isNaN(n)) {
      setDraft(String(value ?? ''))   // reject junk, restore the saved value
      return
    }
    const clamped = Math.min(max, Math.max(min, n))
    if (clamped !== n) setDraft(String(clamped))
    if (clamped !== value) onCommit(clamped)
  }

  return (
    <div>
      <label htmlFor={id} className="block text-sm font-medium text-gray-700 mb-1">{label}</label>
      <input
        id={id}
        type="number"
        min={min}
        max={max}
        step={step}
        value={draft}
        disabled={disabled}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.blur() }}
        className="block w-40 rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none disabled:opacity-50"
      />
      {help && <p className="mt-1 text-xs text-gray-500">{help}</p>}
    </div>
  )
}

/** Backend sends "HH:MM:SS"; <input type="time"> wants "HH:MM". */
const toTimeInput = (v?: string | null) => (v ? v.slice(0, 5) : '')

type FlatNode = { id: number; label: string; depth: number }

function flattenNodes(nodes: OrgTreeNode[], depth = 0, acc: FlatNode[] = []): FlatNode[] {
  for (const n of nodes) {
    acc.push({ id: n.id, label: n.name, depth })
    if (n.children?.length) flattenNodes(n.children, depth + 1, acc)
  }
  return acc
}

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

export default function GeneralSettingsTab() {
  const queryClient = useQueryClient()
  const { showToast } = useToast()

  const [showAddForm, setShowAddForm] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [formData, setFormData] = useState<StatusTypeFormData>(EMPTY_FORM)
  const [deleteConfirmId, setDeleteConfirmId] = useState<number | null>(null)
  const [currencyMode, setCurrencyMode] = useState<'curated' | 'custom'>('curated')
  const [customCurrency, setCustomCurrency] = useState('')
  const [showAdvancedVisibility, setShowAdvancedVisibility] = useState(false)
  const [grantUserId, setGrantUserId] = useState<number | ''>('')
  const [grantNodeId, setGrantNodeId] = useState<number | ''>('')
  const [grantIncludeDescendants, setGrantIncludeDescendants] = useState(true)

  const { data: appSettings, isLoading: settingsLoading } = useQuery<AppSettings>({
    queryKey: ['app-settings'],
    queryFn: () => api.getAppSettings(),
  })

  const updateSettingsMutation = useMutation({
    mutationFn: (data: Partial<AppSettings>) => api.updateAppSettings(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['app-settings'] })
    },
  })

  const { data: orgTree } = useQuery<OrgTreeResponse>({
    queryKey: ['org-tree'],
    queryFn: () => api.getOrgTree(),
    staleTime: 300_000,
    enabled: showAdvancedVisibility,
  })

  const { data: usersPage } = useQuery({
    queryKey: ['users', 'for-visibility'],
    queryFn: () => api.getUsers({ per_page: '100' }),
    enabled: showAdvancedVisibility,
  })

  const { data: grants } = useQuery<ScheduleVisibilityGrant[]>({
    queryKey: ['schedule-visibility'],
    queryFn: () => api.getScheduleVisibilityGrants(),
    enabled: showAdvancedVisibility,
  })

  const grantNodeOptions = useMemo(() => (orgTree ? flattenNodes(orgTree.nodes) : []), [orgTree])
  const grantUsers: User[] = usersPage?.items ?? []

  const createGrantMutation = useMutation({
    mutationFn: () =>
      api.createScheduleVisibilityGrant({
        user_id: Number(grantUserId),
        org_node_id: Number(grantNodeId),
        include_descendants: grantIncludeDescendants,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['schedule-visibility'] })
      showToast('Access granted', 'success')
      setGrantUserId('')
      setGrantNodeId('')
      setGrantIncludeDescendants(true)
    },
    onError: () => showToast('Failed to grant access', 'error'),
  })

  const deleteGrantMutation = useMutation({
    mutationFn: (id: number) => api.deleteScheduleVisibilityGrant(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['schedule-visibility'] })
      showToast('Access removed', 'success')
    },
    onError: () => showToast('Failed to remove access', 'error'),
  })

  const canGrant = grantUserId !== '' && grantNodeId !== '' && !createGrantMutation.isPending

  const currentCurrency = normalizeCurrency(appSettings?.currency_code)
  const saveCurrency = (code: string) => {
    const normalized = code.trim().toUpperCase()
    if (!/^[A-Z]{3}$/.test(normalized)) {
      showToast('Enter a valid 3-letter currency code (e.g. USD)', 'error')
      return
    }
    updateSettingsMutation.mutate(
      { currency_code: normalized },
      {
        onSuccess: () => showToast(`Currency set to ${normalized}`, 'success'),
        onError: (err: Error) => showToast(err.message, 'error'),
      },
    )
  }

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
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none" />
          <p className="mt-1 text-xs text-gray-500">Lowercase letters, numbers, and underscores only</p>
        </div>
        <div>
          <label htmlFor="status-label" className="block text-sm font-medium text-gray-700 mb-1">Label</label>
          <input id="status-label" type="text" required value={formData.label}
            onChange={(e) => setFormData((prev) => ({ ...prev, label: e.target.value }))} placeholder="e.g. Sick Leave"
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none" />
        </div>
        <div>
          <label htmlFor="status-short-label" className="block text-sm font-medium text-gray-700 mb-1">Short Label</label>
          <input id="status-short-label" type="text" required value={formData.short_label}
            onChange={(e) => setFormData((prev) => ({ ...prev, short_label: e.target.value }))} placeholder="e.g. SL"
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none" />
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
              className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none" />
          </div>
        </div>
        <div>
          <label htmlFor="status-bg-class" className="block text-sm font-medium text-gray-700 mb-1">Background Class</label>
          <input id="status-bg-class" type="text" value={formData.bg_class}
            onChange={(e) => setFormData((prev) => ({ ...prev, bg_class: e.target.value }))} placeholder="e.g. bg-purple-100"
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none" />
        </div>
        <div>
          <label htmlFor="status-category" className="block text-sm font-medium text-gray-700 mb-1">Category</label>
          <select id="status-category" required value={formData.category}
            onChange={(e) => setFormData((prev) => ({ ...prev, category: e.target.value }))}
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none">
            {CATEGORY_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="status-sort-order" className="block text-sm font-medium text-gray-700 mb-1">Sort Order</label>
          <input id="status-sort-order" type="number" value={formData.sort_order}
            onChange={(e) => setFormData((prev) => ({ ...prev, sort_order: parseInt(e.target.value, 10) || 0 }))}
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none" />
        </div>
      </div>
      <div className="flex items-center gap-3 pt-2">
        <button type="submit" disabled={isMutating}
          className="inline-flex items-center rounded-md bg-purple-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-purple-700 focus:outline-none focus:ring-2 focus:ring-purple-500 focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed transition-colors">
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
    <div className="space-y-8">
      {/* ── Section: Tenant Timezone ─────────────────────────────── */}
      <div className="bg-white shadow-sm ring-1 ring-gray-900/5 rounded-xl">
        <div className="border-b border-gray-200 px-6 py-4">
          <h2 className="text-lg font-semibold text-gray-900">Organization Timezone</h2>
          <p className="mt-1 text-sm text-gray-500">
            All time references across your organization will be based on this timezone.
          </p>
        </div>
        <div className="px-6 py-6">
          {settingsLoading ? (
            <div className="flex items-center gap-3 text-sm text-gray-500">
              <svg className="h-5 w-5 animate-spin text-purple-600" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              Loading...
            </div>
          ) : (
            <div className="max-w-md">
              <label htmlFor="tenant-timezone" className="block text-sm font-medium text-gray-700 mb-1">Timezone</label>
              <select id="tenant-timezone" value={appSettings?.timezone || ''}
                onChange={(e) => updateSettingsMutation.mutate(
                  { timezone: e.target.value },
                  { onSuccess: () => showToast('Organization timezone saved', 'success'),
                    onError: (err: Error) => showToast(err.message, 'error') },
                )}
                disabled={updateSettingsMutation.isPending}
                className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none disabled:opacity-50 disabled:cursor-not-allowed">
                <option value="">Select timezone</option>
                <option value="Africa/Johannesburg">Africa/Johannesburg (SAST, UTC+2)</option>
                <option value="Africa/Cairo">Africa/Cairo (EET, UTC+2)</option>
                <option value="Africa/Lagos">Africa/Lagos (WAT, UTC+1)</option>
                <option value="Africa/Nairobi">Africa/Nairobi (EAT, UTC+3)</option>
                <option value="America/New_York">America/New_York (EST, UTC-5)</option>
                <option value="America/Chicago">America/Chicago (CST, UTC-6)</option>
                <option value="America/Denver">America/Denver (MST, UTC-7)</option>
                <option value="America/Los_Angeles">America/Los_Angeles (PST, UTC-8)</option>
                <option value="America/Sao_Paulo">America/Sao_Paulo (BRT, UTC-3)</option>
                <option value="America/Toronto">America/Toronto (EST, UTC-5)</option>
                <option value="Asia/Dubai">Asia/Dubai (GST, UTC+4)</option>
                <option value="Asia/Kolkata">Asia/Kolkata (IST, UTC+5:30)</option>
                <option value="Asia/Shanghai">Asia/Shanghai (CST, UTC+8)</option>
                <option value="Asia/Singapore">Asia/Singapore (SGT, UTC+8)</option>
                <option value="Asia/Tokyo">Asia/Tokyo (JST, UTC+9)</option>
                <option value="Australia/Sydney">Australia/Sydney (AEST, UTC+10)</option>
                <option value="Europe/London">Europe/London (GMT, UTC+0)</option>
                <option value="Europe/Berlin">Europe/Berlin (CET, UTC+1)</option>
                <option value="Europe/Paris">Europe/Paris (CET, UTC+1)</option>
                <option value="Europe/Moscow">Europe/Moscow (MSK, UTC+3)</option>
                <option value="Pacific/Auckland">Pacific/Auckland (NZST, UTC+12)</option>
                <option value="UTC">UTC (UTC+0)</option>
              </select>
              <p className="mt-2 text-xs text-gray-500">
                {appSettings?.timezone ? `Current timezone: ${appSettings.timezone}` : 'No timezone set. Select one to configure.'}
              </p>
              {updateSettingsMutation.isPending && (
                <p className="mt-2 text-xs text-purple-600 flex items-center gap-1">
                  <svg className="h-3 w-3 animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  Saving...
                </p>
              )}
            </div>
          )}
        </div>
      </div>

      {/* ── Section: Master Currency ──────────────────────────────── */}
      <div className="bg-white shadow-sm ring-1 ring-gray-900/5 rounded-xl">
        <div className="border-b border-gray-200 px-6 py-4">
          <h2 className="text-lg font-semibold text-gray-900">Master Currency</h2>
          <p className="mt-1 text-sm text-gray-500">
            All monetary values — salary grades, payroll, compensation, payslips and exports — are
            denominated in this currency.
          </p>
        </div>
        <div className="px-6 py-6">
          {settingsLoading ? (
            <div className="text-sm text-gray-500">Loading...</div>
          ) : (
            <div className="max-w-md space-y-3">
              <div>
                <label htmlFor="tenant-currency" className="block text-sm font-medium text-gray-700 mb-1">Currency</label>
                <select
                  id="tenant-currency"
                  value={currencyMode === 'custom' ? '__custom__' : currentCurrency}
                  onChange={(e) => {
                    const v = e.target.value
                    if (v === '__custom__') {
                      setCurrencyMode('custom')
                      setCustomCurrency(currentCurrency)
                    } else {
                      setCurrencyMode('curated')
                      saveCurrency(v)
                    }
                  }}
                  disabled={updateSettingsMutation.isPending}
                  className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none disabled:opacity-50"
                >
                  {!CURATED_CURRENCIES.some((c) => c.code === currentCurrency) && currencyMode !== 'custom' && (
                    <option value={currentCurrency}>{currentCurrency}</option>
                  )}
                  {CURATED_CURRENCIES.map((c) => (
                    <option key={c.code} value={c.code}>{c.code} — {c.label}</option>
                  ))}
                  <option value="__custom__">Custom…</option>
                </select>
              </div>

              {currencyMode === 'custom' && (
                <div className="flex items-end gap-2">
                  <div className="flex-1">
                    <label htmlFor="custom-currency" className="block text-sm font-medium text-gray-700 mb-1">
                      Custom ISO 4217 code
                    </label>
                    <input
                      id="custom-currency"
                      type="text"
                      maxLength={3}
                      value={customCurrency}
                      onChange={(e) => setCustomCurrency(e.target.value.toUpperCase())}
                      placeholder="e.g. CHF"
                      className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm uppercase shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none"
                    />
                  </div>
                  <button
                    onClick={() => saveCurrency(customCurrency)}
                    disabled={updateSettingsMutation.isPending}
                    className="rounded-md bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
                  >
                    Save
                  </button>
                  <button
                    onClick={() => { setCurrencyMode('curated'); setCustomCurrency('') }}
                    className="rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-700 hover:bg-gray-50"
                  >
                    Cancel
                  </button>
                </div>
              )}

              <p className="text-xs text-gray-500">
                Current: <span className="font-medium">{currentCurrency}</span> — example:{' '}
                {formatMoney(1234.5, currentCurrency)}. Changing this affects how amounts are
                displayed everywhere; it does not convert existing stored values.
              </p>
            </div>
          )}
        </div>
      </div>

      {/* ── Section: Schedule Settings + Visibility ───────────────── */}
      <div className="bg-white shadow-sm ring-1 ring-gray-900/5 rounded-xl">
        <div className="border-b border-gray-200 px-6 py-4">
          <h2 className="text-lg font-semibold text-gray-900">Schedule Settings</h2>
          <p className="mt-1 text-sm text-gray-500">
            Configure how schedules are displayed across your organization.
          </p>
        </div>
        <div className="px-6 py-6">
          {settingsLoading ? (
            <div className="flex items-center gap-3 text-sm text-gray-500">
              <svg className="h-5 w-5 animate-spin text-purple-600" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              Loading...
            </div>
          ) : (
            <div className="space-y-6">
              <div className="max-w-md">
                <label htmlFor="week-starts-on" className="block text-sm font-medium text-gray-700 mb-1">Week starts on</label>
                <select
                  id="week-starts-on"
                  value={appSettings?.week_starts_on ?? 'monday'}
                  onChange={(e) => updateSettingsMutation.mutate(
                    { week_starts_on: e.target.value as AppSettings['week_starts_on'] },
                    { onSuccess: () => showToast('Week start day saved', 'success') },
                  )}
                  disabled={updateSettingsMutation.isPending}
                  className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none disabled:opacity-50"
                >
                  {WEEK_START_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
                <p className="mt-2 text-xs text-gray-500">
                  This controls the first day of the week in all schedule views.
                </p>
              </div>

              <div className="max-w-md">
                <label htmlFor="schedule-visibility" className="block text-sm font-medium text-gray-700 mb-1">Employee schedule visibility</label>
                <select
                  id="schedule-visibility"
                  value={appSettings?.schedule_employee_visibility ?? 'own_node'}
                  onChange={(e) => updateSettingsMutation.mutate(
                    { schedule_employee_visibility: e.target.value as AppSettings['schedule_employee_visibility'] },
                    { onSuccess: () => showToast('Schedule visibility saved', 'success') },
                  )}
                  disabled={updateSettingsMutation.isPending}
                  className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none disabled:opacity-50"
                >
                  {SCHEDULE_VISIBILITY_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
                <p className="mt-2 text-xs text-gray-500">
                  {SCHEDULE_VISIBILITY_OPTIONS.find((o) => o.value === (appSettings?.schedule_employee_visibility ?? 'own_node'))?.description}{' '}
                  Admin, HR, and Schedule Editor roles always see all employees regardless of this setting.
                </p>
              </div>

              <div className="border-t border-gray-200 pt-5">
                <button
                  type="button"
                  onClick={() => setShowAdvancedVisibility(!showAdvancedVisibility)}
                  className="flex items-center gap-2 text-sm font-medium text-purple-600 hover:text-purple-700 transition-colors"
                >
                  <svg
                    className={`h-4 w-4 transition-transform ${showAdvancedVisibility ? 'rotate-90' : ''}`}
                    fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor"
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
                  </svg>
                  Advanced: per-person visibility grants
                </button>
                <p className="mt-1 text-xs text-gray-500 ml-6">
                  Grant individual people visibility into specific org units beyond what their role allows.
                </p>
              </div>

              {showAdvancedVisibility && (
                <div className="border border-gray-200 rounded-lg p-5 space-y-6 bg-gray-50">
                  <div>
                    <h4 className="text-sm font-semibold text-gray-900">Grant visibility</h4>
                    <p className="mt-1 text-xs text-gray-500">
                      Give a person visibility into a specific part of the organization&apos;s schedule, beyond what their role or team already allows.
                    </p>
                    <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">Person</label>
                        <select
                          className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none"
                          value={grantUserId}
                          onChange={(e) => setGrantUserId(e.target.value ? Number(e.target.value) : '')}
                        >
                          <option value="">Select a person...</option>
                          {grantUsers.map((u) => (
                            <option key={u.id} value={u.id}>
                              {u.first_name} {u.last_name}
                            </option>
                          ))}
                        </select>
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">Org unit</label>
                        <select
                          className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none"
                          value={grantNodeId}
                          onChange={(e) => setGrantNodeId(e.target.value ? Number(e.target.value) : '')}
                        >
                          <option value="">Select a unit...</option>
                          {grantNodeOptions.map((n) => (
                            <option key={n.id} value={n.id}>
                              {'\u00A0'.repeat(n.depth * 2)}{n.label}
                            </option>
                          ))}
                        </select>
                      </div>
                    </div>
                    <label className="mt-3 flex items-center gap-2 text-sm text-gray-700">
                      <input
                        type="checkbox"
                        checked={grantIncludeDescendants}
                        onChange={(e) => setGrantIncludeDescendants(e.target.checked)}
                        className="h-4 w-4 rounded border-gray-300 text-purple-600 focus:ring-purple-500"
                      />
                      Include everything below this unit (its whole subtree)
                    </label>
                    <div className="mt-4">
                      <button
                        type="button"
                        onClick={() => createGrantMutation.mutate()}
                        disabled={!canGrant}
                        className="rounded-md bg-purple-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                      >
                        {createGrantMutation.isPending ? 'Granting...' : 'Grant access'}
                      </button>
                    </div>
                  </div>

                  <div className="border-t border-gray-200 pt-5">
                    <h4 className="text-sm font-semibold text-gray-900">Current grants</h4>
                    <div className="mt-3 overflow-x-auto">
                      <table className="min-w-full divide-y divide-gray-200 text-sm">
                        <thead>
                          <tr className="text-left text-xs uppercase tracking-wide text-gray-500">
                            <th className="py-2 pr-4">Person</th>
                            <th className="py-2 pr-4">Unit</th>
                            <th className="py-2 pr-4">Scope</th>
                            <th className="py-2 pr-4"></th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-100">
                          {(grants ?? []).length === 0 && (
                            <tr>
                              <td colSpan={4} className="py-6 text-center text-gray-400">
                                No visibility grants yet.
                              </td>
                            </tr>
                          )}
                          {(grants ?? []).map((g) => (
                            <tr key={g.id}>
                              <td className="py-2 pr-4 text-gray-700">{g.user_name ?? `#${g.user_id}`}</td>
                              <td className="py-2 pr-4 text-gray-700">{g.org_node_name ?? `#${g.org_node_id}`}</td>
                              <td className="py-2 pr-4 text-gray-500">
                                {g.include_descendants ? 'Unit + subtree' : 'Unit only'}
                              </td>
                              <td className="py-2 pr-4 text-right">
                                <button
                                  type="button"
                                  onClick={() => deleteGrantMutation.mutate(g.id)}
                                  disabled={deleteGrantMutation.isPending}
                                  className="text-sm font-medium text-red-600 hover:text-red-700 disabled:opacity-50"
                                >
                                  Remove
                                </button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                </div>
              )}

              {updateSettingsMutation.isPending && (
                <p className="text-xs text-purple-600 flex items-center gap-1">
                  <svg className="h-3 w-3 animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  Saving...
                </p>
              )}
            </div>
          )}
        </div>
      </div>

      {/* ── Section: Payroll & Premium Rates ─────────────────────── */}
      <div className="bg-white shadow-sm ring-1 ring-gray-900/5 rounded-xl">
        <div className="border-b border-gray-200 px-6 py-4">
          <h2 className="text-lg font-semibold text-gray-900">Payroll &amp; Premium Rates</h2>
          <p className="mt-1 text-sm text-gray-500">
            The rates used to compute pay. Set these to match your jurisdiction and any
            collective agreement — the shipped values are Philippine statutory defaults
            and are almost certainly not correct for your organization.
          </p>
        </div>
        <div className="px-6 py-6">
          {settingsLoading ? (
            <div className="text-sm text-gray-500">Loading...</div>
          ) : (
            <div className="space-y-6">
              <NumberSetting
                id="working-days-per-month"
                label="Working days per month"
                help="Divides a monthly salary grade to derive the daily rate, which in turn derives the hourly rate."
                value={appSettings?.working_days_per_month}
                min={1} max={31}
                disabled={updateSettingsMutation.isPending}
                onCommit={(n) => updateSettingsMutation.mutate(
                  { working_days_per_month: n },
                  { onSuccess: () => showToast('Working days per month saved', 'success'),
                    onError: (err: Error) => showToast(err.message, 'error') },
                )}
              />

              <div className="border-t border-gray-200 pt-5 space-y-4">
                <h3 className="text-sm font-semibold text-gray-900">Night differential</h3>
                <NumberSetting
                  id="night-diff-multiplier"
                  label="Night differential multiplier"
                  help="1.0 means no premium. 1.10 pays a 10% premium on hours inside the night window."
                  value={appSettings?.night_diff_multiplier}
                  min={1} max={10} step={0.01}
                  disabled={updateSettingsMutation.isPending}
                  onCommit={(n) => updateSettingsMutation.mutate(
                    { night_diff_multiplier: n },
                    { onSuccess: () => showToast('Night differential saved', 'success'),
                      onError: (err: Error) => showToast(err.message, 'error') },
                  )}
                />
                <div className="flex flex-wrap items-end gap-4">
                  <div>
                    <label htmlFor="night-start" className="block text-sm font-medium text-gray-700 mb-1">Night window starts</label>
                    <input
                      id="night-start" type="time"
                      value={toTimeInput(appSettings?.night_shift_start)}
                      disabled={updateSettingsMutation.isPending}
                      onChange={(e) => updateSettingsMutation.mutate(
                        { night_shift_start: e.target.value || null },
                        { onSuccess: () => showToast('Night window saved', 'success'),
                          onError: (err: Error) => showToast(err.message, 'error') },
                      )}
                      className="block w-40 rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none disabled:opacity-50"
                    />
                  </div>
                  <div>
                    <label htmlFor="night-end" className="block text-sm font-medium text-gray-700 mb-1">Night window ends</label>
                    <input
                      id="night-end" type="time"
                      value={toTimeInput(appSettings?.night_shift_end)}
                      disabled={updateSettingsMutation.isPending}
                      onChange={(e) => updateSettingsMutation.mutate(
                        { night_shift_end: e.target.value || null },
                        { onSuccess: () => showToast('Night window saved', 'success'),
                          onError: (err: Error) => showToast(err.message, 'error') },
                      )}
                      className="block w-40 rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none disabled:opacity-50"
                    />
                  </div>
                </div>
                {(!appSettings?.night_shift_start || !appSettings?.night_shift_end) && (
                  <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3">
                    <p className="text-xs text-amber-800">
                      No night window is set, so the night differential is never applied no
                      matter what multiplier is configured. Set both a start and an end time
                      to enable it. The window may cross midnight (e.g. 22:00 to 06:00).
                    </p>
                  </div>
                )}
              </div>

              <div className="border-t border-gray-200 pt-5 space-y-4">
                <h3 className="text-sm font-semibold text-gray-900">Holiday premiums</h3>
                <NumberSetting
                  id="holiday-mult"
                  label="Regular holiday multiplier"
                  help="Applied to hours worked on a regular holiday. 2.0 pays double."
                  value={appSettings?.holiday_worked_multiplier}
                  min={1} max={10} step={0.01}
                  disabled={updateSettingsMutation.isPending}
                  onCommit={(n) => updateSettingsMutation.mutate(
                    { holiday_worked_multiplier: n },
                    { onSuccess: () => showToast('Holiday multiplier saved', 'success'),
                      onError: (err: Error) => showToast(err.message, 'error') },
                  )}
                />
                <NumberSetting
                  id="special-holiday-mult"
                  label="Special holiday multiplier"
                  help="Applied to hours worked on a special (non-regular) holiday."
                  value={appSettings?.special_holiday_worked_multiplier}
                  min={1} max={10} step={0.01}
                  disabled={updateSettingsMutation.isPending}
                  onCommit={(n) => updateSettingsMutation.mutate(
                    { special_holiday_worked_multiplier: n },
                    { onSuccess: () => showToast('Special holiday multiplier saved', 'success'),
                      onError: (err: Error) => showToast(err.message, 'error') },
                  )}
                />
              </div>

              <div className="rounded-lg border border-blue-200 bg-blue-50 p-4">
                <p className="text-xs text-blue-800">
                  Premiums are paid as <span className="font-medium">hours &times; hourly rate &times; (multiplier &minus; 1)</span> on
                  top of base pay, so a multiplier of 1.0 means no premium. Changes apply to
                  payroll computed from now on; they do not retroactively alter payroll
                  periods that have already been generated.
                </p>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── Section: Schedule Enforcement ────────────────────────── */}
      <div className="bg-white shadow-sm ring-1 ring-gray-900/5 rounded-xl">
        <div className="border-b border-gray-200 px-6 py-4">
          <h2 className="text-lg font-semibold text-gray-900">Schedule Enforcement</h2>
          <p className="mt-1 text-sm text-gray-500">
            Working-time limits checked when shifts are created. Set either to 0 to disable
            that rule.
          </p>
        </div>
        <div className="px-6 py-6">
          {settingsLoading ? (
            <div className="text-sm text-gray-500">Loading...</div>
          ) : (
            <div className="space-y-6">
              <NumberSetting
                id="max-consecutive-work-days"
                label="Maximum consecutive work days"
                help="Blocks scheduling a run of work days longer than this. 0 = no limit."
                value={appSettings?.max_consecutive_work_days}
                min={0} max={31}
                disabled={updateSettingsMutation.isPending}
                onCommit={(n) => updateSettingsMutation.mutate(
                  { max_consecutive_work_days: n },
                  { onSuccess: () => showToast('Consecutive work day limit saved', 'success'),
                    onError: (err: Error) => showToast(err.message, 'error') },
                )}
              />
              <NumberSetting
                id="min-rest-days-per-week"
                label="Minimum rest days per week"
                help="Requires at least this many rest days in any rolling 7-day window. 0 = no requirement."
                value={appSettings?.min_rest_days_per_week}
                min={0} max={7}
                disabled={updateSettingsMutation.isPending}
                onCommit={(n) => updateSettingsMutation.mutate(
                  { min_rest_days_per_week: n },
                  { onSuccess: () => showToast('Rest day requirement saved', 'success'),
                    onError: (err: Error) => showToast(err.message, 'error') },
                )}
              />
            </div>
          )}
        </div>
      </div>

      {/* ── Section: Employee Data Retention ─────────────────────── */}
      <div className="bg-white shadow-sm ring-1 ring-gray-900/5 rounded-xl">
        <div className="border-b border-gray-200 px-6 py-4">
          <h2 className="text-lg font-semibold text-gray-900">Employee Data Retention</h2>
          <p className="mt-1 text-sm text-gray-500">
            Configure how long separated (resigned/terminated) employee data is retained and when it is excluded from analytics.
          </p>
        </div>
        <div className="px-6 py-6">
          {settingsLoading ? (
            <div className="flex items-center gap-3 text-sm text-gray-500">
              <svg className="h-5 w-5 animate-spin text-purple-600" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              Loading settings...
            </div>
          ) : (
            <div className="space-y-6">
              <div className="max-w-md">
                <label className="block text-sm font-medium text-gray-700 mb-2">Data Retention Policy</label>
                <div className="space-y-3">
                  <label className="flex items-start gap-3 cursor-pointer">
                    <input
                      type="radio"
                      name="data-retention"
                      checked={appSettings?.data_retention_days === null || appSettings?.data_retention_days === undefined}
                      onChange={() => updateSettingsMutation.mutate({ data_retention_days: null })}
                      className="mt-1 h-4 w-4 text-purple-600 border-gray-300 focus:ring-purple-500"
                    />
                    <div>
                      <p className="text-sm font-medium text-gray-900">Keep data forever</p>
                      <p className="text-xs text-gray-500">Separated employee records are never deleted. They can still be filtered on the employee page.</p>
                    </div>
                  </label>
                  <label className="flex items-start gap-3 cursor-pointer">
                    <input
                      type="radio"
                      name="data-retention"
                      checked={appSettings?.data_retention_days !== null && appSettings?.data_retention_days !== undefined}
                      onChange={() => updateSettingsMutation.mutate({ data_retention_days: 365 })}
                      className="mt-1 h-4 w-4 text-purple-600 border-gray-300 focus:ring-purple-500"
                    />
                    <div>
                      <p className="text-sm font-medium text-gray-900">Flag for deletion after a set period</p>
                      <p className="text-xs text-gray-500">Records past this age are reported as due for deletion. Removal is performed manually by an administrator — nothing is deleted automatically.</p>
                    </div>
                  </label>
                </div>

                {appSettings?.data_retention_days !== null && appSettings?.data_retention_days !== undefined && (
                  <div className="mt-3 ml-7">
                    <label htmlFor="retention-days" className="block text-sm font-medium text-gray-700 mb-1">
                      Days before permanent deletion
                    </label>
                    <input
                      id="retention-days"
                      type="number"
                      min={1}
                      max={3650}
                      value={appSettings?.data_retention_days ?? 365}
                      onChange={(e) => {
                        const val = parseInt(e.target.value, 10);
                        if (val > 0) updateSettingsMutation.mutate({ data_retention_days: val });
                      }}
                      className="block w-32 rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none"
                    />
                    <p className="mt-1 text-xs text-gray-500">
                      Records are flagged as due for deletion {appSettings?.data_retention_days} day{appSettings?.data_retention_days !== 1 ? 's' : ''} after the separation date.
                    </p>
                  </div>
                )}
              </div>

              <div className="max-w-md">
                <label htmlFor="analytics-exclusion" className="block text-sm font-medium text-gray-700 mb-1">
                  Analytics Exclusion Period
                </label>
                <div className="flex items-center gap-2">
                  <input
                    id="analytics-exclusion"
                    type="number"
                    min={0}
                    max={365}
                    value={appSettings?.analytics_exclusion_days ?? 0}
                    onChange={(e) => {
                      const val = parseInt(e.target.value, 10);
                      if (val >= 0) updateSettingsMutation.mutate({ analytics_exclusion_days: val });
                    }}
                    className="block w-32 rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none"
                  />
                  <span className="text-sm text-gray-500">days after separation</span>
                </div>
                <p className="mt-1.5 text-xs text-gray-500">
                  Separated employees will still be included in analytics for this many days after their separation date.
                  After this period, they are excluded from computed metrics. Set to 0 to exclude immediately.
                </p>
              </div>

              <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
                <div className="flex gap-3">
                  <svg className="w-5 h-5 text-blue-600 flex-shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  <div className="text-sm text-blue-800">
                    <p className="font-medium mb-1">How it works</p>
                    <ul className="list-disc list-inside space-y-1 text-xs text-blue-700">
                      <li>When an employee is marked as resigned or terminated, their account is deactivated.</li>
                      <li>Their historical data (schedules, attendance, leave records) remains intact for record-keeping.</li>
                      <li>After the analytics exclusion period, they are no longer included in computed analytics and reports.</li>
                      <li>The retention period flags records as due for deletion. This build does not delete anything automatically — an administrator must remove records deliberately.</li>
                      <li>Separated employees can be reinstated at any time.</li>
                    </ul>
                  </div>
                </div>
              </div>

              {updateSettingsMutation.isPending && (
                <p className="text-xs text-purple-600 flex items-center gap-1">
                  <svg className="h-3 w-3 animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  Saving...
                </p>
              )}
            </div>
          )}
        </div>
      </div>

      {/* ── Section: Shift Status Types ──────────────────────────── */}
      <div className="bg-white shadow-sm ring-1 ring-gray-900/5 rounded-xl">
        <div className="border-b border-gray-200 px-6 py-4 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Shift Status Types</h2>
            <p className="mt-1 text-sm text-gray-500">Define the status types available for scheduling shifts.</p>
          </div>
          {!showAddForm && editingId === null && (
            <button type="button" onClick={() => { setShowAddForm(true); setEditingId(null); setFormData(EMPTY_FORM) }}
              className="inline-flex items-center gap-1.5 rounded-md bg-purple-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-purple-700 focus:outline-none focus:ring-2 focus:ring-purple-500 focus:ring-offset-2 transition-colors">
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
              </svg>
              Add Status Type
            </button>
          )}
        </div>

        <div className="px-6 py-6 space-y-6">
          {(showAddForm || editingId !== null) && renderStatusTypeForm()}

          {statusTypesLoading ? (
            <div className="flex items-center gap-3 text-sm text-gray-500">
              <svg className="h-5 w-5 animate-spin text-purple-600" fill="none" viewBox="0 0 24 24">
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
                    <th className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-wider text-gray-500">Actions</th>
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
                          <span className="inline-flex items-center rounded-full bg-purple-100 text-purple-800 px-2.5 py-0.5 text-xs font-medium">System</span>
                        ) : (
                          <span className="text-sm text-gray-400">--</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <div className="flex items-center justify-end gap-2">
                          <button type="button" onClick={() => handleEditClick(st)}
                            className="inline-flex items-center rounded-md p-1.5 text-gray-400 hover:text-purple-600 hover:bg-purple-50 transition-colors" title="Edit">
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
              <p className="mt-1 text-sm text-gray-500">Get started by adding a new status type.</p>
              <div className="mt-6">
                <button type="button" onClick={() => { setShowAddForm(true); setEditingId(null); setFormData(EMPTY_FORM) }}
                  className="inline-flex items-center gap-1.5 rounded-md bg-purple-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-purple-700 focus:outline-none focus:ring-2 focus:ring-purple-500 focus:ring-offset-2 transition-colors">
                  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
                  </svg>
                  Add Status Type
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
