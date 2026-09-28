'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { Modal, Button, UserPicker } from '@/components/ui';
import type {
  EmployeeBulkAction,
  EmployeeBulkRequest,
  EmployeeBulkResponse,
  EmployeeTypeConfig,
  ScheduleFormatConfig,
} from '@/types';
import OrgUnitSelect from './OrgUnitSelect';

// One change applied to many employees (PATCH /users/bulk). The server checks
// every target (scope, the administrator safeguards) and reports per person,
// so a partial result is shown rather than hidden behind a single toast.

export type BulkSelection =
  | { mode: 'ids'; ids: number[] }
  | { mode: 'filter'; filter: NonNullable<EmployeeBulkRequest['filter']>; count: number };

interface Props {
  selection: BulkSelection;
  canEdit: boolean;
  canCreate: boolean;
  canSeparate: boolean;
  onClear: () => void;
  onDone: () => void;
}

const ACTION_LABELS: Record<EmployeeBulkAction, string> = {
  set_employee_type: 'Change employee type',
  set_schedule_format: 'Change schedule format',
  set_org_unit: 'Move to organization unit',
  set_reports_to: 'Set line manager',
  send_invite: 'Send or resend invites',
  separate: 'Separate (resign / terminate)',
};

const selectClass =
  'px-3 py-2 border border-gray-300 rounded-lg text-sm bg-white focus:ring-2 focus:ring-purple-500 focus:border-transparent outline-none';

