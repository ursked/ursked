'use client';

import React, { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { useToast } from '@/components/ui/Toast';
import { ErrorMessage } from '@/components/ui/ErrorBoundary';
import type { DataExportConfig, ScheduledExport } from '@/types';

const DAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

/** "Every Monday at 08:00" rather than "weekly / 0 / 08:00:00". */
function describe(s: ScheduledExport): string {
  const time = (s.schedule_time || '').slice(0, 5);
  if (s.schedule_type === 'daily') return `Every day at ${time}`;
  if (s.schedule_type === 'weekly') {
    return `Every ${DAY_NAMES[s.schedule_day ?? 0] || 'Monday'} at ${time}`;
  }
  const d = s.schedule_day ?? 1;
  const suffix = d === 1 ? 'st' : d === 2 ? 'nd' : d === 3 ? 'rd' : 'th';
  return `On the ${d}${suffix} of each month at ${time}`;
}

export default function SchedulePanel() {
  const { showToast } = useToast();
  const queryClient = useQueryClient();
  const [adding, setAdding] = useState(false);

  const { data: schedules, isError, refetch } = useQuery<ScheduledExport[]>({
    queryKey: ['export-schedules'],
    queryFn: () => api.getScheduledExports(),
  });
  const { data: configs } = useQuery<DataExportConfig[]>({
    queryKey: ['export-configs'],
    queryFn: () => api.getExportConfigs(),
  });

  const [configId, setConfigId] = useState('');
  const [type, setType] = useState('weekly');
  const [day, setDay] = useState('0');
  const [time, setTime] = useState('08:00');
  const [emails, setEmails] = useState('');

  const create = useMutation({
    mutationFn: () =>
      api.createScheduledExport({
        export_config_id: Number(configId),
        schedule_type: type,
        schedule_day: type === 'daily' ? undefined : Number(day),
        schedule_time: time,
        recipient_emails: emails.split(',').map((e) => e.trim()).filter(Boolean),
        is_active: true,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['export-schedules'] });
      setAdding(false);
      setEmails('');
      showToast('Schedule created.', 'success');
    },
    onError: (e: unknown) =>
      showToast(e instanceof Error ? e.message : 'Could not create the schedule.', 'error'),
  });

  const remove = useMutation({
    mutationFn: (id: number) => api.deleteScheduledExport(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['export-schedules'] });
      showToast('Schedule removed.', 'success');
    },
  });

  const runNow = useMutation({
    mutationFn: (id: number) => api.runScheduledExportNow(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['export-schedules'] });
      showToast('Sent. Check the recipients’ inboxes.', 'success');
    },
    onError: (e: unknown) =>
      showToast(e instanceof Error ? e.message : 'The run failed.', 'error'),
  });

  const input = 'min-h-[44px] rounded-lg border border-gray-300 px-3 text-sm text-gray-900';

  return (
    <div className="rounded-xl border border-gray-200 bg-white">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-gray-200 px-4 py-3">
        <div>
          <h2 className="text-sm font-semibold text-gray-900">Email this report on a schedule</h2>
          <p className="mt-0.5 text-xs text-gray-600">
            Saved reports can be emailed automatically. A report with a period like “last month”
            re-works it out each time it runs.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setAdding((v) => !v)}
          disabled={!configs || configs.length === 0}
          className="min-h-[44px] rounded-lg border border-gray-300 px-4 text-sm font-medium text-gray-800 hover:bg-gray-50 disabled:opacity-50"
        >
          {adding ? 'Cancel' : 'New schedule'}
        </button>
      </div>

      {isError && (
        <div className="p-4">
          <ErrorMessage message="Could not load your schedules." onRetry={() => refetch()} />
        </div>
      )}

      {adding && (
        <div className="grid gap-3 border-b border-gray-200 bg-gray-50 p-4 sm:grid-cols-2">
          <label className="block text-sm text-gray-800">
            Report
            <select value={configId} onChange={(e) => setConfigId(e.target.value)} className={`${input} mt-1 w-full`}>
              <option value="">Choose a saved report…</option>
              {(configs || []).map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
          </label>
          <label className="block text-sm text-gray-800">
            How often
            <select value={type} onChange={(e) => setType(e.target.value)} className={`${input} mt-1 w-full`}>
              <option value="daily">Every day</option>
              <option value="weekly">Every week</option>
              <option value="monthly">Every month</option>
            </select>
          </label>
          {type === 'weekly' && (
            <label className="block text-sm text-gray-800">
              On
              <select value={day} onChange={(e) => setDay(e.target.value)} className={`${input} mt-1 w-full`}>
                {DAY_NAMES.map((d, i) => (
                  <option key={d} value={i}>{d}</option>
                ))}
              </select>
            </label>
          )}
          {type === 'monthly' && (
            <label className="block text-sm text-gray-800">
              Day of the month
              <input type="number" min={1} max={28} value={day} onChange={(e) => setDay(e.target.value)} className={`${input} mt-1 w-full`} />
            </label>
          )}
          <label className="block text-sm text-gray-800">
            At
            <input type="time" value={time} onChange={(e) => setTime(e.target.value)} className={`${input} mt-1 w-full`} />
          </label>
          <label className="block text-sm text-gray-800 sm:col-span-2">
            Send to (comma separated)
            <input
              value={emails}
              onChange={(e) => setEmails(e.target.value)}
              placeholder="hr@example.com, payroll@example.com"
              className={`${input} mt-1 w-full`}
            />
          </label>
          <div className="sm:col-span-2">
            <button
              type="button"
              disabled={!configId || !emails.trim() || create.isPending}
              onClick={() => create.mutate()}
              className="min-h-[44px] rounded-lg bg-purple-600 px-4 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
            >
              {create.isPending ? 'Creating…' : 'Create schedule'}
            </button>
          </div>
        </div>
      )}

      {(schedules || []).length === 0 && !isError ? (
        <p className="px-4 py-6 text-sm text-gray-600">
          No schedules yet. Save a report above, then set one up here.
        </p>
      ) : (
        <ul className="divide-y divide-gray-100">
          {(schedules || []).map((s) => (
            <li key={s.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-gray-900">{s.export_config_name}</p>
                <p className="text-xs text-gray-600">
                  {describe(s)} · to {s.recipient_emails.join(', ')}
                </p>
                {s.last_run_status === 'failed' && (
                  <p className="mt-1 text-xs text-red-700">Last run failed: {s.last_run_error}</p>
                )}
              </div>
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
                onClick={() => remove.mutate(s.id)}
                disabled={remove.isPending}
                className="min-h-[44px] rounded-lg px-3 text-sm font-medium text-red-700 hover:bg-red-50 disabled:opacity-50"
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
