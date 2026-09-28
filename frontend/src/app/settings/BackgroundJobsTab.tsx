'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { useToast } from '@/components/ui/Toast'
import type { BackgroundJobsView, JobRunRow } from '@/types'

// Plain-English names for the scheduler's jobs (app/services/scheduler.py).
const JOB_LABELS: Record<string, string> = {
  scheduled_exports: 'Scheduled reports',
  email_outbox: 'Send queued email',
  attendance_automation: 'Automatic clock-out and absences',
  leave_year_end: 'Leave year-end (carry-over and expiry)',
  leave_carry_over: 'Leave carry-over',
  carry_over_expiry: 'Carried-over leave expiry',
  leave_reminders: 'Leave approval reminders',
  holiday_sync: 'Holiday calendar sync',
  housekeeping: 'Daily housekeeping',
  scheduled_export: 'Scheduled report run',
}

const CADENCE_LABELS: Record<string, string> = {
  tick: 'Every minute',
  hourly: 'Every hour',
  daily: 'Once a day (company time)',
}

const STATUS_STYLES: Record<string, string> = {
  success: 'bg-green-100 text-green-700',
  sent: 'bg-green-100 text-green-700',
  failed: 'bg-red-100 text-red-700',
  running: 'bg-blue-100 text-blue-700',
  queued: 'bg-yellow-100 text-yellow-700',
  skipped: 'bg-gray-100 text-gray-600',
}

const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : '—')

