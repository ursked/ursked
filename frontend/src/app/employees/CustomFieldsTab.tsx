'use client';

import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { useToast } from '@/components/ui/Toast';
import type { CustomFieldDefinition, CustomFieldType, CustomFieldVisibility } from '@/types';
import { useEmployeeFieldConfig, VISIBILITY_LABELS, TYPE_LABELS } from './customFields';

// Employees > Custom fields: the answer to "can I add our own employee code?".
// A company defines a field once (label, type, who may see it, whether it must
// be unique); it then appears on the employee form, the detail panel, My
// Profile (if the employee may see it), the directory's optional columns and
// the CSV import. Managing needs settings:edit, like employee types.

interface Draft {
  key: string;
  label: string;
  field_type: CustomFieldType;
  optionsText: string;
  is_required: boolean;
  is_unique: boolean;
  regex: string;
  visibility: CustomFieldVisibility;
  is_sensitive: boolean;
  help_text: string;
}

const EMPTY: Draft = {
  key: '',
  label: '',
  field_type: 'text',
  optionsText: '',
  is_required: false,
  is_unique: false,
  regex: '',
  visibility: 'hr_only',
  is_sensitive: false,
  help_text: '',
};

const inputClass =
  'block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none disabled:bg-gray-100 disabled:text-gray-500';

function toKey(label: string) {
  const k = label.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
  return (/^[a-z]/.test(k) ? k : `f_${k}`).slice(0, 50);
}

