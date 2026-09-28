'use client';

import React, { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { useToast } from '@/components/ui/Toast';
import { ErrorMessage } from '@/components/ui/ErrorBoundary';
import type { DataExportConfig, ScheduledExport, ScheduledExportRun } from '@/types';
import { errorText, ordinal } from './reportLayout';

const DAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

/** "Every Monday at 08:00" rather than "weekly / 0 / 08:00:00". */
function describe(s: ScheduledExport): string {
  const time = (s.schedule_time || '').slice(0, 5);
  if (s.schedule_type === 'daily') return `Every day at ${time}`;
  if (s.schedule_type === 'weekly') {
    return `Every ${DAY_NAMES[s.schedule_day ?? 0] || 'Monday'} at ${time}`;
  }
  const d = s.schedule_day && s.schedule_day >= 1 ? s.schedule_day : 1;
  return `On the ${ordinal(d)} of each month at ${time}`;
}

interface FormState {
  configId: string;
  type: string;
  day: string;
  time: string;
  emails: string;
}

const BLANK: FormState = { configId: '', type: 'weekly', day: '0', time: '08:00', emails: '' };

function toForm(s: ScheduledExport): FormState {
  return {
    configId: String(s.export_config_id),
    type: s.schedule_type,
    day: String(s.schedule_day ?? (s.schedule_type === 'monthly' ? 1 : 0)),
    time: (s.schedule_time || '08:00').slice(0, 5),
    emails: s.recipient_emails.join(', '),
  };
}

function toBody(f: FormState) {
  return {
    export_config_id: Number(f.configId),
    schedule_type: f.type,
    schedule_day: f.type === 'daily' ? undefined : Number(f.day),
    schedule_time: f.time,
    recipient_emails: f.emails.split(',').map((e) => e.trim()).filter(Boolean),
  };
}

export default function SchedulePanel({
  canEdit = false,
  canDelete = false,
}: {
  /** reports:edit — create, change, pause and resume schedules. */
  canEdit?: boolean;
  /** reports:delete — delete schedules. */
  canDelete?: boolean;
}) {
  const { showToast } = useToast();
  const queryClient = useQueryClient();
  // null = closed, 'new' = adding, a number = editing that schedule.
  const [editing, setEditing] = useState<'new' | number | null>(null);
  const [form, setForm] = useState<FormState>(BLANK);
  const [historyFor, setHistoryFor] = useState<number | null>(null);

  const { data: schedules, isError, refetch } = useQuery<ScheduledExport[]>({
    queryKey: ['export-schedules'],
    queryFn: () => api.getScheduledExports(),
  });
  const { data: configs } = useQuery<DataExportConfig[]>({
    queryKey: ['export-configs'],
    queryFn: () => api.getExportConfigs(),
  });

  const done = (msg: string) => {
    queryClient.invalidateQueries({ queryKey: ['export-schedules'] });
    queryClient.invalidateQueries({ queryKey: ['export-schedule-runs'] });
    showToast(msg, 'success');
  };

  const save = useMutation({
    mutationFn: () =>
      editing === 'new' || editing === null
        ? api.createScheduledExport({ ...toBody(form), is_active: true })
        : api.updateScheduledExport(editing, toBody(form)),
    onSuccess: () => {
      done(editing === 'new' ? 'Schedule created.' : 'Schedule saved.');
      setEditing(null);
      setForm(BLANK);
    },
    onError: (e: unknown) => showToast(errorText(e, 'Could not save the schedule.'), 'error'),
  });

  const toggle = useMutation({
    mutationFn: (s: ScheduledExport) => api.updateScheduledExport(s.id, { is_active: !s.is_active }),
    onSuccess: (s) => done(s.is_active ? 'Schedule resumed.' : 'Schedule paused. Nothing is sent until you resume it.'),
    onError: (e: unknown) => showToast(errorText(e, 'Could not change the schedule.'), 'error'),
  });

  const remove = useMutation({
    mutationFn: (id: number) => api.deleteScheduledExport(id),
    onSuccess: () => done('Schedule removed.'),
    onError: (e: unknown) => showToast(errorText(e, 'Could not remove the schedule.'), 'error'),
  });

  const runNow = useMutation({
    mutationFn: (id: number) => api.runScheduledExportNow(id),
    onSuccess: () => done('Sent. Check the recipients’ inboxes.'),
    onError: (e: unknown) => {
      queryClient.invalidateQueries({ queryKey: ['export-schedules'] });
      showToast(errorText(e, 'The run failed.'), 'error');
    },
  });

  const input = 'min-h-[44px] rounded-lg border border-gray-300 px-3 text-sm text-gray-900';
  const set = (p: Partial<FormState>) => setForm((f) => ({ ...f, ...p }));
  const tz = schedules?.find((s) => s.timezone)?.timezone;

  const formBlock = (
    <div className="grid gap-3 border-b border-gray-200 bg-gray-50 p-4 sm:grid-cols-2">
      <label className="block text-sm text-gray-800">
        Report
        <select value={form.configId} onChange={(e) => set({ configId: e.target.value })} className={`${input} mt-1 w-full`}>
          <option value="">Choose a saved report…</option>
          {(configs || []).map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
      </label>
      <label className="block text-sm text-gray-800">
        How often
        <select
          value={form.type}
          onChange={(e) => {
            const type = e.target.value;
            // Switching kept the weekday index, so "Monday" (0) became day 0
            // of the month, which never comes round. Start each kind afresh.
            set({ type, day: type === 'monthly' ? '1' : '0' });
          }}
          className={`${input} mt-1 w-full`}
        >
          <option value="daily">Every day</option>
          <option value="weekly">Every week</option>
          <option value="monthly">Every month</option>
        </select>
      </label>
      {form.type === 'weekly' && (
        <label className="block text-sm text-gray-800">
          On
          <select value={form.day} onChange={(e) => set({ day: e.target.value })} className={`${input} mt-1 w-full`}>
            {DAY_NAMES.map((d, i) => (
              <option key={d} value={i}>{d}</option>
            ))}
          </select>
        </label>
      )}
      {form.type === 'monthly' && (
        <label className="block text-sm text-gray-800">
          Day of the month
          <select value={form.day} onChange={(e) => set({ day: e.target.value })} className={`${input} mt-1 w-full`}>
            {Array.from({ length: 31 }, (_, i) => i + 1).map((d) => (
              <option key={d} value={d}>{ordinal(d)}</option>
            ))}
          </select>
          {Number(form.day) > 28 && (
            <span className="mt-1 block text-xs text-gray-600">
              In months without a {ordinal(Number(form.day))}, it goes out on the last day of the month.
            </span>
          )}
        </label>
      )}
      <label className="block text-sm text-gray-800">
        At{tz ? ` (${tz} time)` : ''}
        <input type="time" value={form.time} onChange={(e) => set({ time: e.target.value })} className={`${input} mt-1 w-full`} />
      </label>
      <label className="block text-sm text-gray-800 sm:col-span-2">
        Send to (comma separated)
        <input
          value={form.emails}
          onChange={(e) => set({ emails: e.target.value })}
          placeholder="hr@example.com, payroll@example.com"
          className={`${input} mt-1 w-full`}
        />
      </label>
      <p className="text-xs text-gray-600 sm:col-span-2">
        The report is sent as you: it covers the people you can report on, and saving this makes
        you its owner.
      </p>
      <div className="flex flex-wrap gap-2 sm:col-span-2">
        <button
          type="button"
          disabled={!form.configId || !form.emails.trim() || !form.time || save.isPending}
          onClick={() => save.mutate()}
          className="min-h-[44px] rounded-lg bg-purple-600 px-4 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
        >
          {save.isPending ? 'Saving…' : editing === 'new' ? 'Create schedule' : 'Save schedule'}
        </button>
        <button
          type="button"
          onClick={() => {
            setEditing(null);
            setForm(BLANK);
          }}
          className="min-h-[44px] rounded-lg border border-gray-300 px-4 text-sm font-medium text-gray-700 hover:bg-gray-50"
        >
          Cancel
        </button>
      </div>
    </div>
  );

  return (
    <div className="rounded-xl border border-gray-200 bg-white">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-gray-200 px-4 py-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-gray-900">Email this report on a schedule</h2>
          <p className="mt-0.5 text-xs text-gray-600">
            Saved reports can be emailed automatically. A report with a period like “last month”
            re-works it out each time it runs. Times are in {tz || 'the company’s'} time.
          </p>
        </div>
        {canEdit && (
          <button
            type="button"
            onClick={() => {
              setEditing(editing === 'new' ? null : 'new');
              setForm(BLANK);
            }}
            disabled={!configs || configs.length === 0}
            className="min-h-[44px] rounded-lg border border-gray-300 px-4 text-sm font-medium text-gray-800 hover:bg-gray-50 disabled:opacity-50"
          >
            {editing === 'new' ? 'Cancel' : 'New schedule'}
          </button>
        )}
      </div>

      {isError && (
        <div className="p-4">
          <ErrorMessage message="Could not load your schedules." onRetry={() => refetch()} />
        </div>
      )}

      {editing === 'new' && formBlock}

      {(schedules || []).length === 0 && !isError ? (
        <p className="px-4 py-6 text-sm text-gray-600">
          No schedules yet. Save a report above, then set one up here.
        </p>
      ) : (
        <ul className="divide-y divide-gray-100">
          {(schedules || []).map((s) => (
            <li key={s.id}>
              {editing === s.id ? (
                formBlock
              ) : (
                <div className="flex flex-wrap items-center gap-2 px-4 py-3">
                  <div className="min-w-0 flex-1 basis-60">
                    <p className="text-sm font-medium text-gray-900">
                      {s.export_config_name}
                      {!s.is_active && (
                        <span className="ml-2 rounded bg-gray-100 px-1.5 py-0.5 text-xs font-medium text-gray-700">Paused</span>
                      )}
                    </p>
                    <p className="break-words text-xs text-gray-600">
                      {describe(s)} · to {s.recipient_emails.join(', ')}
                    </p>
                    {s.is_active && s.next_run_local && (
                      <p className="text-xs text-gray-600">
                        Next: {s.next_run_local}
                        {s.timezone ? ` (${s.timezone})` : ''}
                      </p>
                    )}
                    {s.owner_name && <p className="text-xs text-gray-500">Sent as {s.owner_name}</p>}
                    {s.last_run_status === 'failed' && (
                      <p className="mt-1 text-xs text-red-700">Last run failed: {s.last_run_error}</p>
                    )}
                  </div>
                  <div className="flex flex-wrap gap-1">
                    <button
                      type="button"
                      onClick={() => runNow.mutate(s.id)}
                      disabled={runNow.isPending}
                      className="min-h-[44px] rounded-lg border border-gray-300 px-3 text-sm font-medium text-gray-800 hover:bg-gray-50 disabled:opacity-50"
                    >
                      Send now
                    </button>
                    <button
                      type="button"
                      onClick={() => setHistoryFor(historyFor === s.id ? null : s.id)}
                      aria-expanded={historyFor === s.id}
                      className="min-h-[44px] rounded-lg px-3 text-sm font-medium text-gray-700 hover:bg-gray-50"
                    >
                      History
                    </button>
                    {canEdit && (
                      <>
                        <button
                          type="button"
                          onClick={() => toggle.mutate(s)}
                          disabled={toggle.isPending}
                          className="min-h-[44px] rounded-lg px-3 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
                        >
                          {s.is_active ? 'Pause' : 'Resume'}
                        </button>
                        <button
                          type="button"
                          onClick={() => {
                            setEditing(s.id);
                            setForm(toForm(s));
                          }}
                          className="min-h-[44px] rounded-lg px-3 text-sm font-medium text-purple-700 hover:bg-purple-50"
                        >
                          Edit
                        </button>
                      </>
                    )}
                    {canDelete && (
                      <button
                        type="button"
                        onClick={() => {
                          if (confirm(`Stop emailing “${s.export_config_name}” and delete this schedule?`)) remove.mutate(s.id);
                        }}
                        disabled={remove.isPending}
                        className="min-h-[44px] rounded-lg px-3 text-sm font-medium text-red-700 hover:bg-red-50 disabled:opacity-50"
                      >
                        Remove
                      </button>
                    )}
                  </div>
                  {historyFor === s.id && <RunHistory scheduleId={s.id} />}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function RunHistory({ scheduleId }: { scheduleId: number }) {
  const { data, isLoading, isError, refetch } = useQuery<ScheduledExportRun[]>({
    queryKey: ['export-schedule-runs', scheduleId],
    queryFn: () => api.getScheduledExportRuns(scheduleId),
  });
  if (isLoading) return <p className="w-full text-xs text-gray-600">Loading…</p>;
  if (isError) {
    return (
      <div className="w-full">
        <ErrorMessage message="Could not load the run history." onRetry={() => refetch()} />
      </div>
    );
  }
  if (!data || data.length === 0) {
    return <p className="w-full text-xs text-gray-600">It has not run yet.</p>;
  }
  return (
    <ol className="w-full space-y-1 rounded-lg bg-gray-50 p-3 text-xs">
      {data.map((r) => (
        <li key={r.id} className="flex flex-wrap gap-x-2">
          <span className="text-gray-700">{r.ran_at ? new Date(r.ran_at).toLocaleString() : '—'}</span>
          <span className={r.status === 'success' ? 'font-medium text-green-700' : 'font-medium text-red-700'}>
            {r.status === 'success' ? 'Sent' : 'Failed'}
          </span>
          {r.status === 'success' && r.recipients != null && (
            <span className="text-gray-600">
              to {r.delivered ?? 0} of {r.recipients} {r.recipients === 1 ? 'person' : 'people'}
              {r.rows != null ? `, ${r.rows.toLocaleString()} rows` : ''}
            </span>
          )}
          {r.error && <span className="w-full break-words text-red-700">{r.error}</span>}
        </li>
      ))}
    </ol>
  );
}