function StatusPill({ status, title }: { status: string; title?: string | null }) {
  return (
    <span
      className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_STYLES[status] ?? 'bg-gray-100 text-gray-700'}`}
      title={title ?? undefined}
    >
      {status}
    </span>
  )
}

/** One line describing what a run did, from the counts it recorded. */
function summary(run: JobRunRow): string {
  if (run.error) return run.error
  const meta = (run.meta ?? {}) as Record<string, unknown>
  const counts = (meta.result && typeof meta.result === 'object' ? meta.result : meta) as Record<string, unknown>
  const parts = Object.entries(counts)
    .filter(([k, v]) => typeof v === 'number' && v !== 0 && k !== 'duration_s')
    .map(([k, v]) => `${k.replace(/_/g, ' ')}: ${v}`)
  return parts.length ? parts.join(', ') : 'Nothing to do'
}

export default function BackgroundJobsTab() {
  const queryClient = useQueryClient()
  const { showToast } = useToast()

  const { data, isLoading, isError } = useQuery<BackgroundJobsView>({
    queryKey: ['background-jobs'],
    queryFn: () => api.getBackgroundJobs(),
    refetchInterval: 30_000,
  })

  const retry = useMutation({
    mutationFn: (id: number) => api.retryOutboxEmail(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['background-jobs'] })
      showToast('The email will be sent again within a minute', 'success')
    },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  if (isLoading) return <div className="text-sm text-gray-500">Loading...</div>
  if (isError || !data) {
    return <div className="text-sm text-red-600">The background job status could not be loaded. Try again in a moment.</div>
  }

  const { counts, items } = data.outbox

  return (
    <div className="space-y-8">
      <div className="bg-white shadow-sm ring-1 ring-gray-900/5 rounded-xl">
        <div className="border-b border-gray-200 px-6 py-4">
          <h2 className="text-lg font-semibold text-gray-900">Background jobs</h2>
          <p className="mt-1 text-sm text-gray-500">
            Work the app does on its own: sending email and scheduled reports, closing forgotten clock-ins,
            leave reminders and year-end, the holiday calendar and daily housekeeping. One server process runs
            them; if it stops, another takes over within a minute. A job left unfinished by a crash is picked up
            again after {data.stale_after_minutes} minutes.
          </p>
        </div>
        <div className="px-6 py-6">
          <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {data.jobs.map((j) => (
              <li key={j.name} className="flex items-center justify-between rounded-lg border border-gray-200 px-3 py-2 text-sm">
                <span className="text-gray-900">{JOB_LABELS[j.name] ?? j.name}</span>
                <span className="text-xs text-gray-500">{CADENCE_LABELS[j.cadence] ?? j.cadence}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      <div className="bg-white shadow-sm ring-1 ring-gray-900/5 rounded-xl">
        <div className="border-b border-gray-200 px-6 py-4">
          <h2 className="text-lg font-semibold text-gray-900">Email waiting to be sent</h2>
          <p className="mt-1 text-sm text-gray-500">
            Emails are sent within a minute of the change they describe. If the mail server cannot be reached they
            are tried again, up to {data.max_email_attempts} times over about six hours, before being marked failed.
          </p>
        </div>
        <div className="px-6 py-6 space-y-4">
          <div className="flex flex-wrap gap-3 text-sm">
            <span className="rounded-lg bg-yellow-50 px-3 py-1.5 text-yellow-800">Waiting: {counts.queued}</span>
            <span className="rounded-lg bg-red-50 px-3 py-1.5 text-red-700">Failed: {counts.failed}</span>
            <span className="rounded-lg bg-gray-50 px-3 py-1.5 text-gray-700">Not sent, email off: {counts.skipped}</span>
            <span className="rounded-lg bg-green-50 px-3 py-1.5 text-green-700">Sent (last 30 days): {counts.sent}</span>
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200 text-sm">
              <thead>
                <tr className="text-left text-xs uppercase tracking-wide text-gray-500">
                  <th className="py-2 pr-4">Queued</th>
                  <th className="py-2 pr-4">Recipient</th>
                  <th className="py-2 pr-4">Subject</th>
                  <th className="py-2 pr-4">Status</th>
                  <th className="py-2 pr-4">Attempts</th>
                  <th className="py-2 pr-4">Next try / error</th>
                  <th className="py-2 pr-4"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {items.length === 0 && (
                  <tr>
                    <td colSpan={7} className="py-6 text-center text-gray-400">Nothing is waiting.</td>
                  </tr>
                )}
                {items.map((o) => (
                  <tr key={o.id}>
                    <td className="py-2 pr-4 whitespace-nowrap text-gray-500">{when(o.created_at)}</td>
                    <td className="py-2 pr-4 text-gray-700">{o.to_email}</td>
                    <td className="py-2 pr-4 text-gray-700">{o.subject}</td>
                    <td className="py-2 pr-4"><StatusPill status={o.status} /></td>
                    <td className="py-2 pr-4 text-gray-700">{o.attempts}</td>
                    <td className="py-2 pr-4 text-gray-500">
                      {o.status === 'queued' ? when(o.next_attempt_at) : (o.last_error ?? '—')}
                    </td>
                    <td className="py-2 pr-4 text-right">
                      {o.status !== 'queued' && (
                        <button
                          type="button"
                          onClick={() => retry.mutate(o.id)}
                          disabled={retry.isPending}
                          className="text-sm font-medium text-purple-600 hover:text-purple-700 disabled:opacity-50"
                        >
                          Retry now
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div className="bg-white shadow-sm ring-1 ring-gray-900/5 rounded-xl">
        <div className="border-b border-gray-200 px-6 py-4">
          <h2 className="text-lg font-semibold text-gray-900">Recent runs</h2>
          <p className="mt-1 text-sm text-gray-500">
            Jobs that ran every minute are listed only when they did something or failed.
          </p>
        </div>
        <div className="px-6 py-6 overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200 text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wide text-gray-500">
                <th className="py-2 pr-4">Job</th>
                <th className="py-2 pr-4">Period</th>
                <th className="py-2 pr-4">Status</th>
                <th className="py-2 pr-4">Started</th>
                <th className="py-2 pr-4">Finished</th>
                <th className="py-2 pr-4">Result</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {data.runs.length === 0 && (
                <tr>
                  <td colSpan={6} className="py-6 text-center text-gray-400">No runs recorded yet.</td>
                </tr>
              )}
              {data.runs.map((r) => (
                <tr key={r.id}>
                  <td className="py-2 pr-4 text-gray-900">{JOB_LABELS[r.job_name] ?? r.job_name}</td>
                  <td className="py-2 pr-4 text-gray-500">{r.period_key}</td>
                  <td className="py-2 pr-4"><StatusPill status={r.status} title={r.error} /></td>
                  <td className="py-2 pr-4 whitespace-nowrap text-gray-500">{when(r.started_at)}</td>
                  <td className="py-2 pr-4 whitespace-nowrap text-gray-500">{when(r.finished_at)}</td>
                  <td className={`py-2 pr-4 ${r.status === 'failed' ? 'text-red-700' : 'text-gray-700'}`}>{summary(r)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