export default function CustomFieldsTab() {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const { data: config, isLoading, isError } = useEmployeeFieldConfig(true);
  const canManage = !!config?.can_manage;
  const fields = config?.fields ?? [];

  const [editing, setEditing] = useState<CustomFieldDefinition | null>(null);
  const [creating, setCreating] = useState(false);
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [keyTouched, setKeyTouched] = useState(false);
  const [labelDraft, setLabelDraft] = useState<string | null>(null);

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['employee-field-config'] });
  };

  const save = useMutation({
    mutationFn: async () => {
      const body: Partial<CustomFieldDefinition> = {
        label: draft.label.trim(),
        field_type: draft.field_type,
        options: draft.field_type === 'select' ? draft.optionsText.split('\n').map((o) => o.trim()).filter(Boolean) : undefined,
        is_required: draft.is_required,
        is_unique: draft.is_unique,
        regex: draft.field_type === 'text' ? draft.regex.trim() || null : null,
        visibility: draft.visibility,
        is_sensitive: draft.is_sensitive,
        help_text: draft.help_text.trim() || null,
      };
      if (editing) return api.updateEmployeeField(editing.id, body);
      return api.createEmployeeField({ ...body, key: draft.key });
    },
    onSuccess: () => {
      refresh();
      showToast(editing ? 'Field updated' : 'Field added', 'success');
      close();
    },
    onError: (err: Error) => showToast(err.message, 'error'),
  });

  const remove = useMutation({
    mutationFn: (f: CustomFieldDefinition) => api.deleteEmployeeField(f.id),
    onSuccess: (res) => {
      refresh();
      showToast(res.result === 'archived' ? 'Field archived. Its values are kept and it can be restored.' : 'Field deleted', 'success');
    },
    onError: (err: Error) => showToast(err.message, 'error'),
  });

  const restore = useMutation({
    mutationFn: (f: CustomFieldDefinition) => api.updateEmployeeField(f.id, { is_archived: false }),
    onSuccess: () => { refresh(); showToast('Field restored', 'success'); },
    onError: (err: Error) => showToast(err.message, 'error'),
  });

  const reorder = useMutation({
    mutationFn: (ids: number[]) => api.reorderEmployeeFields(ids),
    onSuccess: refresh,
    onError: (err: Error) => showToast(err.message, 'error'),
  });

  const saveLabel = useMutation({
    mutationFn: (label: string | null) => api.setEmployeeNumberLabel(label),
    onSuccess: () => { refresh(); setLabelDraft(null); showToast('Label saved', 'success'); },
    onError: (err: Error) => showToast(err.message, 'error'),
  });

  const close = () => {
    setEditing(null);
    setCreating(false);
    setDraft(EMPTY);
    setKeyTouched(false);
  };

  const startEdit = (f: CustomFieldDefinition) => {
    setCreating(false);
    setEditing(f);
    setDraft({
      key: f.key,
      label: f.label,
      field_type: f.field_type,
      optionsText: f.options.join('\n'),
      is_required: f.is_required,
      is_unique: f.is_unique,
      regex: f.regex ?? '',
      visibility: f.visibility,
      is_sensitive: f.is_sensitive,
      help_text: f.help_text ?? '',
    });
  };

  const active = fields.filter((f) => !f.is_archived);
  const archived = fields.filter((f) => f.is_archived);

  const move = (index: number, delta: number) => {
    const ids = active.map((f) => f.id);
    const j = index + delta;
    if (j < 0 || j >= ids.length) return;
    [ids[index], ids[j]] = [ids[j], ids[index]];
    reorder.mutate(ids);
  };

  const showForm = creating || editing !== null;

  return (
    <div className="space-y-6">
      {/* Employee number label */}
      <div className="bg-white shadow-sm ring-1 ring-gray-900/5 rounded-xl px-6 py-5">
        <h2 className="text-lg font-semibold text-gray-900">Employee number</h2>
        <p className="mt-1 text-sm text-gray-500">
          Every employee has one built-in number, unique in your company. Call it what your company calls it
          (for example &ldquo;Badge no.&rdquo; or &ldquo;Staff ID&rdquo;); the new name is used everywhere it appears.
        </p>
        <div className="mt-4 flex flex-col sm:flex-row sm:items-end gap-3 max-w-xl">
          <div className="flex-1">
            <label htmlFor="emp-number-label" className="block text-sm font-medium text-gray-700 mb-1">Label</label>
            <input
              id="emp-number-label"
              type="text"
              maxLength={50}
              disabled={!canManage}
              value={labelDraft ?? config?.employee_number_label ?? ''}
              onChange={(e) => setLabelDraft(e.target.value)}
              className={inputClass}
            />
          </div>
          {canManage && (
            <div className="flex gap-2">
              <button
                type="button"
                disabled={labelDraft === null || saveLabel.isPending}
                onClick={() => saveLabel.mutate(labelDraft?.trim() || null)}
                className="rounded-md bg-purple-600 px-4 py-2 text-sm font-semibold text-white hover:bg-purple-700 disabled:opacity-50"
              >
                Save
              </button>
              {config && config.employee_number_label !== config.default_employee_number_label && (
                <button
                  type="button"
                  onClick={() => saveLabel.mutate(null)}
                  className="rounded-md bg-white px-4 py-2 text-sm font-semibold text-gray-700 ring-1 ring-inset ring-gray-300 hover:bg-gray-50"
                >
                  Reset to &ldquo;{config.default_employee_number_label}&rdquo;
                </button>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Field list */}
      <div className="bg-white shadow-sm ring-1 ring-gray-900/5 rounded-xl">
        <div className="border-b border-gray-200 px-6 py-4 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Custom fields</h2>
            <p className="mt-1 text-sm text-gray-500">
              Information your company keeps about employees that is not built in, such as a company code, locker number or union membership.
            </p>
          </div>
          {canManage && !showForm && (
            <button
              type="button"
              onClick={() => { setCreating(true); setEditing(null); setDraft(EMPTY); }}
              className="inline-flex items-center gap-1.5 rounded-md bg-purple-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-purple-700 whitespace-nowrap"
            >
              Add field
            </button>
          )}
        </div>

        <div className="px-6 py-6 space-y-6">
          {!canManage && config && (
            <p className="rounded-lg border border-gray-200 bg-gray-50 px-4 py-3 text-sm text-gray-600">
              You can see which custom fields exist. Adding or changing them needs permission to edit company settings.
            </p>
          )}

          {showForm && canManage && (
            <form
              onSubmit={(e) => { e.preventDefault(); save.mutate(); }}
              className="bg-gray-50 border border-gray-200 rounded-lg p-5 space-y-4"
            >
              <h3 className="text-sm font-semibold text-gray-900">{editing ? `Edit “${editing.label}”` : 'New field'}</h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label htmlFor="cf-label" className="block text-sm font-medium text-gray-700 mb-1">Label</label>
                  <input
                    id="cf-label"
                    required
                    maxLength={100}
                    value={draft.label}
                    onChange={(e) => {
                      const label = e.target.value;
                      setDraft((d) => ({ ...d, label, key: editing || keyTouched ? d.key : toKey(label) }));
                    }}
                    placeholder="e.g. XXXX employee code"
                    className={inputClass}
                  />
                </div>
                <div>
                  <label htmlFor="cf-key" className="block text-sm font-medium text-gray-700 mb-1">Key (CSV column)</label>
                  <input
                    id="cf-key"
                    required
                    maxLength={50}
                    disabled={!!editing}
                    value={draft.key}
                    onChange={(e) => { setKeyTouched(true); setDraft((d) => ({ ...d, key: e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, '_') })); }}
                    className={`${inputClass} font-mono`}
                  />
                  <p className="mt-1 text-xs text-gray-500">{editing ? 'The key cannot change, so imports keep working.' : 'Lowercase letters, digits and underscores.'}</p>
                </div>
                <div>
                  <label htmlFor="cf-type" className="block text-sm font-medium text-gray-700 mb-1">Type</label>
                  <select
                    id="cf-type"
                    value={draft.field_type}
                    onChange={(e) => setDraft((d) => ({ ...d, field_type: e.target.value as CustomFieldType }))}
                    className={`${inputClass} bg-white`}
                  >
                    {(Object.keys(TYPE_LABELS) as CustomFieldType[]).map((t) => (
                      <option key={t} value={t}>{TYPE_LABELS[t]}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label htmlFor="cf-vis" className="block text-sm font-medium text-gray-700 mb-1">Who can see it</label>
                  <select
                    id="cf-vis"
                    value={draft.visibility}
                    onChange={(e) => setDraft((d) => ({ ...d, visibility: e.target.value as CustomFieldVisibility }))}
                    className={`${inputClass} bg-white`}
                  >
                    {(Object.keys(VISIBILITY_LABELS) as CustomFieldVisibility[]).map((v) => (
                      <option key={v} value={v}>{VISIBILITY_LABELS[v]}</option>
                    ))}
                  </select>
                </div>
                {draft.field_type === 'select' && (
                  <div className="sm:col-span-2">
                    <label htmlFor="cf-options" className="block text-sm font-medium text-gray-700 mb-1">Options (one per line)</label>
                    <textarea
                      id="cf-options"
                      rows={4}
                      value={draft.optionsText}
                      onChange={(e) => setDraft((d) => ({ ...d, optionsText: e.target.value }))}
                      className={inputClass}
                    />
                  </div>
                )}
                {draft.field_type === 'text' && (
                  <div>
                    <label htmlFor="cf-regex" className="block text-sm font-medium text-gray-700 mb-1">Required format (optional)</label>
                    <input
                      id="cf-regex"
                      maxLength={200}
                      value={draft.regex}
                      onChange={(e) => setDraft((d) => ({ ...d, regex: e.target.value }))}
                      placeholder="e.g. X-\d{4}"
                      className={`${inputClass} font-mono`}
                    />
                    <p className="mt-1 text-xs text-gray-500">A regular expression every value must match. Leave empty for any text.</p>
                  </div>
                )}
                <div>
                  <label htmlFor="cf-help" className="block text-sm font-medium text-gray-700 mb-1">Help text (optional)</label>
                  <input
                    id="cf-help"
                    maxLength={300}
                    value={draft.help_text}
                    onChange={(e) => setDraft((d) => ({ ...d, help_text: e.target.value }))}
                    className={inputClass}
                  />
                </div>
              </div>
              <div className="flex flex-wrap gap-x-6 gap-y-2">
                <label className="inline-flex items-center gap-2 text-sm text-gray-700">
                  <input type="checkbox" checked={draft.is_required} onChange={(e) => setDraft((d) => ({ ...d, is_required: e.target.checked }))} className="h-4 w-4 rounded border-gray-300 text-purple-600" />
                  Required
                </label>
                {draft.field_type !== 'boolean' && (
                  <label className="inline-flex items-center gap-2 text-sm text-gray-700">
                    <input type="checkbox" checked={draft.is_unique} onChange={(e) => setDraft((d) => ({ ...d, is_unique: e.target.checked }))} className="h-4 w-4 rounded border-gray-300 text-purple-600" />
                    Unique (no two employees may share a value; searchable in the directory)
                  </label>
                )}
                <label className="inline-flex items-center gap-2 text-sm text-gray-700">
                  <input type="checkbox" checked={draft.is_sensitive} onChange={(e) => setDraft((d) => ({ ...d, is_sensitive: e.target.checked }))} className="h-4 w-4 rounded border-gray-300 text-purple-600" />
                  Sensitive (never shown in tables, search or reports below HR level)
                </label>
              </div>
              <div className="flex gap-3">
                <button type="submit" disabled={save.isPending} className="rounded-md bg-purple-600 px-4 py-2 text-sm font-semibold text-white hover:bg-purple-700 disabled:opacity-50">
                  {save.isPending ? 'Saving…' : editing ? 'Save changes' : 'Add field'}
                </button>
                <button type="button" onClick={close} className="rounded-md bg-white px-4 py-2 text-sm font-semibold text-gray-700 ring-1 ring-inset ring-gray-300 hover:bg-gray-50">
                  Cancel
                </button>
              </div>
            </form>
          )}

          {isLoading ? (
            <p className="text-sm text-gray-500">Loading…</p>
          ) : isError ? (
            <p className="text-sm text-red-700">Could not load custom fields.</p>
          ) : active.length === 0 ? (
            <div className="text-center py-10">
              <h3 className="text-sm font-semibold text-gray-900">No custom fields yet</h3>
              <p className="mt-1 text-sm text-gray-500">Add one to start recording it on every employee.</p>
            </div>
          ) : (
            <div className="relative overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200 text-sm">
                <thead>
                  <tr>
                    {canManage && <th className="px-2 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500"><span className="sr-only">Order</span></th>}
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Field</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Type</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Who can see it</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Rules</th>
                    {canManage && <th className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-wider text-gray-500">Actions</th>}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {active.map((f, i) => (
                    <tr key={f.id} className="hover:bg-gray-50">
                      {canManage && (
                        <td className="px-2 py-3 whitespace-nowrap">
                          <button type="button" onClick={() => move(i, -1)} disabled={i === 0 || reorder.isPending} aria-label={`Move ${f.label} up`} className="h-8 w-8 rounded text-gray-500 hover:bg-gray-100 disabled:opacity-30">&uarr;</button>
                          <button type="button" onClick={() => move(i, 1)} disabled={i === active.length - 1 || reorder.isPending} aria-label={`Move ${f.label} down`} className="h-8 w-8 rounded text-gray-500 hover:bg-gray-100 disabled:opacity-30">&darr;</button>
                        </td>
                      )}
                      <td className="px-4 py-3">
                        <p className="font-medium text-gray-900">{f.label}</p>
                        <p className="font-mono text-xs text-gray-500">{f.key}</p>
                      </td>
                      <td className="px-4 py-3 text-gray-700">
                        {TYPE_LABELS[f.field_type]}
                        {f.field_type === 'select' && <span className="block text-xs text-gray-500">{f.options.join(', ')}</span>}
                      </td>
                      <td className="px-4 py-3 text-gray-700">{VISIBILITY_LABELS[f.visibility]}</td>
                      <td className="px-4 py-3">
                        <div className="flex flex-wrap gap-1">
                          {f.is_required && <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-700">Required</span>}
                          {f.is_unique && <span className="rounded-full bg-blue-50 px-2 py-0.5 text-xs text-blue-800">Unique</span>}
                          {f.is_sensitive && <span className="rounded-full bg-amber-50 px-2 py-0.5 text-xs text-amber-800">Sensitive</span>}
                          {f.regex && <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-700">Format</span>}
                        </div>
                      </td>
                      {canManage && (
                        <td className="px-4 py-3 text-right whitespace-nowrap">
                          <button type="button" onClick={() => startEdit(f)} className="rounded-md px-2 py-1 text-sm text-purple-700 hover:bg-purple-50">Edit</button>
                          <button
                            type="button"
                            onClick={() => {
                              if (confirm(`Remove “${f.label}”? If any employee has a value it is archived (kept, hidden, restorable) instead of deleted.`)) remove.mutate(f);
                            }}
                            className="rounded-md px-2 py-1 text-sm text-red-700 hover:bg-red-50"
                          >
                            Remove
                          </button>
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {canManage && archived.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold text-gray-900">Archived</h3>
              <p className="text-xs text-gray-500 mb-2">Hidden from forms and tables. Values are kept.</p>
              <ul className="divide-y divide-gray-100 rounded-lg border border-gray-200">
                {archived.map((f) => (
                  <li key={f.id} className="flex items-center justify-between px-4 py-2 text-sm">
                    <span className="text-gray-700">{f.label} <span className="font-mono text-xs text-gray-500">{f.key}</span></span>
                    <button type="button" onClick={() => restore.mutate(f)} className="rounded-md px-2 py-1 text-sm text-purple-700 hover:bg-purple-50">Restore</button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
