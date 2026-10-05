'use client';

import React, { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, ScheduleConflict } from '@/lib/api';
import { ScheduleEmployee, Shift } from '@/types';
import { useToast } from '@/components/ui/Toast';
import { resolveStatus, formatShiftTime, type StatusMaps } from './scheduleHelpers';

// Schedule templates: a repeating pattern of days ("Mon-Fri 9-6, weekend
// off") that can be stamped onto any employees for any range. The API has
// existed for a long time with no screen, so the only way to use it was curl.
// A template is made from one employee's week as it is on the grid now.

interface TemplateDay {
  status?: string;
  start_time?: string | null;
  end_time?: string | null;
  work_arrangement?: string | null;
  role_name?: string | null;
  color?: string | null;
  work_site_id?: number | null;
}

interface TemplateRow {
  id: number;
  name: string;
  description?: string | null;
  template_data: TemplateDay[];
  is_active: boolean;
}

interface ApplyResult {
  created: Shift[];
  skipped_conflicts: ScheduleConflict[];
}

interface TemplatesPanelProps {
  isOpen: boolean;
  onClose: () => void;
  /** Rows the viewer manages: sources for a new template and targets to apply to. */
  employees: ScheduleEmployee[];
  /** First day of the week shown; a new template captures 7 days from here. */
  weekStart: string;
  statusMaps?: StatusMaps;
}

const DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