export default function BulkActionsBar({ selection, canEdit, canCreate, canSeparate, onClear, onDone }: Props) {
  const count = selection.mode === 'ids' ? selection.ids.length : selection.count;
  const available = (Object.keys(ACTION_LABELS) as EmployeeBulkAction[]).filter((a) =>
    a === 'send_invite' ? canCreate : a === 'separate' ? canSeparate : canEdit
  );
  const [action, setAction] = useState<EmployeeBulkAction | ''>('');
  const [value, setValue] = useState<string | number | null>(null);
  const [sepType, setSepType] = useState<'resigned' | 'terminated'>('resigned');
  const [sepDate, setSepDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [sepReason, setSepReason] = useState('');
  const [deleteShifts, setDeleteShifts] = useState(true);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<EmployeeBulkResponse | null>(null);

  const { data: types } = useQuery<EmployeeTypeConfig[]>({
    queryKey: ['employee-types'],
    queryFn: () => api.getEmployeeTypes(),
    enabled: action === 'set_employee_type',
  });
  const { data: formats } = useQuery<ScheduleFormatConfig[]>({
    queryKey: ['schedule-formats'],
    queryFn: () => api.getScheduleFormats(),
    enabled: action === 'set_schedule_format',
  });

  if (available.length === 0) return null;

  const apply = async () => {
    if (!action) return;
    setBusy(true);
    setError('');
    const body: EmployeeBulkRequest = { action };
    if (selection.mode === 'ids') body.user_ids = selection.ids;
    else body.filter = selection.filter;
    if (action === 'separate') {
      body.separation = {
        separation_type: sepType,
        separation_date: sepDate,
        separation_reason: sepReason || undefined,
        delete_future_shifts: deleteShifts,
      };
    } else if (action !== 'send_invite') {
      body.value = value === '' ? null : value;
    }
    try {
      const res = await api.bulkUpdateUsers(body);
      setResult(res);
      setConfirming(false);
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The change failed.');
    } finally {
      setBusy(false);
    }
  };

  const valueControl = () => {
    switch (action) {
      case 'set_employee_type':
        return (
          <select aria-label="New employee type" value={String(value ?? '')} onChange={(e) => setValue(e.target.value)} className={selectClass}>
            <option value="">No type</option>
            {(types ?? []).map((t) => <option key={t.code} value={t.code}>{t.name}</option>)}
          </select>
        );
      case 'set_schedule_format':
        return (
          <select aria-label="New schedule format" value={String(value ?? '')} onChange={(e) => setValue(e.target.value)} className={selectClass}>
            <option value="">No format</option>
            {(formats ?? []).map((f) => <option key={f.code} value={f.code}>{f.name}</option>)}
          </select>
        );
      case 'set_org_unit':
        return (
          <div className="min-w-[14rem]">
            <OrgUnitSelect value={typeof value === 'number' ? value : null} onChange={(id) => setValue(id)} className={selectClass} />
          </div>
        );
      case 'set_reports_to':
        return (
          <div className="min-w-[16rem]">
            <UserPicker value={typeof value === 'number' ? value : null} onChange={(id) => setValue(id)} placeholder="Search for the manager (empty clears)" />
          </div>
        );
      default:
        return null;
    }
  };

  return (
    <>
      <div className="sticky top-2 z-30 flex flex-col gap-3 rounded-xl border border-purple-200 bg-purple-50 px-4 py-3 shadow-sm lg:flex-row lg:items-center" role="region" aria-label="Bulk actions">
        <p className="text-sm font-medium text-purple-900 whitespace-nowrap">
          {count} selected
          <button type="button" onClick={onClear} className="ml-2 text-xs font-normal text-purple-700 underline">Clear</button>
        </p>
        <div className="flex flex-1 flex-wrap items-center gap-2">
          <select
            aria-label="Bulk action"
            value={action}
            onChange={(e) => { setAction(e.target.value as EmployeeBulkAction | ''); setValue(null); setError(''); }}
            className={selectClass}
          >
            <option value="">Choose an action…</option>
            {available.map((a) => <option key={a} value={a}>{ACTION_LABELS[a]}</option>)}
          </select>
          {valueControl()}
          {action && (
            <Button size="sm" onClick={() => setConfirming(true)} disabled={busy}>Apply to {count}</Button>
          )}
        </div>
        {error && <p className="text-sm text-red-700" role="alert">{error}</p>}
      </div>

      {confirming && action && (
        <Modal
          open
          onOpenChange={(o) => { if (!o) setConfirming(false); }}
          title={`${ACTION_LABELS[action]} for ${count} ${count === 1 ? 'employee' : 'employees'}?`}
          description={action === 'separate' ? 'They will be deactivated and signed out everywhere. You can reinstate them later.' : 'Each employee is checked individually; you will see who was changed and who was not.'}
          size="md"
          footer={
            <>
              <Button variant="secondary" onClick={() => setConfirming(false)} disabled={busy}>Cancel</Button>
              <Button variant={action === 'separate' ? 'danger' : 'primary'} onClick={apply} loading={busy}>Confirm</Button>
            </>
          }
        >
          {action === 'separate' ? (
            <div className="space-y-3 text-sm">
              <div className="flex gap-3">
                {(['resigned', 'terminated'] as const).map((t) => (
                  <label key={t} className="inline-flex items-center gap-2">
                    <input type="radio" name="bulk-sep-type" checked={sepType === t} onChange={() => setSepType(t)} className="h-4 w-4 text-purple-600" />
                    {t === 'resigned' ? 'Resigned' : 'Terminated'}
                  </label>
                ))}
              </div>
              <div>
                <label htmlFor="bulk-sep-date" className="block text-sm font-medium text-gray-700 mb-1">Separation date</label>
                <input id="bulk-sep-date" type="date" value={sepDate} onChange={(e) => setSepDate(e.target.value)} className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm" />
              </div>
              <div>
                <label htmlFor="bulk-sep-reason" className="block text-sm font-medium text-gray-700 mb-1">Reason (optional)</label>
                <textarea id="bulk-sep-reason" rows={2} value={sepReason} onChange={(e) => setSepReason(e.target.value)} className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm" />
              </div>
              <label className="inline-flex items-center gap-2">
                <input type="checkbox" checked={deleteShifts} onChange={(e) => setDeleteShifts(e.target.checked)} className="h-4 w-4 rounded text-purple-600" />
                Delete their shifts after the separation date
              </label>
            </div>
          ) : (
            <p className="text-sm text-gray-600">This cannot be undone in one step, but every change is recorded in the audit log.</p>
          )}
          {error && <p className="mt-3 text-sm text-red-700" role="alert">{error}</p>}
        </Modal>
      )}

      {result && (
        <Modal
          open
          onOpenChange={(o) => { if (!o) { setResult(null); setAction(''); onClear(); } }}
          title="Bulk change finished"
          description={`${result.updated} changed, ${result.skipped} skipped, ${result.failed} not changed because of a problem.`}
          size="lg"
          footer={<Button onClick={() => { setResult(null); setAction(''); onClear(); }}>Done</Button>}
        >
          {result.results.filter((r) => r.status !== 'updated').length === 0 ? (
            <p className="text-sm text-gray-700">Everyone was changed.</p>
          ) : (
            <ul className="divide-y divide-gray-100 text-sm">
              {result.results.filter((r) => r.status !== 'updated').map((r) => (
                <li key={r.user_id} className="flex justify-between gap-4 py-2">
                  <span className="text-gray-900">{r.name}</span>
                  <span className={r.status === 'error' ? 'text-red-700' : 'text-gray-600'}>{r.message || r.status}</span>
                </li>
              ))}
            </ul>
          )}
        </Modal>
      )}
    </>
  );
}
