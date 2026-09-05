'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { useToast } from '@/components/ui/Toast';
import { ErrorMessage } from '@/components/ui/ErrorBoundary';
import type {
  AggregationSpec,
  ColumnFormat,
  DataExportConfig,
  DataSource,
  ExportSpec,
  FilterCondition,
  PreviewResponse,
} from '@/types';
import PreviewGrid, { type ColumnAction } from './PreviewGrid';
import StepsPanel, { type Step } from './StepsPanel';
import {
  CalculatedColumnDialog,
  FilterDialog,
  FormatDialog,
  GroupDialog,
  RenameDialog,
  aggLabelFor,
  operatorLabel,
  type FieldOption,
} from './dialogs';

const EMPTY_SPEC: ExportSpec = {
  data_source: '',
  columns: [],
  custom_columns: [],
  filters: [],
  group_by: [],
  aggregations: [],
  column_aliases: {},
  column_formats: {},
  sorts: [],
  date_preset: null,
  date_from: null,
  date_to: null,
  output_format: 'csv',
  row_limit: null,
  name_format: 'first_last',
};

const PERIODS: { value: string; label: string }[] = [
  { value: '', label: 'All time' },
  { value: 'this_week', label: 'This week' },
  { value: 'last_week', label: 'Last week' },
  { value: 'this_month', label: 'This month' },
  { value: 'last_month', label: 'Last month' },
  { value: 'last_7_days', label: 'Last 7 days' },
  { value: 'last_30_days', label: 'Last 30 days' },
  { value: 'last_90_days', label: 'Last 90 days' },
  { value: 'this_quarter', label: 'This quarter' },
  { value: 'year_to_date', label: 'Year so far' },
  { value: 'this_year', label: 'This year' },
  { value: 'custom', label: 'Exact dates…' },
];

type DialogState =
  | { kind: 'filter'; field: FieldOption; existing?: FilterCondition }
  | { kind: 'format'; field: FieldOption }
  | { kind: 'rename'; field: FieldOption }
  | { kind: 'group' }
  | { kind: 'calc'; existing?: { name: string; formula: string } }
  | null;

