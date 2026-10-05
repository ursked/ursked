'use client'

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { useToast } from '@/components/ui/Toast'
import type { AppSettings, RetentionReport } from '@/types'
import NumberSetting from './NumberSetting'

export default function DataBackupsTab() {
  const queryClient = useQueryClient()
  const { showToast } = useToast()
  const [starting, setStarting] = useState(false)

  const { data: appSettings } = useQuery<AppSettings>({
    queryKey: ['app-settings'],
    queryFn: () => api.getAppSettings(),
  })

  const { data: report, isLoading: reportLoading, isError: reportError } = useQuery<RetentionReport>({
    queryKey: ['retention-report', appSettings?.data_retention_days ?? null],
    queryFn: () => api.getRetentionReport(),
  })

  const save = useMutation({
    mutationFn: (data: Partial<AppSettings>) => api.updateAppSettings(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['app-settings'] })
      showToast('Housekeeping setting saved', 'success')
    },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  const download = async () => {
    setStarting(true)
    try {
      const { blob, filename } = await api.downloadBackup()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
      showToast('Backup downloaded', 'success')
    } catch (err) {
      const reason = err instanceof Error && err.message && err.message !== 'Failed to fetch'
        ? err.message
        : 'The backup did not complete. Nothing was saved; please try again.'
      showToast(reason, 'error')
    } finally {
      setStarting(false)
    }
  }

  return (
    <div className="space-y-8">
      {/* ── Backup ─────────────────────────────────────────────────── */}
      <div className="bg-white shadow-sm ring-1 ring-gray-900/5 rounded-xl">
        <div className="border-b border-gray-200 px-6 py-4">
          <h2 className="text-lg font-semibold text-gray-900">Backup</h2>
          <p className="mt-1 text-sm text-gray-500">
            Download a complete copy of the database: every employee, schedule, leave record and payroll run.
            Keep it somewhere safe; it contains personal and pay data. Because it holds everyone&apos;s salary
            figures, downloading one needs salary access (Finances, Salary Access), even for an administrator.
          </p>
        </div>
        <div className="px-6 py-6 space-y-3">
          <button
            type="button"
            onClick={download}
            disabled={starting}
            className="rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-brand-700 disabled:opacity-50"
          >
            {starting ? 'Preparing the backup...' : 'Download a backup'}
          </button>
          <p className="text-xs text-gray-500">
            The file is an SQL dump. The README explains how to restore it, and how to turn on automatic
            nightly backups on the server.
          </p>
        </div>
      </div>

      {/* ── Housekeeping ───────────────────────────────────────────── */}
      <div className="bg-white shadow-sm ring-1 ring-gray-900/5 rounded-xl">
        <div className="border-b border-gray-200 px-6 py-4">
          <h2 className="text-lg font-semibold text-gray-900">Housekeeping</h2>
          <p className="mt-1 text-sm text-gray-500">
            Once a day, early in the morning in your organization&apos;s timezone, the app removes expired sign-in
            sessions and the older entries below. It never deletes schedules, attendance, leave, payroll or employees.
          </p>
        </div>
        <div className="px-6 py-6 space-y-6">
          <NumberSetting
            id="audit_log_retention_days"
            label="Keep audit log entries for (days)"
            help="Who changed what: employee records, roles, permissions, settings. At least 90 days; two years (730) by default."
            value={appSettings?.audit_log_retention_days}
            min={90} max={3650}
            disabled={save.isPending}
            onCommit={(n) => save.mutate({ audit_log_retention_days: n })}
          />
          <NumberSetting
            id="login_history_retention_days"
            label="Keep sign-in history for (days)"
            help="Successful and failed sign-ins, shown in the audit log."
            value={appSettings?.login_history_retention_days}
            min={30} max={3650}
            disabled={save.isPending}
            onCommit={(n) => save.mutate({ login_history_retention_days: n })}
          />
          <NumberSetting
            id="read_notification_retention_days"
            label="Keep notifications that have been read for (days)"
            help="Unread notifications are always kept."
            value={appSettings?.read_notification_retention_days}
            min={7} max={3650}
            disabled={save.isPending}
            onCommit={(n) => save.mutate({ read_notification_retention_days: n })}
          />
        </div>
      </div>

      {/* ── Due for deletion ───────────────────────────────────────── */}
      <div className="bg-white shadow-sm ring-1 ring-gray-900/5 rounded-xl">
        <div className="border-b border-gray-200 px-6 py-4">
          <h2 className="text-lg font-semibold text-gray-900">Records due for deletion</h2>
          <p className="mt-1 text-sm text-gray-500">
            Records of employees who left longer ago than your data retention period (Settings &rarr; General
            &rarr; Employee Data Retention). This is a report only: nothing here is deleted automatically.
            Check your local record-keeping obligations before removing payroll or leave history.
          </p>
        </div>
        <div className="px-6 py-6">
          {reportLoading ? (
            <div className="text-sm text-gray-500">Loading...</div>
          ) : reportError || !report ? (
            <div className="text-sm text-red-600">The report could not be loaded. Try again in a moment.</div>
          ) : report.retention_days === null ? (
            <p className="text-sm text-gray-600">
              Your organization keeps records forever, so nothing is due for deletion.
            </p>
          ) : (
            <div className="space-y-4">
              <p className="text-sm text-gray-700">
                Retention period: <span className="font-medium">{report.retention_days} days</span> after the
                separation date. Due: employees who left before{' '}
                <span className="font-medium">{report.cutoff_date}</span>.
              </p>
              <table className="min-w-full max-w-md divide-y divide-gray-200 text-sm">
                <thead>
                  <tr className="text-left text-xs uppercase tracking-wide text-gray-500">
                    <th className="py-2 pr-4">Record type</th>
                    <th className="py-2 pr-4 text-right">Due</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {report.counts.map((c) => (
                    <tr key={c.type}>
                      <td className="py-2 pr-4 text-gray-700">{c.label}</td>
                      <td className="py-2 pr-4 text-right tabular-nums text-gray-900">{c.count.toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {report.employees.length > 0 && (
                <div>
                  <h3 className="text-sm font-semibold text-gray-900">Employees</h3>
                  <ul className="mt-2 space-y-1 text-sm text-gray-700">
                    {report.employees.map((e) => (
                      <li key={e.id}>
                        {e.name || `#${e.id}`}
                        <span className="text-gray-500"> — left {e.separation_date ?? 'on an unknown date'}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
