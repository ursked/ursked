'use client'

import { useEffect, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { useToast } from '@/components/ui/Toast'
import type { SmtpSettings, SmtpSettingsUpdate, EmailLogEntry } from '@/types'

const EMPTY_FORM: SmtpSettingsUpdate = {
  smtp_active: false,
  smtp_host: '',
  smtp_port: 587,
  smtp_use_tls: true,
  smtp_use_ssl: false,
  smtp_username: '',
  smtp_password: '',
  smtp_from_email: '',
  smtp_from_name: '',
}

const STATUS_STYLES: Record<string, string> = {
  sent: 'bg-green-100 text-green-700',
  failed: 'bg-red-100 text-red-700',
  pending: 'bg-yellow-100 text-yellow-700',
}

export default function SmtpTab() {
  const queryClient = useQueryClient()
  const { showToast } = useToast()

  const [form, setForm] = useState<SmtpSettingsUpdate>(EMPTY_FORM)
  const [hasPassword, setHasPassword] = useState(false)
  const [testRecipient, setTestRecipient] = useState('')

  const { data: settings, isLoading } = useQuery<SmtpSettings>({
    queryKey: ['smtp-settings'],
    queryFn: () => api.getSmtpSettings(),
  })

  useEffect(() => {
    if (!settings) return
    let active = true
    // Defer so state updates do not run synchronously in the effect body
    // (react-hooks/set-state-in-effect).
    void Promise.resolve().then(() => {
      if (!active) return
      setForm({
        smtp_active: settings.smtp_active,
        smtp_host: settings.smtp_host ?? '',
        smtp_port: settings.smtp_port,
        smtp_use_tls: settings.smtp_use_tls,
        smtp_use_ssl: settings.smtp_use_ssl,
        smtp_username: settings.smtp_username ?? '',
        smtp_password: '', // never prefilled
        smtp_from_email: settings.smtp_from_email ?? '',
        smtp_from_name: settings.smtp_from_name ?? '',
      })
      setHasPassword(settings.has_password)
    })
    return () => {
      active = false
    }
  }, [settings])

  const saveMutation = useMutation({
    mutationFn: (data: Partial<SmtpSettingsUpdate>) => api.updateSmtpSettings(data),
    onSuccess: (res) => {
      setHasPassword(res.has_password)
      setForm((f) => ({ ...f, smtp_password: '' }))
      queryClient.invalidateQueries({ queryKey: ['smtp-settings'] })
      showToast('SMTP settings saved', 'success')
    },
    onError: () => showToast('Failed to save SMTP settings', 'error'),
  })

  const testMutation = useMutation({
    mutationFn: (recipient?: string) => api.testSmtp(recipient),
    onSuccess: (res) => {
      showToast(res.message, res.success ? 'success' : 'error')
      queryClient.invalidateQueries({ queryKey: ['email-logs'] })
    },
    onError: () => showToast('Test failed', 'error'),
  })

  const { data: logs } = useQuery<EmailLogEntry[]>({
    queryKey: ['email-logs'],
    queryFn: () => api.getEmailLogs(),
  })

  const handleSave = () => {
    // Omit the password entirely when the field is left blank, so an existing
    // password is preserved by the backend.
    const payload: Partial<SmtpSettingsUpdate> = { ...form }
    if (!payload.smtp_password) delete payload.smtp_password
    saveMutation.mutate(payload)
  }

  if (isLoading) {
    return <div className="py-12 text-center text-sm text-gray-500">Loading…</div>
  }

  const field = (label: string, node: React.ReactNode, hint?: string) => (
    <div>
      <label className="block text-sm font-medium text-gray-700">{label}</label>
      <div className="mt-1">{node}</div>
      {hint && <p className="mt-1 text-xs text-gray-400">{hint}</p>}
    </div>
  )

  const input =
    'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-transparent focus:ring-2 focus:ring-blue-500 outline-none'

  return (
    <div className="space-y-8">
      {/* Config */}
      <div className="rounded-xl border border-gray-200 bg-white p-6">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-lg font-semibold text-gray-900">Email (SMTP)</h3>
            <p className="mt-1 text-sm text-gray-500">
              Configure the mail server ursked uses to send invites, notifications and alerts.
            </p>
          </div>
          <label className="flex items-center gap-2 text-sm font-medium text-gray-700">
            <input
              type="checkbox"
              checked={!!form.smtp_active}
              onChange={(e) => setForm((f) => ({ ...f, smtp_active: e.target.checked }))}
              className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
            />
            Active
          </label>
        </div>

        <div className="mt-6 grid grid-cols-1 gap-5 sm:grid-cols-2">
          {field(
            'SMTP Host',
            <input
              className={input}
              value={form.smtp_host ?? ''}
              onChange={(e) => setForm((f) => ({ ...f, smtp_host: e.target.value }))}
              placeholder="smtp.example.com"
            />,
          )}
          {field(
            'Port',
            <input
              className={input}
              type="number"
              value={form.smtp_port ?? 587}
              onChange={(e) => setForm((f) => ({ ...f, smtp_port: parseInt(e.target.value) || 587 }))}
              placeholder="587"
            />,
            '587 for STARTTLS, 465 for SSL, 25 for plain.',
          )}
          {field(
            'Username',
            <input
              className={input}
              value={form.smtp_username ?? ''}
              onChange={(e) => setForm((f) => ({ ...f, smtp_username: e.target.value }))}
              autoComplete="off"
            />,
          )}
          {field(
            'Password',
            <input
              className={input}
              type="password"
              value={form.smtp_password ?? ''}
              onChange={(e) => setForm((f) => ({ ...f, smtp_password: e.target.value }))}
              placeholder={hasPassword ? '•••••••• (unchanged)' : ''}
              autoComplete="new-password"
            />,
            hasPassword ? 'Leave blank to keep the current password.' : undefined,
          )}
          {field(
            'From Email',
            <input
              className={input}
              value={form.smtp_from_email ?? ''}
              onChange={(e) => setForm((f) => ({ ...f, smtp_from_email: e.target.value }))}
              placeholder="no-reply@example.com"
            />,
          )}
          {field(
            'From Name',
            <input
              className={input}
              value={form.smtp_from_name ?? ''}
              onChange={(e) => setForm((f) => ({ ...f, smtp_from_name: e.target.value }))}
              placeholder="ursked"
            />,
          )}
        </div>

        <div className="mt-5 flex flex-wrap items-center gap-6">
          <label className="flex items-center gap-2 text-sm text-gray-700">
            <input
              type="checkbox"
              checked={!!form.smtp_use_tls}
              onChange={(e) => setForm((f) => ({ ...f, smtp_use_tls: e.target.checked }))}
              className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
            />
            Use STARTTLS
          </label>
          <label className="flex items-center gap-2 text-sm text-gray-700">
            <input
              type="checkbox"
              checked={!!form.smtp_use_ssl}
              onChange={(e) => setForm((f) => ({ ...f, smtp_use_ssl: e.target.checked }))}
              className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
            />
            Use SSL
          </label>
        </div>

        <div className="mt-6 flex flex-wrap items-center gap-3 border-t border-gray-100 pt-5">
          <button
            onClick={handleSave}
            disabled={saveMutation.isPending}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {saveMutation.isPending ? 'Saving…' : 'Save settings'}
          </button>
          <button
            onClick={() => testMutation.mutate(undefined)}
            disabled={testMutation.isPending}
            className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
          >
            Test connection
          </button>
          <div className="flex items-center gap-2">
            <input
              className="rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-transparent focus:ring-2 focus:ring-blue-500"
              value={testRecipient}
              onChange={(e) => setTestRecipient(e.target.value)}
              placeholder="you@company.com"
            />
            <button
              onClick={() => testMutation.mutate(testRecipient)}
              disabled={testMutation.isPending || !testRecipient}
              className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
            >
              Send test email
            </button>
          </div>
        </div>
      </div>

      {/* Email log */}
      <div className="rounded-xl border border-gray-200 bg-white p-6">
        <h3 className="text-lg font-semibold text-gray-900">Email log</h3>
        <p className="mt-1 text-sm text-gray-500">
          The most recent send attempts. Use this to confirm whether a message actually went out.
        </p>
        <div className="mt-4 overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200 text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wide text-gray-500">
                <th className="py-2 pr-4">When</th>
                <th className="py-2 pr-4">Type</th>
                <th className="py-2 pr-4">Recipient</th>
                <th className="py-2 pr-4">Subject</th>
                <th className="py-2 pr-4">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {(logs ?? []).length === 0 && (
                <tr>
                  <td colSpan={5} className="py-6 text-center text-gray-400">
                    No emails sent yet.
                  </td>
                </tr>
              )}
              {(logs ?? []).map((log) => (
                <tr key={log.id}>
                  <td className="py-2 pr-4 whitespace-nowrap text-gray-500">
                    {log.created_at ? new Date(log.created_at).toLocaleString() : '—'}
                  </td>
                  <td className="py-2 pr-4 text-gray-700">{log.type}</td>
                  <td className="py-2 pr-4 text-gray-700">{log.to_email}</td>
                  <td className="py-2 pr-4 text-gray-700">{log.subject}</td>
                  <td className="py-2 pr-4">
                    <span
                      className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${
                        STATUS_STYLES[log.status] ?? 'bg-gray-100 text-gray-700'
                      }`}
                      title={log.error_message ?? undefined}
                    >
                      {log.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