export default function ExportBuilder() {
  const { showToast } = useToast();
  const queryClient = useQueryClient();

  const [spec, setSpec] = useState<ExportSpec>(EMPTY_SPEC);
  const [reportName, setReportName] = useState('');
  const [loadedConfigId, setLoadedConfigId] = useState<number | null>(null);
  const [dialog, setDialog] = useState<DialogState>(null);
  const [showPicker, setShowPicker] = useState(true);
  const [downloading, setDownloading] = useState(false);

  const { data: sources, isLoading: sourcesLoading, isError: sourcesError, refetch: refetchSources } =
    useQuery<DataSource[]>({ queryKey: ['export-sources'], queryFn: () => api.getDataSources() });

  const { data: configs } = useQuery<DataExportConfig[]>({
    queryKey: ['export-configs'],
    queryFn: () => api.getExportConfigs(),
  });

  // ── Field catalogue ────────────────────────────────────────────
  // One flat list of everything selectable, already namespaced when more than
  // one source is in play, so the rest of the component never has to care which
  // mode it is in.
  const [activeSources, setActiveSources] = useState<string[]>([]);

  const allFields: FieldOption[] = useMemo(() => {
    if (!sources) return [];
    const multi = activeSources.length > 1;
    const out: FieldOption[] = [];
    for (const key of activeSources) {
      const src = sources.find((s) => s.key === key);
      if (!src) continue;
      for (const c of src.columns) {
        out.push({
          key: multi ? `${key}.${c.key}` : c.key,
          label: multi ? `${src.label} > ${c.label}` : c.label,
          type: c.type,
        });
      }
    }
    // Calculated columns are selectable everywhere a real column is.
    for (const cc of spec.custom_columns) {
      out.push({ key: cc.name, label: cc.name, type: 'string' });
    }
    return out;
  }, [sources, activeSources, spec.custom_columns]);

  const fieldByKey = useCallback(
    (key: string): FieldOption =>
      allFields.find((f) => f.key === key) || { key, label: key, type: 'string' },
    [allFields]
  );

  // ── Live preview ───────────────────────────────────────────────
  const ready = spec.data_source !== '' && (spec.columns.length > 0 || spec.group_by.length > 0);
  const previewKey = JSON.stringify(spec);
  const [debouncedKey, setDebouncedKey] = useState(previewKey);
  useEffect(() => {
    const t = setTimeout(() => setDebouncedKey(previewKey), 350);
    return () => clearTimeout(t);
  }, [previewKey]);

  const {
    data: preview,
    isFetching: previewLoading,
    isError: previewError,
    error: previewErrObj,
    refetch: refetchPreview,
  } = useQuery<PreviewResponse>({
    queryKey: ['export-preview', debouncedKey],
    queryFn: () => api.previewExport({ ...spec, limit: 50 }),
    enabled: ready,
    retry: false,
  });

  // Distinct values per column, so a filter can offer real choices instead of
  // asking someone to remember what is in the data.
  const samplesFor = useCallback(
    (key: string) => {
      const seen = new Set<string>();
      for (const r of preview?.rows || []) {
        const v = r[key];
        if (v !== null && v !== undefined && String(v) !== '') seen.add(String(v));
        if (seen.size >= 8) break;
      }
      return Array.from(seen);
    },
    [preview]
  );

  // ── Mutations ──────────────────────────────────────────────────
  const patch = (p: Partial<ExportSpec>) => setSpec((s) => ({ ...s, ...p }));

  const chooseSource = (key: string) => {
    const src = sources?.find((s) => s.key === key);
    if (!src) return;
    const next = activeSources.includes(key)
      ? activeSources.filter((k) => k !== key)
      : [...activeSources, key];
    setActiveSources(next);

    if (next.length === 0) {
      setSpec({ ...EMPTY_SPEC });
      return;
    }
    // Start with a handful of columns so there is something to look at
    // immediately rather than an empty grid and an instruction.
    const multi = next.length > 1;
    const cols: string[] = [];
    for (const k of next) {
      const s = sources?.find((x) => x.key === k);
      if (!s) continue;
      for (const c of s.columns.slice(0, multi ? 3 : 6)) {
        cols.push(multi ? `${k}.${c.key}` : c.key);
      }
    }
    setSpec({
      ...EMPTY_SPEC,
      data_source: multi ? 'multi' : next[0],
      columns: cols,
      output_format: spec.output_format,
    });
    // Collapse once something is chosen: the picker is a ten-card grid, and
    // leaving it open pushes the data — the thing the page exists for — below
    // the fold. It stays one tap away.
    setShowPicker(false);
  };

  const removeColumn = (key: string) =>
    patch({
      columns: spec.columns.filter((c) => c !== key),
      custom_columns: spec.custom_columns.filter((c) => c.name !== key),
      sorts: spec.sorts.filter((s) => s.column !== key),
      filters: spec.filters.filter((f) => f.column !== key),
    });

  const setSort = (key: string, direction: 'asc' | 'desc') =>
    patch({ sorts: [{ column: key, direction }, ...spec.sorts.filter((s) => s.column !== key)] });

  const moveColumn = (key: string, delta: number) => {
    const i = spec.columns.indexOf(key);
    if (i < 0) return;
    const j = Math.max(0, Math.min(spec.columns.length - 1, i + delta));
    const next = [...spec.columns];
    next.splice(i, 1);
    next.splice(j, 0, key);
    patch({ columns: next });
  };

  const saveMutation = useMutation({
    mutationFn: async () => {
      const body = { ...spec, name: reportName.trim(), description: undefined };
      if (loadedConfigId) return api.updateExportConfig(loadedConfigId, body);
      return api.createExportConfig(body);
    },
    onSuccess: (cfg) => {
      setLoadedConfigId(cfg.id);
      queryClient.invalidateQueries({ queryKey: ['export-configs'] });
      showToast('Report saved.', 'success');
    },
    onError: (e: unknown) =>
      showToast(e instanceof Error ? e.message : 'Could not save the report.', 'error'),
  });

  const loadConfig = async (id: number) => {
    try {
      const cfg = await api.getExportConfig(id);
      const srcKeys =
        cfg.data_source === 'multi'
          ? Array.from(new Set((cfg.columns || []).map((c) => c.split('.')[0])))
          : [cfg.data_source];
      setActiveSources(srcKeys);
      setReportName(cfg.name);
      setLoadedConfigId(cfg.id);
      setShowPicker(false);
      setSpec({
        data_source: cfg.data_source,
        columns: cfg.columns || [],
        custom_columns: cfg.custom_columns || [],
        filters: cfg.filters || [],
        group_by: cfg.group_by || [],
        aggregations: cfg.aggregations || [],
        column_aliases: cfg.column_aliases || {},
        column_formats: cfg.column_formats || {},
        sorts: cfg.sorts || [],
        date_preset: (cfg.date_preset as ExportSpec['date_preset']) || null,
        date_from: cfg.date_from || null,
        date_to: cfg.date_to || null,
        output_format: (cfg.output_format as 'csv' | 'xlsx') || 'csv',
        row_limit: cfg.row_limit ?? null,
        name_format: cfg.name_format || 'first_last',
      });
    } catch (e) {
      showToast(e instanceof Error ? e.message : 'Could not open that report.', 'error');
    }
  };

  const download = async (format: 'csv' | 'xlsx') => {
    setDownloading(true);
    try {
      const blob = await api.exportData({ ...spec, output_format: format });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${(reportName || spec.data_source || 'report').replace(/\s+/g, '_')}.${format}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      showToast(e instanceof Error ? e.message : 'Download failed.', 'error');
    } finally {
      setDownloading(false);
    }
  };

  // ── Column menu ────────────────────────────────────────────────
  const actionsFor = useCallback(
    (key: string): ColumnAction[] => {
      const field = fieldByKey(key);
      const grouped = spec.group_by.length > 0;
      const acts: ColumnAction[] = [
        {
          key: 'asc',
          label: 'Sort A to Z (smallest first)',
          onSelect: () => setSort(key, 'asc'),
        },
        {
          key: 'desc',
          label: 'Sort Z to A (largest first)',
          onSelect: () => setSort(key, 'desc'),
        },
        {
          key: 'filter',
          label: 'Filter on this column…',
          hint: 'Keep only rows that match',
          onSelect: () =>
            setDialog({
              kind: 'filter',
              field,
              existing: spec.filters.find((f) => f.column === key),
            }),
        },
        {
          key: 'rename',
          label: 'Rename this column…',
          onSelect: () => setDialog({ kind: 'rename', field }),
        },
        {
          key: 'format',
          label: 'Change how it looks…',
          hint: 'Dates, decimals, letter case',
          onSelect: () => setDialog({ kind: 'format', field }),
        },
      ];
      if (!grouped) {
        acts.push(
          { key: 'left', label: 'Move left', onSelect: () => moveColumn(key, -1) },
          { key: 'right', label: 'Move right', onSelect: () => moveColumn(key, 1) },
          {
            key: 'group',
            label: 'Summarise by this column…',
            hint: 'One row per value, with totals',
            onSelect: () => {
              patch({ group_by: [key] });
              setDialog({ kind: 'group' });
            },
          },
          { key: 'remove', label: 'Remove this column', danger: true, onSelect: () => removeColumn(key) }
        );
      }
      return acts;
    },
    [spec, fieldByKey] // eslint-disable-line react-hooks/exhaustive-deps
  );

  const markersFor = useCallback(
    (key: string) => {
      const m: string[] = [];
      if (spec.filters.some((f) => f.column === key)) m.push('filtered');
      const s = spec.sorts.find((x) => x.column === key);
      if (s) m.push(s.direction === 'asc' ? '↑' : '↓');
      if (spec.column_aliases[key]) m.push('renamed');
      if (spec.column_formats[key]) m.push('formatted');
      return m;
    },
    [spec]
  );

  // ── Steps, in words ────────────────────────────────────────────
  const steps: Step[] = useMemo(() => {
    const out: Step[] = [];
    if (activeSources.length && sources) {
      const names = activeSources.map((k) => sources.find((s) => s.key === k)?.label || k);
      out.push({
        id: 'source',
        kind: 'source',
        text:
          names.length > 1
            ? `Start with ${names.join(' and ')}, matched up by employee and date`
            : `Start with ${names[0]}`,
        onEdit: () => setShowPicker(true),
      });
    }
    if (spec.date_preset) {
      const label = PERIODS.find((p) => p.value === spec.date_preset)?.label || spec.date_preset;
      const resolved =
        preview?.resolved_date_from && preview?.resolved_date_to
          ? ` (${preview.resolved_date_from} to ${preview.resolved_date_to})`
          : '';
      out.push({
        id: 'period',
        kind: 'period',
        text: `Only ${label.toLowerCase()}${resolved}`,
        onRemove: () => patch({ date_preset: null, date_from: null, date_to: null }),
      });
    }
    spec.filters.forEach((f, i) => {
      const field = fieldByKey(f.column);
      const val = Array.isArray(f.value) ? f.value.join(' and ') : String(f.value ?? '');
      out.push({
        id: `filter-${i}`,
        kind: 'filter',
        text: `Only rows where ${field.label} ${operatorLabel(f.operator)}${val ? ` ${val}` : ''}`,
        onEdit: () => setDialog({ kind: 'filter', field, existing: f }),
        onRemove: () => patch({ filters: spec.filters.filter((_, ix) => ix !== i) }),
      });
    });
    spec.custom_columns.forEach((cc, i) => {
      out.push({
        id: `calc-${i}`,
        kind: 'column',
        text: `Work out a column called “${cc.name}”`,
        onEdit: () => setDialog({ kind: 'calc', existing: cc }),
        onRemove: () =>
          patch({ custom_columns: spec.custom_columns.filter((_, ix) => ix !== i) }),
      });
    });
    if (spec.group_by.length) {
      const groupNames = spec.group_by.map((g) => fieldByKey(g).label).join(' and ');
      const figures = spec.aggregations.map((a) => aggLabelFor(a, allFields)).join(', ');
      out.push({
        id: 'group',
        kind: 'group',
        text: `One row per ${groupNames}, showing ${figures || 'a row count'}`,
        onEdit: () => setDialog({ kind: 'group' }),
        onRemove: () => patch({ group_by: [], aggregations: [] }),
      });
    }
    spec.sorts.forEach((s, i) => {
      out.push({
        id: `sort-${i}`,
        kind: 'sort',
        text: `Order by ${fieldByKey(s.column).label}, ${s.direction === 'asc' ? 'smallest first' : 'largest first'}`,
        onRemove: () => patch({ sorts: spec.sorts.filter((_, ix) => ix !== i) }),
      });
    });
    Object.entries(spec.column_aliases).forEach(([k, v]) => {
      out.push({
        id: `alias-${k}`,
        kind: 'rename',
        text: `Call ${fieldByKey(k).label} “${v}” in the file`,
        onRemove: () => {
          const next = { ...spec.column_aliases };
          delete next[k];
          patch({ column_aliases: next });
        },
      });
    });
    Object.keys(spec.column_formats).forEach((k) => {
      out.push({
        id: `fmt-${k}`,
        kind: 'format',
        text: `Change how ${fieldByKey(k).label} is displayed`,
        onEdit: () => setDialog({ kind: 'format', field: fieldByKey(k) }),
        onRemove: () => {
          const next = { ...spec.column_formats };
          delete next[k];
          patch({ column_formats: next });
        },
      });
    });
    return out;
  }, [spec, sources, activeSources, preview, fieldByKey, allFields]);

  // ── Render ─────────────────────────────────────────────────────
  if (sourcesError) {
    return (
      <ErrorMessage
        message="Could not load the list of available data. This is a loading failure, not an empty account."
        onRetry={() => refetchSources()}
      />
    );
  }

  const grouped = spec.group_by.length > 0;

  return (
    <div className="space-y-4">
      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-2 rounded-xl border border-gray-200 bg-white px-4 py-3">
        <input
          value={reportName}
          onChange={(e) => setReportName(e.target.value)}
          placeholder="Name this report"
          className="min-h-[44px] flex-1 rounded-lg border border-gray-300 px-3 text-sm font-medium text-gray-900 sm:max-w-xs"
        />
        <select
          value={loadedConfigId ?? ''}
          onChange={(e) => (e.target.value ? loadConfig(Number(e.target.value)) : null)}
          className="min-h-[44px] rounded-lg border border-gray-300 px-3 text-sm text-gray-800"
          aria-label="Open a saved report"
        >
          <option value="">Open a saved report…</option>
          {(configs || []).map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
        <div className="ml-auto flex flex-wrap gap-2">
          <button
            type="button"
            disabled={!ready || !reportName.trim() || saveMutation.isPending}
            onClick={() => saveMutation.mutate()}
            className="min-h-[44px] rounded-lg border border-gray-300 px-4 text-sm font-medium text-gray-800 hover:bg-gray-50 disabled:opacity-50"
          >
            {saveMutation.isPending ? 'Saving…' : loadedConfigId ? 'Save changes' : 'Save report'}
          </button>
          <button
            type="button"
            disabled={!ready || downloading}
            onClick={() => download('xlsx')}
            className="min-h-[44px] rounded-lg bg-purple-600 px-4 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
          >
            {downloading ? 'Preparing…' : 'Download Excel'}
          </button>
          <button
            type="button"
            disabled={!ready || downloading}
            onClick={() => download('csv')}
            className="min-h-[44px] rounded-lg border border-gray-300 px-4 text-sm font-medium text-gray-800 hover:bg-gray-50 disabled:opacity-50"
          >
            CSV
          </button>
        </div>
      </div>

      {/* min-w-0 is load-bearing. A grid item defaults to min-width:auto, so the
          wide preview table forces the whole column to its own width and drags
          the toolbar and headings off the right of a phone screen with it. */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
        <div className="min-w-0 space-y-4">
          {/* Source picker */}
          <div className="rounded-xl border border-gray-200 bg-white">
            <button
              type="button"
              onClick={() => setShowPicker((v) => !v)}
              className="flex w-full min-h-[44px] items-center justify-between px-4 py-3 text-left"
              aria-expanded={showPicker}
            >
              <span>
                <span className="text-sm font-semibold text-gray-900">What do you want to report on?</span>
                {activeSources.length > 0 && (
                  <span className="ml-2 text-sm text-gray-600">
                    {activeSources.length} selected
                  </span>
                )}
              </span>
              <span className="text-sm text-purple-700">{showPicker ? 'Hide' : 'Change'}</span>
            </button>
            {showPicker && (
              <div className="border-t border-gray-200 p-4">
                {sourcesLoading ? (
                  <p className="text-sm text-gray-600">Loading…</p>
                ) : (
                  <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                    {(sources || []).map((s) => {
                      const on = activeSources.includes(s.key);
                      return (
                        <button
                          key={s.key}
                          type="button"
                          onClick={() => chooseSource(s.key)}
                          aria-pressed={on}
                          className={`rounded-lg border p-3 text-left transition-colors ${
                            on ? 'border-purple-500 bg-purple-50' : 'border-gray-200 hover:bg-gray-50'
                          }`}
                        >
                          <span className="block text-sm font-medium text-gray-900">{s.label}</span>
                          <span className="mt-0.5 block text-xs text-gray-600">{s.description}</span>
                        </button>
                      );
                    })}
                  </div>
                )}
                {activeSources.length > 1 && (
                  <p className="mt-3 rounded-lg bg-blue-50 px-3 py-2 text-xs text-blue-900">
                    Rows from these are matched up by employee, and by date where both have one.
                  </p>
                )}
              </div>
            )}
          </div>

          {/* Period + add controls */}
          {ready && (
            <div className="flex flex-wrap items-center gap-2 rounded-xl border border-gray-200 bg-white px-4 py-3">
              <label className="flex items-center gap-2 text-sm text-gray-800">
                Period
                <select
                  value={spec.date_preset || ''}
                  onChange={(e) =>
                    patch({
                      date_preset: (e.target.value || null) as ExportSpec['date_preset'],
                      date_from: null,
                      date_to: null,
                    })
                  }
                  className="min-h-[44px] rounded-lg border border-gray-300 px-2 text-sm"
                >
                  {PERIODS.map((p) => (
                    <option key={p.value} value={p.value}>
                      {p.label}
                    </option>
                  ))}
                </select>
              </label>
              {spec.date_preset === 'custom' && (
                <>
                  <input
                    type="date"
                    value={spec.date_from || ''}
                    onChange={(e) => patch({ date_from: e.target.value || null })}
                    className="min-h-[44px] rounded-lg border border-gray-300 px-2 text-sm"
                    aria-label="From date"
                  />
                  <input
                    type="date"
                    value={spec.date_to || ''}
                    onChange={(e) => patch({ date_to: e.target.value || null })}
                    className="min-h-[44px] rounded-lg border border-gray-300 px-2 text-sm"
                    aria-label="To date"
                  />
                </>
              )}
              <button
                type="button"
                onClick={() => setDialog({ kind: 'group' })}
                className="min-h-[44px] rounded-lg border border-gray-300 px-3 text-sm font-medium text-gray-800 hover:bg-gray-50"
              >
                {grouped ? 'Change summary' : 'Summarise…'}
              </button>
              <button
                type="button"
                onClick={() => setDialog({ kind: 'calc' })}
                className="min-h-[44px] rounded-lg border border-gray-300 px-3 text-sm font-medium text-gray-800 hover:bg-gray-50"
              >
                Add a calculated column…
              </button>
              {!grouped && (
                <AddColumnMenu
                  fields={allFields.filter((f) => !spec.columns.includes(f.key))}
                  onPick={(k) => patch({ columns: [...spec.columns, k] })}
                />
              )}
            </div>
          )}

          <PreviewGrid
            columns={preview?.column_headers || []}
            rows={preview?.rows || []}
            total={preview?.total ?? 0}
            returned={preview?.returned ?? 0}
            isLoading={previewLoading}
            isError={previewError}
            errorMessage={previewErrObj instanceof Error ? previewErrObj.message : undefined}
            onRetry={() => refetchPreview()}
            actionsFor={actionsFor}
            markersFor={markersFor}
            emptyHint={
              activeSources.length === 0
                ? 'Choose what you want to report on above and the data appears here immediately.'
                : undefined
            }
          />
        </div>

        {steps.length > 0 && <StepsPanel steps={steps} />}
      </div>

      {/* Dialogs */}
      {dialog?.kind === 'filter' && (
        <FilterDialog
          field={dialog.field}
          existing={dialog.existing}
          sampleValues={samplesFor(dialog.field.key)}
          onClose={() => setDialog(null)}
          onSave={(f) => {
            patch({
              filters: [...spec.filters.filter((x) => x.column !== f.column), f],
            });
            setDialog(null);
          }}
        />
      )}
      {dialog?.kind === 'format' && (
        <FormatDialog
          field={dialog.field}
          existing={spec.column_formats[dialog.field.key]}
          onClose={() => setDialog(null)}
          onSave={(f) => {
            const next: Record<string, ColumnFormat> = { ...spec.column_formats };
            if (f) next[dialog.field.key] = f;
            else delete next[dialog.field.key];
            patch({ column_formats: next });
            setDialog(null);
          }}
        />
      )}
      {dialog?.kind === 'rename' && (
        <RenameDialog
          field={dialog.field}
          current={spec.column_aliases[dialog.field.key]}
          onClose={() => setDialog(null)}
          onSave={(name) => {
            const next = { ...spec.column_aliases };
            if (name) next[dialog.field.key] = name;
            else delete next[dialog.field.key];
            patch({ column_aliases: next });
            setDialog(null);
          }}
        />
      )}
      {dialog?.kind === 'group' && (
        <GroupDialog
          fields={allFields}
          groupBy={spec.group_by}
          aggregations={spec.aggregations}
          onClose={() => setDialog(null)}
          onSave={(g, a) => {
            patch({ group_by: g, aggregations: a as AggregationSpec[], sorts: [] });
            setDialog(null);
          }}
        />
      )}
      {dialog?.kind === 'calc' && (
        <CalculatedColumnDialog
          fields={allFields}
          existing={dialog.existing}
          onClose={() => setDialog(null)}
          onSave={(name, formula) => {
            const others = spec.custom_columns.filter((c) => c.name !== dialog.existing?.name);
            patch({ custom_columns: [...others, { name, formula }] });
            setDialog(null);
          }}
        />
      )}
    </div>
  );
}

function AddColumnMenu({
  fields,
  onPick,
}: {
  fields: FieldOption[];
  onPick: (key: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState('');
  const shown = fields.filter((f) => f.label.toLowerCase().includes(q.toLowerCase()));
  if (fields.length === 0) return null;
  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="min-h-[44px] rounded-lg border border-gray-300 px-3 text-sm font-medium text-gray-800 hover:bg-gray-50"
      >
        Add a column…
      </button>
      {open && (
        <div className="absolute right-0 z-40 mt-1 w-72 rounded-lg border border-gray-200 bg-white p-2 shadow-xl">
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search columns"
            className="mb-2 w-full min-h-[44px] rounded-lg border border-gray-300 px-3 text-sm"
            autoFocus
          />
          <div className="max-h-64 overflow-y-auto">
            {shown.map((f) => (
              <button
                key={f.key}
                type="button"
                onClick={() => {
                  onPick(f.key);
                  setOpen(false);
                  setQ('');
                }}
                className="flex w-full min-h-[40px] items-center justify-between gap-2 rounded px-2 text-left text-sm text-gray-800 hover:bg-gray-50"
              >
                <span className="truncate">{f.label}</span>
                <span className="flex-shrink-0 text-xs text-gray-500">{f.type}</span>
              </button>
            ))}
            {shown.length === 0 && <p className="px-2 py-3 text-sm text-gray-600">No matches.</p>}
          </div>
        </div>
      )}
    </div>
  );
}
