'use client'

import { useMemo, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { AppSettings, ScheduleVisibilityGrant, User, OrgTreeNode, OrgTreeResponse } from '@/types'
import { useToast } from '@/components/ui/Toast'
import { CURATED_CURRENCIES, normalizeCurrency, formatMoney } from '@/lib/currency'
import NumberSetting from './NumberSetting'

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

type FlatNode = { id: number; label: string; depth: number }

function flattenNodes(nodes: OrgTreeNode[], depth = 0, acc: FlatNode[] = []): FlatNode[] {
  for (const n of nodes) {
    acc.push({ id: n.id, label: n.name, depth })
    if (n.children?.length) flattenNodes(n.children, depth + 1, acc)
  }
  return acc
}

export default function GeneralSettingsTab() {
  const queryClient = useQueryClient()
  const { showToast } = useToast()

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

      {/* "Payroll & Premium Rates" is now Finances -> Pay rules, under the
          finances permission: editing settings must not change what everyone
          is paid. The settings API refuses those fields. */}

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

              <div className="border-t border-gray-200 pt-5">
                <label className="flex items-start gap-3 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={!!appSettings?.auto_create_holiday_off}
                    disabled={updateSettingsMutation.isPending}
                    onChange={(e) => updateSettingsMutation.mutate(
                      { auto_create_holiday_off: e.target.checked },
                      { onSuccess: () => showToast('Holiday setting saved', 'success'),
                        onError: (err: Error) => showToast(err.message, 'error') },
                    )}
                    className="mt-0.5 h-4 w-4 rounded text-purple-600 border-gray-300 focus:ring-purple-500"
                  />
                  <div>
                    <p className="text-sm font-medium text-gray-900">
                      Mark employees off automatically on holidays
                    </p>
                    <p className="text-xs text-gray-500 mt-0.5">
                      When a date is marked as a holiday, employees with nothing scheduled
                      that day get a &quot;Holiday Off&quot; entry. Anyone who already has a
                      shift, a rest day, or approved leave is left untouched. Leave this off
                      if your organization operates on holidays.
                    </p>
                  </div>
                </label>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── Section: Working Hours (area S) ─────────────────────── */}
      <div className="bg-white shadow-sm ring-1 ring-gray-900/5 rounded-xl">
        <div className="border-b border-gray-200 px-6 py-4">
          <h2 className="text-lg font-semibold text-gray-900">Working Hours</h2>
          <p className="mt-1 text-sm text-gray-500">
            Limits checked whenever a shift is created, edited, dragged, copied, swapped or
            changed by an approved request. A shift that breaks one is flagged, and whoever
            schedules it can still save it on purpose. Set a limit to 0 to turn it off.
          </p>
        </div>
        <div className="px-6 py-6">
          {settingsLoading ? (
            <div className="text-sm text-gray-500">Loading...</div>
          ) : (
            <div className="space-y-6">
              <NumberSetting
                id="max-work-hours-per-day"
                label="Maximum hours of work in a day"
                help="All of a day's shifts together, split shifts included. 0 = no limit."
                value={appSettings?.max_work_hours_per_day}
                min={0} max={24} step={0.5}
                disabled={updateSettingsMutation.isPending}
                onCommit={(n) => updateSettingsMutation.mutate(
                  { max_work_hours_per_day: n },
                  { onSuccess: () => showToast('Daily hour limit saved', 'success'),
                    onError: (err: Error) => showToast(err.message, 'error') },
                )}
              />
              <NumberSetting
                id="max-work-hours-per-week"
                label="Maximum hours of work in a week"
                help="Counted over the week as it starts in Schedule Settings. 0 = no limit."
                value={appSettings?.max_work_hours_per_week}
                min={0} max={168} step={0.5}
                disabled={updateSettingsMutation.isPending}
                onCommit={(n) => updateSettingsMutation.mutate(
                  { max_work_hours_per_week: n },
                  { onSuccess: () => showToast('Weekly hour limit saved', 'success'),
                    onError: (err: Error) => showToast(err.message, 'error') },
                )}
              />
              <NumberSetting
                id="min-rest-hours"
                label="Minimum rest between working days (hours)"
                help="From the end of one day's last shift to the start of the next day's first, overnight shifts included. The break inside a split shift does not count. 0 = no minimum."
                value={appSettings?.min_rest_hours_between_shifts}
                min={0} max={48} step={0.5}
                disabled={updateSettingsMutation.isPending}
                onCommit={(n) => updateSettingsMutation.mutate(
                  { min_rest_hours_between_shifts: n },
                  { onSuccess: () => showToast('Rest requirement saved', 'success'),
                    onError: (err: Error) => showToast(err.message, 'error') },
                )}
              />
              <label className="flex items-start gap-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={!!appSettings?.check_overlapping_shifts}
                  disabled={updateSettingsMutation.isPending}
                  onChange={(e) => updateSettingsMutation.mutate(
                    { check_overlapping_shifts: e.target.checked },
                    { onSuccess: () => showToast('Overlap check saved', 'success'),
                      onError: (err: Error) => showToast(err.message, 'error') },
                  )}
                  className="mt-0.5 h-4 w-4 rounded text-purple-600 border-gray-300 focus:ring-purple-500"
                />
                <div>
                  <p className="text-sm font-medium text-gray-900">Flag overlapping shifts</p>
                  <p className="text-xs text-gray-500 mt-0.5">
                    Warn when two shifts of the same person overlap, for example the two parts
                    of a split shift, or a night shift running into the next morning&apos;s.
                  </p>
                </div>
              </label>
            </div>
          )}
        </div>
      </div>

      {/* ── Section: Time Clock ──────────────────────────────────── */}
      <div className="bg-white shadow-sm ring-1 ring-gray-900/5 rounded-xl">
        <div className="border-b border-gray-200 px-6 py-4">
          <h2 className="text-lg font-semibold text-gray-900">Time Clock</h2>
          <p className="mt-1 text-sm text-gray-500">
            Let employees clock themselves in and out, optionally recording where they
            were. Off by default.
          </p>
        </div>
        <div className="px-6 py-6 space-y-5">
          <label className="flex items-start gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={!!appSettings?.timeclock_enabled}
              disabled={updateSettingsMutation.isPending}
              onChange={(e) => updateSettingsMutation.mutate(
                { timeclock_enabled: e.target.checked },
                { onSuccess: () => showToast('Time clock setting saved', 'success'),
                  onError: (err: Error) => showToast(err.message, 'error') },
              )}
              className="mt-0.5 h-4 w-4 rounded text-purple-600 border-gray-300 focus:ring-purple-500"
            />
            <div>
              <p className="text-sm font-medium text-gray-900">Enable the time clock</p>
              <p className="text-xs text-gray-500 mt-0.5">
                Adds a Time Clock page where employees record their own hours as they
                work. Their attendance record is rebuilt from those punches, so
                overtime and tardiness are calculated exactly as they are for hours
                entered by hand.
              </p>
            </div>
          </label>

          <label className="flex items-start gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={!!appSettings?.timeclock_require_location}
              disabled={updateSettingsMutation.isPending || !appSettings?.timeclock_enabled}
              onChange={(e) => updateSettingsMutation.mutate(
                { timeclock_require_location: e.target.checked },
                { onSuccess: () => showToast('Location setting saved', 'success'),
                  onError: (err: Error) => showToast(err.message, 'error') },
              )}
              className="mt-0.5 h-4 w-4 rounded text-purple-600 border-gray-300 focus:ring-purple-500"
            />
            <div>
              <p className="text-sm font-medium text-gray-900">Ask for location on each punch</p>
              <p className="text-xs text-gray-500 mt-0.5">
                Records the device&apos;s coordinates with each clock-in and clock-out, and
                stores them as personal data. A punch is <strong>never refused</strong> because
                a location is missing &mdash; it is recorded and flagged for review instead.
                Browsers only share location over HTTPS, so on a plain-HTTP address every
                punch is marked as having no location.
              </p>
            </div>
          </label>

          <NumberSetting
            id="timeclock_location_grace_minutes"
            label="Minutes to add a missing location"
            help="After a punch with no location, how long the employee may still attach one. The result is always marked as added later, never as captured at the time. 0 disables it."
            value={appSettings?.timeclock_location_grace_minutes}
            min={0} max={1440}
            disabled={updateSettingsMutation.isPending || !appSettings?.timeclock_enabled}
            onCommit={(n) => updateSettingsMutation.mutate(
              { timeclock_location_grace_minutes: n },
              { onSuccess: () => showToast('Grace window saved', 'success'),
                onError: (err: Error) => showToast(err.message, 'error') },
            )}
          />

          <NumberSetting
            id="timeclock_default_radius_m"
            label="Default site radius (metres)"
            help="How close to a work site still counts as being there, for sites that do not set their own. Indoor GPS is often 100-200m out, so a generous radius avoids wrongly flagging people."
            value={appSettings?.timeclock_default_radius_m}
            min={10} max={100000}
            disabled={updateSettingsMutation.isPending || !appSettings?.timeclock_enabled}
            onCommit={(n) => updateSettingsMutation.mutate(
              { timeclock_default_radius_m: n },
              { onSuccess: () => showToast('Default radius saved', 'success'),
                onError: (err: Error) => showToast(err.message, 'error') },
            )}
          />
        </div>
      </div>

      {/* ── Section: Leave Days and Approvals (area L) ────────────── */}
      <div className="bg-white shadow-sm ring-1 ring-gray-900/5 rounded-xl">
        <div className="border-b border-gray-200 px-6 py-4">
          <h2 className="text-lg font-semibold text-gray-900">Leave Days and Approvals</h2>
          <p className="mt-1 text-sm text-gray-500">
            How leave days are counted when someone has nothing on the schedule, and how long a request may
            wait for an approver before the app follows up.
          </p>
        </div>
        <div className="px-6 py-6 space-y-6">
          <fieldset>
            <legend className="text-sm font-medium text-gray-900">Normal working days</legend>
            <p className="mt-0.5 text-xs text-gray-500">
              A leave day counts when the employee is scheduled to work that day, and never on a holiday.
              For days with nothing on the schedule, these are the days that count.
            </p>
            <div className="mt-2 flex flex-wrap gap-2">
              {['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map((label, day) => {
                const week = appSettings?.work_week_days ?? [0, 1, 2, 3, 4]
                const on = week.includes(day)
                return (
                  <button
                    key={label}
                    type="button"
                    aria-pressed={on}
                    disabled={updateSettingsMutation.isPending || (on && week.length === 1)}
                    onClick={() => updateSettingsMutation.mutate(
                      { work_week_days: on ? week.filter((d) => d !== day) : [...week, day].sort() },
                      { onSuccess: () => showToast('Working days saved', 'success'),
                        onError: (err: Error) => showToast(err.message, 'error') },
                    )}
                    className={`min-w-[3rem] rounded-full border px-3 py-1.5 text-sm ${
                      on ? 'border-purple-600 bg-purple-50 text-purple-700' : 'border-gray-300 text-gray-600 hover:bg-gray-50'
                    } disabled:opacity-60`}
                  >
                    {label}
                  </button>
                )
              })}
            </div>
          </fieldset>

          <NumberSetting
            id="leave_reminder_after_days"
            label="Remind the approver after (days)"
            help="Once a request has waited this many days for the same approver, they get a reminder each day until they decide."
            value={appSettings?.leave_reminder_after_days}
            min={1} max={60}
            disabled={updateSettingsMutation.isPending}
            onCommit={(n) => updateSettingsMutation.mutate(
              { leave_reminder_after_days: n },
              { onSuccess: () => showToast('Reminder timing saved', 'success'),
                onError: (err: Error) => showToast(err.message, 'error') },
            )}
          />
          <NumberSetting
            id="leave_escalate_after_days"
            label="Pass it on after (days, 0 = never)"
            help="After this many days without a decision, the request moves to the approver's own manager, or to an administrator if they have none. Requests still waiting after their last day expire."
            value={appSettings?.leave_escalate_after_days}
            min={0} max={90}
            disabled={updateSettingsMutation.isPending}
            onCommit={(n) => updateSettingsMutation.mutate(
              { leave_escalate_after_days: n },
              { onSuccess: () => showToast('Escalation timing saved', 'success'),
                onError: (err: Error) => showToast(err.message, 'error') },
            )}
          />

          <div className="space-y-3 border-t border-gray-200 pt-5">
            {([
              ['notify_on_leave_request', 'Tell approvers about requests', 'New requests, changes, cancellations, reminders and reassignments, in the app and by email.'],
              ['notify_on_leave_approval', 'Tell employees about decisions', 'Approvals, rejections, reversals, overrides and expiry, in the app and by email.'],
            ] as const).map(([key, title, help]) => (
              <label key={key} className="flex items-start gap-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={appSettings ? appSettings[key] !== false : true}
                  disabled={updateSettingsMutation.isPending}
                  onChange={(e) => updateSettingsMutation.mutate(
                    { [key]: e.target.checked } as Partial<AppSettings>,
                    { onSuccess: () => showToast('Notification setting saved', 'success'),
                      onError: (err: Error) => showToast(err.message, 'error') },
                  )}
                  className="mt-0.5 h-4 w-4 rounded text-purple-600 border-gray-300 focus:ring-purple-500"
                />
                <div>
                  <p className="text-sm font-medium text-gray-900">{title}</p>
                  <p className="text-xs text-gray-500 mt-0.5">{help}</p>
                </div>
              </label>
            ))}
          </div>
        </div>
      </div>

      {/* ── Section: Attendance Automation (area F) ───────────────── */}
      <div className="bg-white shadow-sm ring-1 ring-gray-900/5 rounded-xl">
        <div className="border-b border-gray-200 px-6 py-4">
          <h2 className="text-lg font-semibold text-gray-900">Attendance Automation</h2>
          <p className="mt-1 text-sm text-gray-500">
            What happens when someone forgets to clock out, or does not turn up for a published shift.
            Both apply only to companies using the time clock.
          </p>
        </div>
        <div className="px-6 py-6 space-y-6">
          <NumberSetting
            id="auto_clockout_after_hours"
            label="Close a forgotten clock-in after the shift ends (hours)"
            help="The day is closed at the shift's scheduled end, not at the moment it is noticed, and marked for review."
            value={appSettings?.auto_clockout_after_hours}
            min={0.5} max={24} step={0.5}
            disabled={updateSettingsMutation.isPending}
            onCommit={(n) => updateSettingsMutation.mutate(
              { auto_clockout_after_hours: n },
              { onSuccess: () => showToast('Automatic clock-out saved', 'success'),
                onError: (err: Error) => showToast(err.message, 'error') },
            )}
          />
          <NumberSetting
            id="auto_clockout_unscheduled_hours"
            label="With no shift, close it after (hours from clock-in)"
            help="The day is then closed one normal working day after the clock-in."
            value={appSettings?.auto_clockout_unscheduled_hours}
            min={1} max={24}
            disabled={updateSettingsMutation.isPending}
            onCommit={(n) => updateSettingsMutation.mutate(
              { auto_clockout_unscheduled_hours: n },
              { onSuccess: () => showToast('Automatic clock-out saved', 'success'),
                onError: (err: Error) => showToast(err.message, 'error') },
            )}
          />
          <label className="flex items-start gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={appSettings ? appSettings.auto_mark_absent !== false : true}
              disabled={updateSettingsMutation.isPending}
              onChange={(e) => updateSettingsMutation.mutate(
                { auto_mark_absent: e.target.checked },
                { onSuccess: () => showToast('Absence setting saved', 'success'),
                  onError: (err: Error) => showToast(err.message, 'error') },
              )}
              className="mt-0.5 h-4 w-4 rounded text-purple-600 border-gray-300 focus:ring-purple-500"
            />
            <div>
              <p className="text-sm font-medium text-gray-900">Mark no-shows absent</p>
              <p className="text-xs text-gray-500 mt-0.5">
                A published shift that ends with no clock-in, no approved leave and no holiday is recorded as absent.
              </p>
            </div>
          </label>
          <NumberSetting
            id="auto_absent_after_minutes"
            label="Wait after the shift starts (minutes)"
            help="Nobody is marked absent before this long after their shift was due to start, nor before it ends."
            value={appSettings?.auto_absent_after_minutes}
            min={15} max={1440}
            disabled={updateSettingsMutation.isPending || appSettings?.auto_mark_absent === false}
            onCommit={(n) => updateSettingsMutation.mutate(
              { auto_absent_after_minutes: n },
              { onSuccess: () => showToast('Absence setting saved', 'success'),
                onError: (err: Error) => showToast(err.message, 'error') },
            )}
          />
        </div>
      </div>

      {/* ── Section: Notifications and Defaults (area A) ──────────── */}
      <div className="bg-white shadow-sm ring-1 ring-gray-900/5 rounded-xl">
        <div className="border-b border-gray-200 px-6 py-4">
          <h2 className="text-lg font-semibold text-gray-900">Notifications and Defaults</h2>
          <p className="mt-1 text-sm text-gray-500">
            Schedule notifications, and the values used when nothing more specific is set up.
          </p>
        </div>
        <div className="px-6 py-6 space-y-6">
          <label className="flex items-start gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={appSettings ? appSettings.notify_on_schedule_change !== false : true}
              disabled={updateSettingsMutation.isPending}
              onChange={(e) => updateSettingsMutation.mutate(
                { notify_on_schedule_change: e.target.checked },
                { onSuccess: () => showToast('Notification setting saved', 'success'),
                  onError: (err: Error) => showToast(err.message, 'error') },
              )}
              className="mt-0.5 h-4 w-4 rounded text-purple-600 border-gray-300 focus:ring-purple-500"
            />
            <div>
              <p className="text-sm font-medium text-gray-900">Email employees when their schedule changes</p>
              <p className="text-xs text-gray-500 mt-0.5">
                When a schedule is published, or a published shift is changed or removed, the people affected get an email.
                They are always told in the app, whatever this says.
              </p>
            </div>
          </label>
          <NumberSetting
            id="default_leave_days"
            label="Leave days per year when no leave policy applies"
            help="Each active leave type gives this many days to anyone not covered by a leave policy. Leave policies set their own amounts."
            value={appSettings?.default_leave_days}
            min={0} max={365}
            disabled={updateSettingsMutation.isPending}
            onCommit={(n) => updateSettingsMutation.mutate(
              { default_leave_days: n },
              { onSuccess: () => showToast('Default leave days saved', 'success'),
                onError: (err: Error) => showToast(err.message, 'error') },
            )}
          />
          <NumberSetting
            id="default_shift_duration_hours"
            label="Length of a working day (hours)"
            help="Used when an employee's schedule format does not say: to work out daily and hourly pay rates, undertime, and the time clock's expected hours."
            value={appSettings?.default_shift_duration_hours}
            min={1} max={24}
            disabled={updateSettingsMutation.isPending}
            onCommit={(n) => updateSettingsMutation.mutate(
              { default_shift_duration_hours: n },
              { onSuccess: () => showToast('Working day length saved', 'success'),
                onError: (err: Error) => showToast(err.message, 'error') },
            )}
          />
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
                      <li>The retention period flags records as due for deletion: <span className="font-medium">Settings → Data &amp; backups</span> lists what is due, by type. Nothing is deleted automatically — an administrator must remove records deliberately.</li>
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
    </div>
  )
}
