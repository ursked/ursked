'use client';

import { Fragment, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import DashboardLayout from '@/components/layout/DashboardLayout';
import { useAuth } from '@/contexts/AuthContext';
import { api } from '@/lib/api';
import { hasRole } from '@/lib/roles';
import { UserPicker } from '@/components/ui';
import type { AuditLogEntry, AuditLogPage } from '@/types';

// Who changed what, and when. Backed by GET /audit/logs, which is readable by
// administrators only, so the page is too. Employee edits carry before/after
// values; imports and bulk edits are one entry per batch.

const PER_PAGE = 25;

function fmtValue(v: unknown): string {
  if (v === null || v === undefined || v === '') return '(empty)';
  if (Array.isArray(v)) return v.join(', ') || '(none)';
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
}

function Changes({ entry }: { entry: AuditLogEntry }) {
  const d = (entry.details ?? {}) as Record<string, unknown>;
  const changes = { ...((d.changes as Record<string, { from: unknown; to: unknown }>) ?? {}) };
  for (const [k, v] of Object.entries((d.custom_fields as Record<string, { from: unknown; to: unknown }>) ?? {})) {
    changes[`${k} (custom)`] = v;
  }
  const rows = Object.entries(changes);
  const extra = Object.entries(d).filter(([k]) => !['changes', 'custom_fields', 'target_name', 'after'].includes(k));
  return (
    <div className="space-y-3 text-xs">
      {rows.length > 0 && (
        <table className="min-w-full">
          <thead>
            <tr className="text-left text-gray-500">
              <th className="py-1 pr-4 font-medium">Field</th>
              <th className="py-1 pr-4 font-medium">Before</th>
              <th className="py-1 font-medium">After</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([field, c]) => (
              <tr key={field} className="align-top">
                <td className="py-1 pr-4 text-gray-700">{field.replace(/_id$/, '').replace(/_/g, ' ')}</td>
                <td className="py-1 pr-4 text-gray-500 break-all">{fmtValue(c?.from)}</td>
                <td className="py-1 text-gray-900 break-all">{fmtValue(c?.to)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {extra.length > 0 && (
        <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1">
          {extra.map(([k, v]) => (
            <div key={k} className="flex gap-2">
              <dt className="text-gray-500">{k.replace(/_/g, ' ')}:</dt>
              <dd className="text-gray-900 break-all">{fmtValue(v)}</dd>
            </div>
          ))}
        </dl>
      )}
      {entry.ip_address && <p className="text-gray-500">From {entry.ip_address}</p>}
    </div>
  );
}

export default function AuditLogPage() {
  const { user } = useAuth();
  const isAdmin = !!user && hasRole(user, 'tenant_admin');

  const [page, setPage] = useState(1);
  const [actorId, setActorId] = useState<number | null>(null);
  const [targetId, setTargetId] = useState<number | null>(null);
  const [action, setAction] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [expanded, setExpanded] = useState<number | null>(null);

  const { data: actions = [] } = useQuery({
    queryKey: ['audit-actions'],
    queryFn: () => api.getAuditActions(),
    enabled: isAdmin,
  });

  const params: Record<string, string> = { page: String(page), per_page: String(PER_PAGE) };
  if (actorId) params.user_id = String(actorId);
  if (targetId) params.target_user_id = String(targetId);
  if (action) params.action = action;
  if (dateFrom) params.date_from = dateFrom;
  if (dateTo) params.date_to = dateTo;

  const { data, isLoading, isError, error } = useQuery<AuditLogPage>({
    queryKey: ['audit-logs', params],
    queryFn: () => api.getAuditLogs(params),
    enabled: isAdmin,
  });

  const resetPage = () => { setPage(1); setExpanded(null); };
  const hasFilters = actorId || targetId || action || dateFrom || dateTo;

  if (user && !isAdmin) {
    return (
      <DashboardLayout>
        <div className="max-w-xl mx-auto py-16 text-center">
          <h1 className="text-xl font-semibold text-gray-900">Audit log</h1>
          <p className="mt-2 text-sm text-gray-600">Only administrators can view the audit log.</p>
        </div>
      </DashboardLayout>
    );
  }

  return (
    <DashboardLayout>
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Audit log</h1>
          <p className="mt-1 text-sm text-gray-500">Who changed what, and when: employee records, roles, separations, imports, settings and sign-ins.</p>
        </div>

        {/* Filters */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-4">
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-5 gap-3">
            <UserPicker
              label="Done by"
              value={actorId}
              includeInactive
              onChange={(id) => { setActorId(id); resetPage(); }}
              placeholder="Anyone"
            />
            <UserPicker
              label="About employee"
              value={targetId}
              includeInactive
              onChange={(id) => { setTargetId(id); resetPage(); }}
              placeholder="Any employee"
            />
            <div>
              <label htmlFor="audit-action" className="mb-1 block text-sm font-medium text-gray-700">Action</label>
              <select
                id="audit-action"
                value={action}
                onChange={(e) => { setAction(e.target.value); resetPage(); }}
                className="h-10 w-full rounded-lg border border-gray-300 bg-white px-3 text-sm"
              >
                <option value="">All actions</option>
                {actions.map((a) => <option key={a.action} value={a.action}>{a.label}</option>)}
              </select>
            </div>
            <div>
              <label htmlFor="audit-from" className="mb-1 block text-sm font-medium text-gray-700">From</label>
              <input id="audit-from" type="date" value={dateFrom} onChange={(e) => { setDateFrom(e.target.value); resetPage(); }}
                className="h-10 w-full rounded-lg border border-gray-300 px-3 text-sm" />
            </div>
            <div>
              <label htmlFor="audit-to" className="mb-1 block text-sm font-medium text-gray-700">To</label>
              <input id="audit-to" type="date" value={dateTo} onChange={(e) => { setDateTo(e.target.value); resetPage(); }}
                className="h-10 w-full rounded-lg border border-gray-300 px-3 text-sm" />
            </div>
          </div>
          {hasFilters && (
            <button
              type="button"
              onClick={() => { setActorId(null); setTargetId(null); setAction(''); setDateFrom(''); setDateTo(''); resetPage(); }}
              className="mt-3 text-sm text-purple-700 underline"
            >
              Clear filters
            </button>
          )}
        </div>

        {/* Entries */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
          {/* relative: the sr-only header label is absolutely positioned; without a
              positioned ancestor inside the scroll box it escapes the clip and
              widens the whole page on a phone. */}
          <div className="relative overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-100 text-left">
                  <th className="py-3 px-4 font-medium text-gray-600 whitespace-nowrap">When</th>
                  <th className="py-3 px-4 font-medium text-gray-600">What happened</th>
                  <th className="py-3 px-4 font-medium text-gray-600 hidden md:table-cell">Action</th>
                  <th className="py-3 px-4"><span className="sr-only">Details</span></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {isLoading ? (
                  <tr><td colSpan={4} className="py-12 text-center text-gray-500">Loading…</td></tr>
                ) : isError ? (
                  <tr><td colSpan={4} className="py-12 text-center text-red-700">{error instanceof Error ? error.message : 'Could not load the audit log.'}</td></tr>
                ) : !data || data.items.length === 0 ? (
                  <tr><td colSpan={4} className="py-12 text-center text-gray-500">No entries{hasFilters ? ' match these filters' : ' yet'}.</td></tr>
                ) : (
                  data.items.map((e) => (
                    <Fragment key={e.id}>
                      <tr className="align-top hover:bg-gray-50">
                        <td className="py-3 px-4 text-gray-600 whitespace-nowrap">{e.created_at ? new Date(e.created_at).toLocaleString() : '--'}</td>
                        <td className="py-3 px-4 text-gray-900">{e.description || e.action}</td>
                        <td className="py-3 px-4 hidden md:table-cell">
                          <span className="inline-flex rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-700">{e.action_label || e.action}</span>
                        </td>
                        <td className="py-3 px-4 text-right">
                          <button
                            type="button"
                            onClick={() => setExpanded(expanded === e.id ? null : e.id)}
                            aria-expanded={expanded === e.id}
                            className="text-sm text-purple-700 hover:underline whitespace-nowrap"
                          >
                            {expanded === e.id ? 'Hide' : 'Details'}
                          </button>
                        </td>
                      </tr>
                      {expanded === e.id && (
                        <tr className="bg-gray-50">
                          <td colSpan={4} className="px-4 py-3"><Changes entry={e} /></td>
                        </tr>
                      )}
                    </Fragment>
                  ))
                )}
              </tbody>
            </table>
          </div>
          {data && data.total_pages > 1 && (
            <div className="flex items-center justify-between px-4 py-3 border-t border-gray-100">
              <p className="text-sm text-gray-500">Page {data.page} of {data.total_pages} ({data.total} entries)</p>
              <div className="flex gap-2">
                <button type="button" onClick={() => { setPage((p) => Math.max(1, p - 1)); setExpanded(null); }} disabled={page <= 1}
                  className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50">Previous</button>
                <button type="button" onClick={() => { setPage((p) => p + 1); setExpanded(null); }} disabled={page >= data.total_pages}
                  className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50">Next</button>
              </div>
            </div>
          )}
        </div>
      </div>
    </DashboardLayout>
  );
}