function addDays(iso: string, n: number): string {
  const d = new Date(iso + 'T00:00:00');
  d.setDate(d.getDate() + n);
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${d.getFullYear()}-${m}-${day}`;
}

function dayLabel(iso: string): string {
  const d = new Date(iso + 'T00:00:00');
  return DAY_NAMES[(d.getDay() + 6) % 7];
}

export default function TemplatesPanel({ isOpen, onClose, employees, weekStart, statusMaps }: TemplatesPanelProps) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [tab, setTab] = useState<'list' | 'create'>('list');

  // Create
  const [name, setName] = useState('');
  const [sourceId, setSourceId] = useState<number | ''>('');

  // Apply
  const [applyingId, setApplyingId] = useState<number | null>(null);
  const [applyStart, setApplyStart] = useState('');
  const [applyEnd, setApplyEnd] = useState('');
  const [targetIds, setTargetIds] = useState<number[]>([]);
  const [skipped, setSkipped] = useState<ScheduleConflict[]>([]);

  const { data: templates = [], isLoading } = useQuery<TemplateRow[]>({
    queryKey: ['schedule-templates'],
    queryFn: () => api.getTemplates() as Promise<TemplateRow[]>,
    enabled: isOpen,
  });

  const source = employees.find((e) => e.employee_id === sourceId);
  // The week pattern: the first shift of each of the 7 days, or an empty
  // entry (left unscheduled when applied).
  const pattern: TemplateDay[] = useMemo(() => {
    if (!source) return [];
    return Array.from({ length: 7 }, (_, i) => {
      const day = addDays(weekStart, i);
      const s = source.shifts.find((x) => x.date === day && !x.leave_application_id);
      if (!s) return {};
      return {
        status: s.status,
        start_time: s.start_time ?? null,
        end_time: s.end_time ?? null,
        work_arrangement: s.work_arrangement ?? null,
        role_name: s.role_name ?? null,
        color: s.color ?? null,
        work_site_id: s.work_site_id ?? null,
      };
    });
  }, [source, weekStart]);

  const createMutation = useMutation({
    mutationFn: () => api.createTemplate({
      name: name.trim(),
      description: source ? `From ${source.employee_name}'s week of ${weekStart}` : undefined,
      template_data: pattern,
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['schedule-templates'] });
      setName('');
      setSourceId('');
      setTab('list');
      showToast('Template saved', 'success');
    },
    onError: (err: Error) => showToast(err.message, 'error'),
  });

  const applyMutation = useMutation({
    mutationFn: (id: number) => api.applyTemplate(id, {
      start_date: applyStart,
      end_date: applyEnd || undefined,
      employee_ids: targetIds,
    }) as Promise<ApplyResult>,
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ['schedule-grid'] });
      setSkipped(res.skipped_conflicts ?? []);
      const n = res.created?.length ?? 0;
      const s = res.skipped_conflicts?.length ?? 0;
      showToast(
        `Created ${n} draft shift${n !== 1 ? 's' : ''}` + (s ? `, skipped ${s} day${s !== 1 ? 's' : ''}` : ''),
        n > 0 ? 'success' : 'info',
      );
      if (!s) setApplyingId(null);
    },
    onError: (err: Error) => showToast(err.message, 'error'),
  });

  if (!isOpen) return null;

  const startApply = (id: number) => {
    setApplyingId(id);
    setApplyStart(weekStart);
    setApplyEnd('');
    setTargetIds(employees.map((e) => e.employee_id));
    setSkipped([]);
  };

  const describe = (d: TemplateDay) => {
    if (!d || !d.status) return '—';
    const r = resolveStatus(d.status, statusMaps);
    const t = formatShiftTime(d.start_time, d.end_time);
    return t ? `${r.short} ${t}` : r.short;
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />
      <div className="relative w-full max-w-md bg-white shadow-2xl flex flex-col">
        <div className="px-6 py-4 border-b flex items-center justify-between">
          <div>
            <h3 className="text-lg font-semibold text-gray-900">Schedule Templates</h3>
            <p className="text-xs text-gray-500 mt-0.5">A weekly pattern you can stamp onto anyone, for any range</p>
          </div>
          <button onClick={onClose} className="p-1 rounded-lg hover:bg-gray-100 text-gray-400" aria-label="Close">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="px-6 border-b flex gap-4">
          {(['list', 'create'] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`py-2.5 text-sm font-medium border-b-2 transition-colors ${
                tab === t ? 'border-brand-600 text-brand-600' : 'border-transparent text-gray-500 hover:text-gray-700'
              }`}
            >
              {t === 'list' ? 'Templates' : 'New from this week'}
            </button>
          ))}
        </div>

        <div className="flex-1 overflow-y-auto p-6">
          {tab === 'create' ? (
            <div className="space-y-4">
              <div>
                <label htmlFor="tpl-source" className="block text-sm font-medium text-gray-700 mb-1">Copy the week of</label>
                <select
                  id="tpl-source"
                  value={sourceId}
                  onChange={(e) => setSourceId(e.target.value ? Number(e.target.value) : '')}
                  className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                >
                  <option value="">Choose an employee…</option>
                  {employees.map((e) => (
                    <option key={e.employee_id} value={e.employee_id}>{e.employee_name}</option>
                  ))}
                </select>
                <p className="mt-1 text-xs text-gray-500">The 7 days from {weekStart}, as they are on the grid now. Leave days are left out.</p>
              </div>

              {source && (
                <div className="grid grid-cols-7 gap-1 text-center">
                  {pattern.map((d, i) => (
                    <div key={i} className="rounded border border-gray-200 p-1">
                      <div className="text-[10px] font-medium text-gray-500">{dayLabel(addDays(weekStart, i))}</div>
                      <div className="text-[10px] text-gray-800 break-words">{describe(d)}</div>
                    </div>
                  ))}
                </div>
              )}

              <div>
                <label htmlFor="tpl-name" className="block text-sm font-medium text-gray-700 mb-1">Template name</label>
                <input
                  id="tpl-name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. Day shift, weekends off"
                  className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                />
              </div>

              <button
                onClick={() => createMutation.mutate()}
                disabled={!name.trim() || !source || pattern.every((d) => !d.status) || createMutation.isPending}
                className="w-full py-2 text-sm font-medium text-white bg-brand-600 rounded-lg hover:bg-brand-700 disabled:opacity-50"
              >
                {createMutation.isPending ? 'Saving…' : 'Save template'}
              </button>
            </div>
          ) : isLoading ? (
            <p className="text-sm text-gray-500">Loading…</p>
          ) : templates.length === 0 ? (
            <div className="text-center py-8">
              <p className="text-sm text-gray-500">No templates yet</p>
              <button
                onClick={() => setTab('create')}
                className="mt-3 px-4 py-1.5 text-xs font-medium text-brand-700 bg-brand-50 rounded-lg hover:bg-brand-100"
              >
                Make one from this week
              </button>
            </div>
          ) : (
            <div className="space-y-3">
              {templates.map((tpl) => (
                <div key={tpl.id} className="border border-gray-200 rounded-lg p-4">
                  <h4 className="text-sm font-medium text-gray-900">{tpl.name}</h4>
                  {tpl.description && <p className="text-xs text-gray-500 mt-0.5">{tpl.description}</p>}
                  <p className="mt-1 text-[11px] text-gray-600">
                    {(Array.isArray(tpl.template_data) ? tpl.template_data : []).map(describe).join(' · ')}
                  </p>

                  {applyingId === tpl.id ? (
                    <div className="mt-3 space-y-2 rounded-lg border border-blue-200 bg-blue-50 p-3">
                      <div className="grid grid-cols-2 gap-2">
                        <label className="text-xs text-blue-800">
                          From
                          <input type="date" value={applyStart} onChange={(e) => setApplyStart(e.target.value)}
                            className="mt-0.5 w-full rounded-md border border-blue-300 px-2 py-1 text-xs" />
                        </label>
                        <label className="text-xs text-blue-800">
                          Repeat until <span className="text-blue-500">(optional)</span>
                          <input type="date" value={applyEnd} min={applyStart || undefined}
                            onChange={(e) => setApplyEnd(e.target.value)}
                            className="mt-0.5 w-full rounded-md border border-blue-300 px-2 py-1 text-xs" />
                        </label>
                      </div>
                      <div>
                        <p className="text-xs text-blue-800 mb-1">For ({targetIds.length} selected)</p>
                        <div className="max-h-32 overflow-y-auto rounded border border-blue-200 bg-white p-1">
                          {employees.map((e) => (
                            <label key={e.employee_id} className="flex items-center gap-2 px-1 py-0.5 text-xs text-gray-700">
                              <input
                                type="checkbox"
                                checked={targetIds.includes(e.employee_id)}
                                onChange={() => setTargetIds((prev) => prev.includes(e.employee_id)
                                  ? prev.filter((x) => x !== e.employee_id) : [...prev, e.employee_id])}
                              />
                              {e.employee_name}
                            </label>
                          ))}
                        </div>
                      </div>
                      <p className="text-[11px] text-blue-600">
                        Creates draft shifts. Days that already have a shift, approved leave, or break a
                        schedule rule are skipped and listed.
                      </p>
                      {skipped.length > 0 && (
                        <ul className="max-h-24 overflow-y-auto rounded bg-amber-50 p-2 text-[11px] text-amber-800 space-y-0.5">
                          {skipped.map((c, i) => <li key={i}>{c.message}</li>)}
                        </ul>
                      )}
                      <div className="flex gap-2">
                        <button
                          onClick={() => applyMutation.mutate(tpl.id)}
                          disabled={!applyStart || targetIds.length === 0 || applyMutation.isPending}
                          className="flex-1 rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                        >
                          {applyMutation.isPending ? 'Applying…' : 'Apply'}
                        </button>
                        <button
                          onClick={() => setApplyingId(null)}
                          className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-xs text-gray-700"
                        >
                          Close
                        </button>
                      </div>
                    </div>
                  ) : (
                    <button
                      onClick={() => startApply(tpl.id)}
                      className="mt-3 w-full py-1.5 text-xs font-medium text-blue-700 bg-blue-50 rounded-lg hover:bg-blue-100"
                    >
                      Apply to a range…
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
