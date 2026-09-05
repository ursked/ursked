'use client'

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { useCurrency } from '@/lib/currency'
import { DataSource, DataExportConfig, CustomColumn, PreviewResponse, ScheduledExport } from '@/types'

const SOURCE_GROUPS = [
  {
    label: 'Employee Profiles',
    keys: ['employees'],
  },
  {
    label: 'Time & Attendance',
    keys: ['schedules', 'attendance', 'overtime_logs', 'tardiness_records'],
  },
  {
    label: 'Leave Management',
    keys: ['leave_applications', 'leave_credit_adjustments'],
  },
  {
    label: 'Payroll & Compensation',
    keys: ['payroll_items', 'salary_grades'],
  },
  {
    label: 'Organization',
    keys: ['organization'],
  },
]

export default function DataTab() {
  const queryClient = useQueryClient()

  // ── State ──────────────────────────────────────────────────────
  const [selectedConfigId, setSelectedConfigId] = useState<number | null>(null)
  const [configName, setConfigName] = useState('')
  const [configDescription, setConfigDescription] = useState('')
  const [selectedSources, setSelectedSources] = useState<string[]>([])
  const [selectedColumns, setSelectedColumns] = useState<string[]>([]) // namespaced: "src.col"
  const [customColumns, setCustomColumns] = useState<CustomColumn[]>([])
  const [newCustomName, setNewCustomName] = useState('')
  const [newCustomFormula, setNewCustomFormula] = useState('')
  const [nameFormat, setNameFormat] = useState<string>('first_last')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [preview, setPreview] = useState<PreviewResponse | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [exportLoading, setExportLoading] = useState(false)
  const [error, setError] = useState('')
  const [successMsg, setSuccessMsg] = useState('')
  const [showHowItWorks, setShowHowItWorks] = useState(false)

  // ── Queries ────────────────────────────────────────────────────
  const { data: sources = [] } = useQuery<DataSource[]>({
    queryKey: ['data-sources'],
    queryFn: () => api.getDataSources(),
  })

  // Salary/pay data may only be exported by an approved salary-viewer — mirrors
  // the server-side gate. When the current user is not a viewer, salary sources
  // and columns are shown but locked, with a prompt to request access.
  const { data: salaryStatus } = useQuery({
    queryKey: ['my-salary-status'],
    queryFn: () => api.getMySalaryStatus(),
  })
  const isSalaryViewer = salaryStatus?.is_viewer ?? false
  const { code: currencyCode } = useCurrency()

  function isSalarySource(srcKey: string) {
    return getSourceMeta(srcKey)?.is_salary ?? false
  }
  function isSalaryColumn(srcKey: string, colKey: string) {
    if (isSalarySource(srcKey)) return true
    return getColumnsForSource(srcKey).find((c) => c.key === colKey)?.is_salary ?? false
  }
  // A source is locked if it exposes salary data and the user isn't a viewer.
  function isSourceLocked(srcKey: string) {
    return !isSalaryViewer && isSalarySource(srcKey)
  }

  const { data: configs = [] } = useQuery<DataExportConfig[]>({
    queryKey: ['export-configs'],
    queryFn: () => api.getExportConfigs(),
  })

  // ── Mutations ──────────────────────────────────────────────────
  const saveMutation = useMutation({
    mutationFn: (data: Parameters<typeof api.createExportConfig>[0]) => {
      if (selectedConfigId) {
        return api.updateExportConfig(selectedConfigId, data as Record<string, unknown>)
      }
      return api.createExportConfig(data)
    },
    onSuccess: (saved) => {
      queryClient.invalidateQueries({ queryKey: ['export-configs'] })
      setSelectedConfigId(saved.id)
      setSuccessMsg('Configuration saved successfully')
      setError('')
      setTimeout(() => setSuccessMsg(''), 3000)
    },
    onError: (err: Error) => {
      setError(err.message)
      setSuccessMsg('')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.deleteExportConfig(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['export-configs'] })
      resetForm()
      setSuccessMsg('Configuration deleted')
      setTimeout(() => setSuccessMsg(''), 3000)
    },
    onError: (err: Error) => setError(err.message),
  })

  // ── Schedule state ────────────────────────────────────────────
  const [showScheduleForm, setShowScheduleForm] = useState(false)
  const [editingScheduleId, setEditingScheduleId] = useState<number | null>(null)
  const [scheduleConfigId, setScheduleConfigId] = useState<number | ''>('')
  const [scheduleType, setScheduleType] = useState<'daily' | 'weekly' | 'monthly'>('daily')
  const [scheduleDay, setScheduleDay] = useState<number>(0)
  const [scheduleTime, setScheduleTime] = useState('08:00')
  const [scheduleEmails, setScheduleEmails] = useState('')
  const [scheduleActive, setScheduleActive] = useState(true)
  const [scheduleError, setScheduleError] = useState('')
  const [scheduleSuccess, setScheduleSuccess] = useState('')

  // ── Schedule queries ─────────────────────────────────────────
  const { data: schedules = [] } = useQuery<ScheduledExport[]>({
    queryKey: ['scheduled-exports'],
    queryFn: () => api.getScheduledExports(),
  })

  // ── Schedule mutations ───────────────────────────────────────
  const createScheduleMutation = useMutation({
    mutationFn: (data: { export_config_id: number; schedule_type: string; schedule_day?: number; schedule_time: string; recipient_emails: string[]; is_active?: boolean }) => {
      if (editingScheduleId) {
        return api.updateScheduledExport(editingScheduleId, data as Record<string, unknown>)
      }
      return api.createScheduledExport(data)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['scheduled-exports'] })
      resetScheduleForm()
      setScheduleSuccess(editingScheduleId ? 'Schedule updated' : 'Schedule created')
      setTimeout(() => setScheduleSuccess(''), 3000)
    },
    onError: (err: Error) => setScheduleError(err.message),
  })

  const deleteScheduleMutation = useMutation({
    mutationFn: (id: number) => api.deleteScheduledExport(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['scheduled-exports'] })
      setScheduleSuccess('Schedule deleted')
      setTimeout(() => setScheduleSuccess(''), 3000)
    },
    onError: (err: Error) => setScheduleError(err.message),
  })

  const runNowMutation = useMutation({
    mutationFn: (id: number) => api.runScheduledExportNow(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['scheduled-exports'] })
      setScheduleSuccess('Export triggered — emails will be sent shortly')
      setTimeout(() => setScheduleSuccess(''), 4000)
    },
    onError: (err: Error) => setScheduleError(err.message),
  })

  const toggleScheduleActiveMutation = useMutation({
    mutationFn: ({ id, is_active }: { id: number; is_active: boolean }) =>
      api.updateScheduledExport(id, { is_active }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['scheduled-exports'] })
    },
    onError: (err: Error) => setScheduleError(err.message),
  })

  function resetScheduleForm() {
    setShowScheduleForm(false)
    setEditingScheduleId(null)
    setScheduleConfigId('')
    setScheduleType('daily')
    setScheduleDay(0)
    setScheduleTime('08:00')
    setScheduleEmails('')
    setScheduleActive(true)
    setScheduleError('')
  }

  function editSchedule(s: ScheduledExport) {
    setEditingScheduleId(s.id)
    setScheduleConfigId(s.export_config_id)
    setScheduleType(s.schedule_type)
    setScheduleDay(s.schedule_day ?? 0)
    setScheduleTime(s.schedule_time)
    setScheduleEmails(s.recipient_emails.join(', '))
    setScheduleActive(s.is_active)
    setShowScheduleForm(true)
    setScheduleError('')
  }

  function handleSaveSchedule() {
    if (!scheduleConfigId) {
      setScheduleError('Select a saved export configuration')
      return
    }
    const emails = scheduleEmails.split(',').map((e) => e.trim()).filter(Boolean)
    if (emails.length === 0) {
      setScheduleError('Enter at least one recipient email')
      return
    }
    setScheduleError('')
    createScheduleMutation.mutate({
      export_config_id: scheduleConfigId as number,
      schedule_type: scheduleType,
      schedule_day: scheduleType !== 'daily' ? scheduleDay : undefined,
      schedule_time: scheduleTime,
      recipient_emails: emails,
      is_active: scheduleActive,
    })
  }

  const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

  // ── Multi-source helpers ──────────────────────────────────────
  const isMultiSource = selectedSources.length > 1

  function getSourceMeta(key: string) {
    return sources.find((s) => s.key === key)
  }

  function getColumnsForSource(sourceKey: string) {
    return getSourceMeta(sourceKey)?.columns || []
  }

  function getSelectedColumnsForSource(sourceKey: string) {
    return selectedColumns.filter((c) => c.startsWith(sourceKey + '.'))
  }

  function getColumnLabel(namespacedCol: string) {
    if (!namespacedCol.includes('.')) return namespacedCol
    const [src, col] = namespacedCol.split('.', 2)
    const srcMeta = getSourceMeta(src)
    const colDef = srcMeta?.columns.find((c) => c.key === col)
    if (!colDef) return namespacedCol
    if (isMultiSource) return `${srcMeta?.label} > ${colDef.label}`
    return colDef.label
  }

  // ── Helpers ────────────────────────────────────────────────────
  function resetForm() {
    setSelectedConfigId(null)
    setConfigName('')
    setConfigDescription('')
    setSelectedSources([])
    setSelectedColumns([])
    setCustomColumns([])
    setNameFormat('first_last')
    setDateFrom('')
    setDateTo('')
    setPreview(null)
    setError('')
    setSuccessMsg('')
  }

  function loadConfig(config: DataExportConfig) {
    setSelectedConfigId(config.id)
    setConfigName(config.name)
    setConfigDescription(config.description || '')
    setCustomColumns(config.custom_columns || [])
    setNameFormat(config.name_format || 'first_last')
    setDateFrom('')
    setDateTo('')
    setPreview(null)
    setError('')
    setSuccessMsg('')

    if (config.data_source === 'multi') {
      // Multi-source: parse sources from namespaced columns
      const srcs = Array.from(new Set(config.columns.filter((c) => c.includes('.')).map((c) => c.split('.')[0])))
      setSelectedSources(srcs)
      setSelectedColumns(config.columns)
    } else {
      // Single source: namespace the columns internally
      setSelectedSources([config.data_source])
      setSelectedColumns(config.columns.map((c) => `${config.data_source}.${c}`))
    }
  }

  function toggleSource(key: string) {
    // Block selecting a salary source without viewer enrollment.
    if (isSourceLocked(key) && !selectedSources.includes(key)) {
      setError('Salary data export requires an approved salary-viewer enrollment.')
      return
    }
    if (selectedSources.includes(key)) {
      // Remove source and its columns
      setSelectedSources((prev) => prev.filter((s) => s !== key))
      setSelectedColumns((prev) => prev.filter((c) => !c.startsWith(key + '.')))
    } else {
      setSelectedSources((prev) => [...prev, key])
    }
    setPreview(null)
  }

  function toggleColumn(sourceKey: string, colKey: string) {
    if (!isSalaryViewer && isSalaryColumn(sourceKey, colKey)) {
      setError('Salary data export requires an approved salary-viewer enrollment.')
      return
    }
    const ns = `${sourceKey}.${colKey}`
    setSelectedColumns((prev) =>
      prev.includes(ns) ? prev.filter((c) => c !== ns) : [...prev, ns]
    )
    setPreview(null)
  }

  function selectAllColumnsForSource(sourceKey: string) {
    // "Select All" never pulls in salary columns the user isn't enrolled to see.
    const allCols = getColumnsForSource(sourceKey)
      .filter((c) => isSalaryViewer || !isSalaryColumn(sourceKey, c.key))
      .map((c) => `${sourceKey}.${c.key}`)
    setSelectedColumns((prev) => {
      const withoutSrc = prev.filter((c) => !c.startsWith(sourceKey + '.'))
      return [...withoutSrc, ...allCols]
    })
    setPreview(null)
  }

  function clearColumnsForSource(sourceKey: string) {
    setSelectedColumns((prev) => prev.filter((c) => !c.startsWith(sourceKey + '.')))
    setPreview(null)
  }

  function addCustomColumn() {
    if (!newCustomName.trim() || !newCustomFormula.trim()) return
    setCustomColumns((prev) => [...prev, { name: newCustomName.trim(), formula: newCustomFormula.trim() }])
    setNewCustomName('')
    setNewCustomFormula('')
    setPreview(null)
  }

  function removeCustomColumn(idx: number) {
    setCustomColumns((prev) => prev.filter((_, i) => i !== idx))
    setPreview(null)
  }

  // ── Build request payload ─────────────────────────────────────
  function buildRequestPayload() {
    const common = {
      custom_columns: customColumns.length > 0 ? customColumns : undefined,
      name_format: nameFormat !== 'first_last' ? nameFormat : undefined,
      date_from: dateFrom || undefined,
      date_to: dateTo || undefined,
    }
    if (isMultiSource) {
      return {
        data_source: 'multi',
        columns: selectedColumns,
        ...common,
      }
    }
    // Single source: strip namespace prefix
    const src = selectedSources[0]
    return {
      data_source: src,
      columns: selectedColumns.map((c) => c.replace(src + '.', '')),
      ...common,
    }
  }

  // ── Actions ────────────────────────────────────────────────────
  async function handlePreview() {
    if (selectedSources.length === 0 || selectedColumns.length === 0) {
      setError('Select at least one data source and one column')
      return
    }
    setPreviewLoading(true)
    setError('')
    try {
      const result = await api.previewExport(buildRequestPayload())
      setPreview(result)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Preview failed')
    } finally {
      setPreviewLoading(false)
    }
  }

  async function handleExport() {
    if (selectedSources.length === 0 || selectedColumns.length === 0) {
      setError('Select at least one data source and one column')
      return
    }
    setExportLoading(true)
    setError('')
    try {
      const blob = await api.exportData(buildRequestPayload())
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      const filename = isMultiSource ? 'multi_source_export.csv' : `${selectedSources[0]}_export.csv`
      a.download = filename
      document.body.appendChild(a)
      a.click()
      a.remove()
      window.URL.revokeObjectURL(url)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Export failed')
    } finally {
      setExportLoading(false)
    }
  }

  function handleSave() {
    if (!configName.trim()) {
      setError('Enter a configuration name')
      return
    }
    if (selectedSources.length === 0 || selectedColumns.length === 0) {
      setError('Select at least one data source and one column')
      return
    }
    const payload = buildRequestPayload()
    saveMutation.mutate({
      name: configName.trim(),
      description: configDescription.trim() || undefined,
      ...payload,
      name_format: nameFormat !== 'first_last' ? nameFormat : undefined,
    })
  }

  const totalSelectedColumns = selectedColumns.length

  // Date-based sources that support date range filtering
  const DATE_SOURCES = ['schedules', 'attendance', 'overtime_logs', 'tardiness_records']
  const hasDateSources = selectedSources.some((s) => DATE_SOURCES.includes(s))

  const NAME_FORMAT_OPTIONS = [
    { value: 'first_last', label: 'First Last', example: 'John Smith' },
    { value: 'last_first', label: 'Last, First', example: 'Smith, John' },
    { value: 'last_first_upper', label: 'LAST, FIRST', example: 'SMITH, JOHN' },
    { value: 'first_last_upper', label: 'FIRST LAST', example: 'JOHN SMITH' },
  ]

  // ── Render ─────────────────────────────────────────────────────
  return (
    <div className="space-y-6">
      {/* Saved Configs Bar */}
      <div className="flex items-center gap-3 flex-wrap">
        <label className="text-sm font-medium text-gray-700">Saved Exports:</label>
        <select
          className="rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:border-purple-500 focus:ring-purple-500"
          value={selectedConfigId ?? ''}
          onChange={(e) => {
            const id = e.target.value ? Number(e.target.value) : null
            if (id) {
              const cfg = configs.find((c) => c.id === id)
              if (cfg) loadConfig(cfg)
            } else {
              resetForm()
            }
          }}
        >
          <option value="">-- New Export --</option>
          {configs.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
        <button
          onClick={resetForm}
          className="rounded-md bg-purple-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-purple-700"
        >
          + New Export
        </button>
        {selectedConfigId && (
          <button
            onClick={() => {
              if (confirm('Delete this saved configuration?')) {
                deleteMutation.mutate(selectedConfigId)
              }
            }}
            className="rounded-md bg-red-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-700"
          >
            Delete
          </button>
        )}
      </div>

      {/* Salary-access notice */}
      {!isSalaryViewer && (
        <div className="rounded-md bg-amber-50 border border-amber-200 p-3">
          <p className="text-sm text-amber-800">
            <span className="font-medium">Salary data is locked.</span> Exporting pay figures
            (Payroll, Salary Grades, and overtime/tardiness amounts) requires an approved
            salary-viewer enrollment — being an admin is not enough. Request access from{' '}
            <span className="font-medium">Finances → Salary Access</span>.
          </p>
        </div>
      )}

      {/* Messages */}
      {error && (
        <div className="rounded-md bg-red-50 p-3">
          <p className="text-sm text-red-700">{error}</p>
        </div>
      )}
      {successMsg && (
        <div className="rounded-md bg-green-50 p-3">
          <p className="text-sm text-green-700">{successMsg}</p>
        </div>
      )}

      {/* Step 1: Export Name */}
      <div>
        <h3 className="text-sm font-semibold text-gray-900 mb-2 flex items-center gap-2">
          <span className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-purple-100 text-purple-700 text-xs font-bold">1</span>
          Name Your Export
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Export Name</label>
            <input
              type="text"
              value={configName}
              onChange={(e) => setConfigName(e.target.value)}
              placeholder="e.g. Monthly Attendance Report"
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-purple-500 focus:ring-purple-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Description (optional)</label>
            <input
              type="text"
              value={configDescription}
              onChange={(e) => setConfigDescription(e.target.value)}
              placeholder="Brief description..."
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-purple-500 focus:ring-purple-500"
            />
          </div>
        </div>
      </div>

      {/* Step 2: Data Sources */}
      <div>
        <h3 className="text-sm font-semibold text-gray-900 mb-2 flex items-center gap-2">
          <span className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-purple-100 text-purple-700 text-xs font-bold">2</span>
          Select Data Sources
          {selectedSources.length > 0 && (
            <span className="text-xs font-normal text-gray-500">
              ({selectedSources.length} selected)
            </span>
          )}
        </h3>
        <p className="text-xs text-gray-500 mb-3">
          Choose one or more data sources. When combining multiple sources, data is automatically linked by Employee ID.
        </p>

        <div className="space-y-3">
          {SOURCE_GROUPS.map((group) => {
            const groupSources = group.keys.filter((k) => sources.some((s) => s.key === k))
            if (groupSources.length === 0) return null
            return (
              <div key={group.label}>
                <p className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-1.5">{group.label}</p>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
                  {groupSources.map((srcKey) => {
                    const src = getSourceMeta(srcKey)
                    if (!src) return null
                    const isOn = selectedSources.includes(srcKey)
                    const colCount = getSelectedColumnsForSource(srcKey).length
                    const locked = isSourceLocked(srcKey)
                    const salary = isSalarySource(srcKey)
                    return (
                      <button
                        key={srcKey}
                        type="button"
                        onClick={() => toggleSource(srcKey)}
                        disabled={locked}
                        title={locked ? 'Salary data — requires salary-viewer enrollment' : undefined}
                        className={`text-left p-3 rounded-lg border-2 transition-all ${
                          locked
                            ? 'border-gray-200 bg-gray-50 opacity-60 cursor-not-allowed'
                            : isOn
                            ? 'border-purple-500 bg-purple-50 ring-1 ring-purple-500'
                            : 'border-gray-200 bg-white hover:border-gray-300'
                        }`}
                      >
                        <div className="flex items-center justify-between gap-1">
                          <span className={`text-sm font-medium ${isOn ? 'text-purple-900' : 'text-gray-900'}`}>
                            {src.label}
                          </span>
                          <span className="flex items-center gap-1">
                            {salary && (
                              <span className="inline-flex items-center px-1.5 py-0.5 rounded-full text-[10px] font-semibold bg-amber-100 text-amber-800">
                                {locked ? 'Salary · locked' : 'Salary'}
                              </span>
                            )}
                            {isOn && colCount > 0 && (
                              <span className="inline-flex items-center px-1.5 py-0.5 rounded-full text-xs font-medium bg-purple-200 text-purple-800">
                                {colCount} col{colCount !== 1 ? 's' : ''}
                              </span>
                            )}
                          </span>
                        </div>
                        <p className="text-xs text-gray-500 mt-0.5">{src.description}</p>
                        <p className="text-xs text-gray-400 mt-0.5">{src.columns.length} columns available</p>
                      </button>
                    )
                  })}
                </div>
              </div>
            )
          })}
        </div>

        {isMultiSource && (
          <div className="mt-3 rounded-md bg-blue-50 border border-blue-200 p-3">
            <p className="text-xs text-blue-800">
              <span className="font-medium">Multi-source mode:</span> Data from {selectedSources.length} sources will be merged using Employee ID as the common link.
              {selectedSources.some((s) => ['schedules', 'attendance', 'overtime_logs', 'tardiness_records'].includes(s)) &&
                selectedSources.filter((s) => ['schedules', 'attendance', 'overtime_logs', 'tardiness_records'].includes(s)).length >= 2 &&
                ' Daily sources (Attendance, Schedules, Overtime, Tardiness) are also matched by Date.'}
            </p>
          </div>
        )}
      </div>

      {/* Export Options: Name Format & Date Range */}
      {selectedSources.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Name Format */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Employee Name Format</label>
            <select
              value={nameFormat}
              onChange={(e) => { setNameFormat(e.target.value); setPreview(null) }}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-purple-500 focus:ring-purple-500"
            >
              {NAME_FORMAT_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label} — e.g. {opt.example}
                </option>
              ))}
            </select>
            <p className="mt-1 text-xs text-gray-500">Applies to all employee name fields in the export</p>
          </div>

          {/* Date Range Filter */}
          {hasDateSources && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Date Range Filter</label>
              <div className="flex items-center gap-2">
                <input
                  type="date"
                  value={dateFrom}
                  onChange={(e) => { setDateFrom(e.target.value); setPreview(null) }}
                  className="flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-purple-500 focus:ring-purple-500"
                />
                <span className="text-sm text-gray-500">to</span>
                <input
                  type="date"
                  value={dateTo}
                  onChange={(e) => { setDateTo(e.target.value); setPreview(null) }}
                  className="flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-purple-500 focus:ring-purple-500"
                />
                {(dateFrom || dateTo) && (
                  <button
                    onClick={() => { setDateFrom(''); setDateTo(''); setPreview(null) }}
                    className="text-xs text-gray-500 hover:text-gray-700 whitespace-nowrap"
                  >
                    Clear
                  </button>
                )}
              </div>
              <p className="mt-1 text-xs text-gray-500">
                Filters daily sources ({selectedSources.filter((s) => DATE_SOURCES.includes(s)).map((s) => getSourceMeta(s)?.label).join(', ')}) by date
              </p>
            </div>
          )}
        </div>
      )}

      {/* Step 3: Column Selection */}
      {selectedSources.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-gray-900 mb-2 flex items-center gap-2">
            <span className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-purple-100 text-purple-700 text-xs font-bold">3</span>
            Choose Columns
            {totalSelectedColumns > 0 && (
              <span className="text-xs font-normal text-gray-500">
                ({totalSelectedColumns} selected)
              </span>
            )}
          </h3>

          <div className="space-y-3">
            {selectedSources.map((srcKey) => {
              const src = getSourceMeta(srcKey)
              if (!src) return null
              const srcCols = src.columns
              const selectedForSrc = getSelectedColumnsForSource(srcKey)

              return (
                <div key={srcKey} className="rounded-lg border border-gray-200 p-4">
                  <div className="flex items-center justify-between mb-3">
                    <h4 className="text-sm font-semibold text-gray-800">
                      {src.label}
                      <span className="ml-2 text-xs font-normal text-gray-500">
                        {selectedForSrc.length}/{srcCols.length} selected
                      </span>
                    </h4>
                    <div className="flex gap-2">
                      <button
                        onClick={() => selectAllColumnsForSource(srcKey)}
                        className="text-xs text-purple-600 hover:text-purple-800 font-medium"
                      >
                        Select All
                      </button>
                      <span className="text-xs text-gray-500">|</span>
                      <button
                        onClick={() => clearColumnsForSource(srcKey)}
                        className="text-xs text-gray-500 hover:text-gray-700 font-medium"
                      >
                        Clear
                      </button>
                    </div>
                  </div>
                  <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2">
                    {srcCols.map((col) => {
                      const ns = `${srcKey}.${col.key}`
                      const checked = selectedColumns.includes(ns)
                      const salaryCol = isSalaryColumn(srcKey, col.key)
                      const colLocked = salaryCol && !isSalaryViewer
                      return (
                        <label
                          key={col.key}
                          title={colLocked ? 'Salary data — requires salary-viewer enrollment' : undefined}
                          className={`flex items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors ${
                            colLocked
                              ? 'bg-gray-50 text-gray-400 border border-transparent opacity-60 cursor-not-allowed'
                              : checked
                              ? 'bg-purple-50 text-purple-900 border border-purple-200 cursor-pointer'
                              : 'bg-gray-50 text-gray-700 border border-transparent hover:bg-gray-100 cursor-pointer'
                          }`}
                        >
                          <input
                            type="checkbox"
                            checked={checked}
                            disabled={colLocked}
                            onChange={() => toggleColumn(srcKey, col.key)}
                            className="rounded border-gray-300 text-purple-600 focus:ring-purple-500 disabled:opacity-50"
                          />
                          <span className="truncate">{col.label}</span>
                          {salaryCol && col.type === 'number' && (
                            <span className="text-[10px] font-semibold text-amber-700" title={`Salary data (${currencyCode})`}>
                              {currencyCode}
                            </span>
                          )}
                          {salaryCol && col.type !== 'number' && (
                            <span className="text-[10px] font-semibold text-amber-700" title="Salary data">•</span>
                          )}
                          <span className="ml-auto text-xs text-gray-400">{col.type}</span>
                        </label>
                      )
                    })}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Step 4: Custom Columns */}
      {selectedSources.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-gray-900 mb-2 flex items-center gap-2">
            <span className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-purple-100 text-purple-700 text-xs font-bold">4</span>
            Custom Columns (optional)
          </h3>
          <div className="rounded-lg border border-gray-200 p-4">
            {customColumns.length > 0 && (
              <div className="space-y-2 mb-3">
                {customColumns.map((cc, idx) => (
                  <div key={idx} className="flex items-center gap-2 bg-gray-50 rounded-md px-3 py-2">
                    <span className="text-sm font-medium text-gray-800 min-w-[120px]">{cc.name}</span>
                    <code className="text-xs text-gray-600 bg-gray-100 px-2 py-0.5 rounded flex-1 truncate">
                      {cc.formula}
                    </code>
                    <button
                      onClick={() => removeCustomColumn(idx)}
                      className="text-red-500 hover:text-red-700 text-sm"
                    >
                      Remove
                    </button>
                  </div>
                ))}
              </div>
            )}

            <div className="flex flex-col sm:flex-row gap-2">
              <input
                type="text"
                value={newCustomName}
                onChange={(e) => setNewCustomName(e.target.value)}
                placeholder="Column name"
                className="rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:border-purple-500 focus:ring-purple-500 sm:w-40"
              />
              <input
                type="text"
                value={newCustomFormula}
                onChange={(e) => setNewCustomFormula(e.target.value)}
                placeholder='Formula, e.g. CONCAT({first_name}, " ", {last_name})'
                className="rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:border-purple-500 focus:ring-purple-500 flex-1"
                onKeyDown={(e) => {
                  if (e.key === 'Enter') addCustomColumn()
                }}
              />
              <button
                onClick={addCustomColumn}
                disabled={!newCustomName.trim() || !newCustomFormula.trim()}
                className="rounded-md bg-gray-800 px-4 py-1.5 text-sm font-medium text-white hover:bg-gray-900 disabled:bg-gray-300 disabled:cursor-not-allowed whitespace-nowrap"
              >
                + Add
              </button>
            </div>
            <div className="mt-2 text-xs text-gray-500">
              <p>
                Reference columns with <code className="bg-gray-100 px-1 rounded">{'{column_key}'}</code>.
                Available functions: <code className="bg-gray-100 px-1 rounded">CONCAT</code>,{' '}
                <code className="bg-gray-100 px-1 rounded">UPPER</code>,{' '}
                <code className="bg-gray-100 px-1 rounded">LOWER</code>,{' '}
                <code className="bg-gray-100 px-1 rounded">IF</code>,{' '}
                <code className="bg-gray-100 px-1 rounded">ROUND</code>,{' '}
                <code className="bg-gray-100 px-1 rounded">FORMAT_SCHEDULE</code>,{' '}
                <code className="bg-gray-100 px-1 rounded">YEAR</code>,{' '}
                <code className="bg-gray-100 px-1 rounded">MONTH</code>,{' '}
                math operators: <code className="bg-gray-100 px-1 rounded">+ - * /</code>
              </p>
              <p className="mt-1">
                A cell showing <code className="bg-gray-100 px-1 rounded">#ERROR</code> means the
                formula couldn&apos;t be evaluated for that row — check the column keys in{' '}
                <code className="bg-gray-100 px-1 rounded">{'{...}'}</code> and the function
                arguments. Referencing a salary column keeps the export salary-gated.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Action buttons */}
      {selectedSources.length > 0 && selectedColumns.length > 0 && (
        <div className="flex gap-3 flex-wrap">
          <button
            onClick={handlePreview}
            disabled={previewLoading}
            className="rounded-md bg-white px-4 py-2 text-sm font-medium text-gray-700 border border-gray-300 hover:bg-gray-50 disabled:opacity-50"
          >
            {previewLoading ? 'Loading...' : 'Preview'}
          </button>
          <button
            onClick={handleExport}
            disabled={exportLoading}
            className="rounded-md bg-green-600 px-4 py-2 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
          >
            {exportLoading ? 'Exporting...' : 'Export CSV'}
          </button>
          <button
            onClick={handleSave}
            disabled={saveMutation.isPending}
            className="rounded-md bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
          >
            {saveMutation.isPending ? 'Saving...' : selectedConfigId ? 'Update Configuration' : 'Save Configuration'}
          </button>
        </div>
      )}

      {/* Preview Table */}
      {preview && (
        <div className="rounded-lg border border-gray-200 overflow-hidden">
          <div className="bg-gray-50 px-4 py-2 border-b border-gray-200">
            <h3 className="text-sm font-semibold text-gray-900">
              Preview ({preview.rows.length} of {preview.total} rows)
              {isMultiSource && (
                <span className="ml-2 text-xs font-normal text-gray-500">
                  — merged from {selectedSources.length} sources
                </span>
              )}
            </h3>
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  {preview.columns.map((col) => (
                    <th
                      key={col}
                      className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider whitespace-nowrap"
                    >
                      {getColumnLabel(col)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {preview.rows.map((row, idx) => (
                  <tr key={idx} className={idx % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
                    {preview.columns.map((col) => (
                      <td
                        key={col}
                        className="px-4 py-2 text-sm text-gray-900 whitespace-nowrap max-w-xs truncate"
                      >
                        {String(row[col] ?? '')}
                      </td>
                    ))}
                  </tr>
                ))}
                {preview.rows.length === 0 && (
                  <tr>
                    <td
                      colSpan={preview.columns.length}
                      className="px-4 py-8 text-center text-sm text-gray-500"
                    >
                      No data found for the selected source(s)
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* How It Works */}
      <div className="rounded-lg border border-gray-200 bg-gray-50">
        <button
          type="button"
          onClick={() => setShowHowItWorks(!showHowItWorks)}
          className="w-full flex items-center justify-between px-4 py-3 text-sm font-medium text-gray-700 hover:text-gray-900"
        >
          <span>How Data Export Works</span>
          <svg
            className={`w-4 h-4 transition-transform ${showHowItWorks ? 'rotate-180' : ''}`}
            fill="none" viewBox="0 0 24 24" stroke="currentColor"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </button>
        {showHowItWorks && (
          <div className="px-4 pb-4 text-sm text-gray-600 space-y-2">
            <ul className="list-disc list-inside space-y-1">
              <li>Select one or more data sources to build your export template</li>
              <li>Pick the columns you need from each source — only selected columns appear in the export</li>
              <li>When combining multiple sources, data is automatically merged by <strong>Employee ID</strong></li>
              <li>Daily sources (Attendance, Schedules, Overtime, Tardiness) are also matched by <strong>Date</strong> when combined</li>
              <li>Use <strong>Custom Columns</strong> for computed fields using formulas (e.g., CONCAT, IF, math)</li>
              <li>Save your configuration as a template for quick re-use</li>
              <li>Set up <strong>Scheduled Exports</strong> to automatically email reports on a recurring basis</li>
            </ul>
          </div>
        )}
      </div>

      {/* ── Scheduled Exports ─────────────────────────────────── */}
      <div className="border-t border-gray-200 pt-6 mt-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-gray-900">Scheduled Exports</h2>
          {!showScheduleForm && (
            <button
              onClick={() => { resetScheduleForm(); setShowScheduleForm(true) }}
              className="rounded-md bg-purple-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-purple-700"
            >
              + New Schedule
            </button>
          )}
        </div>

        {/* Schedule messages */}
        {scheduleError && (
          <div className="rounded-md bg-red-50 p-3 mb-4">
            <p className="text-sm text-red-700">{scheduleError}</p>
          </div>
        )}
        {scheduleSuccess && (
          <div className="rounded-md bg-green-50 p-3 mb-4">
            <p className="text-sm text-green-700">{scheduleSuccess}</p>
          </div>
        )}

        {/* Schedule Form */}
        {showScheduleForm && (
          <div className="rounded-lg border border-gray-200 p-4 mb-4 bg-gray-50">
            <h3 className="text-sm font-semibold text-gray-900 mb-3">
              {editingScheduleId ? 'Edit Schedule' : 'New Schedule'}
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
              {/* Config selector */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Export Configuration</label>
                <select
                  value={scheduleConfigId}
                  onChange={(e) => setScheduleConfigId(e.target.value ? Number(e.target.value) : '')}
                  className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-purple-500 focus:ring-purple-500"
                >
                  <option value="">-- Select saved config --</option>
                  {configs.map((c) => (
                    <option key={c.id} value={c.id}>{c.name}</option>
                  ))}
                </select>
              </div>

              {/* Frequency */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Frequency</label>
                <select
                  value={scheduleType}
                  onChange={(e) => setScheduleType(e.target.value as 'daily' | 'weekly' | 'monthly')}
                  className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-purple-500 focus:ring-purple-500"
                >
                  <option value="daily">Daily</option>
                  <option value="weekly">Weekly</option>
                  <option value="monthly">Monthly</option>
                </select>
              </div>

              {/* Day of week (weekly) */}
              {scheduleType === 'weekly' && (
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Day of Week</label>
                  <select
                    value={scheduleDay}
                    onChange={(e) => setScheduleDay(Number(e.target.value))}
                    className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-purple-500 focus:ring-purple-500"
                  >
                    {WEEKDAYS.map((d, i) => (
                      <option key={i} value={i}>{d}</option>
                    ))}
                  </select>
                </div>
              )}

              {/* Day of month (monthly) */}
              {scheduleType === 'monthly' && (
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Day of Month</label>
                  <select
                    value={scheduleDay}
                    onChange={(e) => setScheduleDay(Number(e.target.value))}
                    className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-purple-500 focus:ring-purple-500"
                  >
                    {Array.from({ length: 31 }, (_, i) => i + 1).map((d) => (
                      <option key={d} value={d}>{d}</option>
                    ))}
                  </select>
                </div>
              )}

              {/* Time */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Time (HH:MM)</label>
                <input
                  type="time"
                  value={scheduleTime}
                  onChange={(e) => setScheduleTime(e.target.value)}
                  className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-purple-500 focus:ring-purple-500"
                />
              </div>

              {/* Recipient emails */}
              <div className="md:col-span-2">
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Recipient Emails <span className="text-gray-400 font-normal">(comma-separated)</span>
                </label>
                <input
                  type="text"
                  value={scheduleEmails}
                  onChange={(e) => setScheduleEmails(e.target.value)}
                  placeholder="user@example.com, another@example.com"
                  className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-purple-500 focus:ring-purple-500"
                />
              </div>

              {/* Active toggle */}
              <div className="flex items-center gap-2">
                <label className="relative inline-flex items-center cursor-pointer">
                  <input
                    type="checkbox"
                    checked={scheduleActive}
                    onChange={(e) => setScheduleActive(e.target.checked)}
                    className="sr-only peer"
                  />
                  <div className="w-9 h-5 bg-gray-300 peer-focus:ring-2 peer-focus:ring-purple-300 rounded-full peer peer-checked:bg-purple-600 after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:after:translate-x-full" />
                </label>
                <span className="text-sm text-gray-700">Active</span>
              </div>
            </div>

            <div className="flex gap-2">
              <button
                onClick={handleSaveSchedule}
                disabled={createScheduleMutation.isPending}
                className="rounded-md bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
              >
                {createScheduleMutation.isPending ? 'Saving...' : editingScheduleId ? 'Update Schedule' : 'Create Schedule'}
              </button>
              <button
                onClick={resetScheduleForm}
                className="rounded-md bg-white px-4 py-2 text-sm font-medium text-gray-700 border border-gray-300 hover:bg-gray-50"
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {/* Schedule List */}
        {schedules.length > 0 ? (
          <div className="rounded-lg border border-gray-200 overflow-hidden">
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Config</th>
                    <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Frequency</th>
                    <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Time</th>
                    <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Recipients</th>
                    <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Active</th>
                    <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Last Run</th>
                    <th className="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase">Actions</th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {schedules.map((s) => (
                    <tr key={s.id}>
                      <td className="px-4 py-2 text-sm text-gray-900 font-medium">{s.export_config_name}</td>
                      <td className="px-4 py-2 text-sm text-gray-700 capitalize">
                        {s.schedule_type}
                        {s.schedule_type === 'weekly' && s.schedule_day != null && (
                          <span className="text-gray-400 ml-1">({WEEKDAYS[s.schedule_day]?.slice(0, 3)})</span>
                        )}
                        {s.schedule_type === 'monthly' && s.schedule_day != null && (
                          <span className="text-gray-400 ml-1">(Day {s.schedule_day})</span>
                        )}
                      </td>
                      <td className="px-4 py-2 text-sm text-gray-700">{s.schedule_time}</td>
                      <td className="px-4 py-2 text-sm text-gray-700 max-w-[200px] truncate" title={s.recipient_emails.join(', ')}>
                        {s.recipient_emails.join(', ')}
                      </td>
                      <td className="px-4 py-2">
                        <label className="relative inline-flex items-center cursor-pointer">
                          <input
                            type="checkbox"
                            checked={s.is_active}
                            onChange={() => toggleScheduleActiveMutation.mutate({ id: s.id, is_active: !s.is_active })}
                            className="sr-only peer"
                          />
                          <div className="w-9 h-5 bg-gray-300 peer-focus:ring-2 peer-focus:ring-purple-300 rounded-full peer peer-checked:bg-purple-600 after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:after:translate-x-full" />
                        </label>
                      </td>
                      <td className="px-4 py-2 text-sm">
                        {s.last_run_at ? (
                          <span className={s.last_run_status === 'success' ? 'text-green-600' : 'text-red-600'}>
                            {s.last_run_status === 'success' ? 'OK' : 'Failed'}{' '}
                            {new Date(s.last_run_at).toLocaleString()}
                          </span>
                        ) : (
                          <span className="text-gray-400">Never</span>
                        )}
                      </td>
                      <td className="px-4 py-2 text-right">
                        <div className="flex items-center justify-end gap-1">
                          <button
                            onClick={() => runNowMutation.mutate(s.id)}
                            disabled={runNowMutation.isPending}
                            className="rounded px-2 py-1 text-xs font-medium text-green-700 bg-green-50 hover:bg-green-100"
                            title="Run Now"
                          >
                            Run
                          </button>
                          <button
                            onClick={() => editSchedule(s)}
                            className="rounded px-2 py-1 text-xs font-medium text-purple-700 bg-purple-50 hover:bg-purple-100"
                          >
                            Edit
                          </button>
                          <button
                            onClick={() => {
                              if (confirm('Delete this schedule?')) {
                                deleteScheduleMutation.mutate(s.id)
                              }
                            }}
                            className="rounded px-2 py-1 text-xs font-medium text-red-700 bg-red-50 hover:bg-red-100"
                          >
                            Delete
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ) : (
          <p className="text-sm text-gray-500">
            No scheduled exports yet. Save an export configuration above, then create a schedule to automatically email reports.
          </p>
        )}
      </div>
    </div>
  )
}
