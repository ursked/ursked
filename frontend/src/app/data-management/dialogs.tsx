'use client';

import React, { useMemo, useState } from 'react';
import type {
  AggregateFunc,
  AggregationSpec,
  ColumnFormat,
  FilterCondition,
} from '@/types';

/** A column the user can pick, already carrying its plain-English name. */
export interface FieldOption {
  key: string;
  label: string;
  type: string; // string | number | date | time | datetime
}

// ── Shell ────────────────────────────────────────────────────────────

export function Dialog({
  title,
  subtitle,
  onClose,
  children,
  footer,
}: {
  title: string;
  subtitle?: string;
  onClose: () => void;
  children: React.ReactNode;
  footer?: React.ReactNode;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 p-0 sm:items-center sm:p-4"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="max-h-[92vh] w-full overflow-y-auto rounded-t-2xl bg-white shadow-2xl sm:max-w-lg sm:rounded-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="border-b border-gray-200 px-5 py-4">
          <h2 className="text-base font-semibold text-gray-900">{title}</h2>
          {subtitle && <p className="mt-1 text-sm text-gray-600">{subtitle}</p>}
        </div>
        <div className="space-y-4 px-5 py-4">{children}</div>
        <div className="flex justify-end gap-2 border-t border-gray-200 px-5 py-3">
          <button
            type="button"
            onClick={onClose}
            className="min-h-[44px] rounded-lg border border-gray-300 px-4 text-sm font-medium text-gray-700 hover:bg-gray-50"
          >
            Cancel
          </button>
          {footer}
        </div>
      </div>
    </div>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return <span className="mb-1 block text-sm font-medium text-gray-800">{children}</span>;
}

const inputClass =
  'w-full min-h-[44px] rounded-lg border border-gray-300 px-3 text-sm text-gray-900 focus:border-purple-500';

// ── Filter ───────────────────────────────────────────────────────────

/**
 * Operators are offered by column TYPE, in words. A non-technical user should
 * never have to know that `gte` exists, and should never be offered "is greater
 * than" on a person's name.
 */
const OPERATORS_BY_TYPE: Record<string, { value: string; label: string }[]> = {
  string: [
    { value: 'eq', label: 'is exactly' },
    { value: 'neq', label: 'is not' },
    { value: 'contains', label: 'contains' },
    { value: 'not_contains', label: 'does not contain' },
    { value: 'starts_with', label: 'starts with' },
    { value: 'ends_with', label: 'ends with' },
    { value: 'in', label: 'is any of' },
    { value: 'not_in', label: 'is none of' },
    { value: 'is_empty', label: 'is blank' },
    { value: 'is_not_empty', label: 'is not blank' },
  ],
  number: [
    { value: 'eq', label: 'equals' },
    { value: 'neq', label: 'does not equal' },
    { value: 'gt', label: 'is more than' },
    { value: 'gte', label: 'is at least' },
    { value: 'lt', label: 'is less than' },
    { value: 'lte', label: 'is at most' },
    { value: 'between', label: 'is between' },
    { value: 'is_empty', label: 'is blank' },
    { value: 'is_not_empty', label: 'is not blank' },
  ],
  date: [
    { value: 'eq', label: 'is on' },
    { value: 'gt', label: 'is after' },
    { value: 'gte', label: 'is on or after' },
    { value: 'lt', label: 'is before' },
    { value: 'lte', label: 'is on or before' },
    { value: 'between', label: 'is between' },
    { value: 'is_empty', label: 'is blank' },
    { value: 'is_not_empty', label: 'is not blank' },
  ],
};

export const NO_VALUE_OPERATORS = new Set(['is_empty', 'is_not_empty']);

export function operatorsFor(type: string) {
  if (type === 'number') return OPERATORS_BY_TYPE.number;
  if (type === 'date' || type === 'datetime' || type === 'time') return OPERATORS_BY_TYPE.date;
  return OPERATORS_BY_TYPE.string;
}

export function operatorLabel(op: string): string {
  for (const list of Object.values(OPERATORS_BY_TYPE)) {
    const found = list.find((o) => o.value === op);
    if (found) return found.label;
  }
  return op;
}

export function FilterDialog({
  field,
  existing,
  sampleValues,
  onSave,
  onClose,
}: {
  field: FieldOption;
  existing?: FilterCondition;
  sampleValues: string[];
  onSave: (f: FilterCondition) => void;
  onClose: () => void;
}) {
  const ops = operatorsFor(field.type);
  const [operator, setOperator] = useState(existing?.operator || ops[0].value);
  const [value, setValue] = useState(
    existing && !Array.isArray(existing.value) ? String(existing.value ?? '') : ''
  );
  const [low, setLow] = useState(
    Array.isArray(existing?.value) ? String(existing?.value?.[0] ?? '') : ''
  );
  const [high, setHigh] = useState(
    Array.isArray(existing?.value) ? String(existing?.value?.[1] ?? '') : ''
  );

  const needsValue = !NO_VALUE_OPERATORS.has(operator);
  const isRange = operator === 'between';
  const inputType = field.type === 'date' ? 'date' : field.type === 'number' ? 'number' : 'text';

  return (
    <Dialog
      title={`Only include rows where ${field.label}…`}
      subtitle="Rows that do not match are left out of the report."
      onClose={onClose}
      footer={
        <button
          type="button"
          onClick={() =>
            onSave({
              column: field.key,
              operator,
              value: isRange ? [low, high] : needsValue ? value : null,
            })
          }
          className="min-h-[44px] rounded-lg bg-purple-600 px-4 text-sm font-medium text-white hover:bg-purple-700"
        >
          Apply filter
        </button>
      }
    >
      <label className="block">
        <Label>Condition</Label>
        <select value={operator} onChange={(e) => setOperator(e.target.value)} className={inputClass}>
          {ops.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </label>

      {isRange && (
        <div className="grid grid-cols-2 gap-3">
          <label className="block">
            <Label>From</Label>
            <input type={inputType} value={low} onChange={(e) => setLow(e.target.value)} className={inputClass} />
          </label>
          <label className="block">
            <Label>To</Label>
            <input type={inputType} value={high} onChange={(e) => setHigh(e.target.value)} className={inputClass} />
          </label>
        </div>
      )}

      {needsValue && !isRange && (
        <label className="block">
          <Label>{operator === 'in' || operator === 'not_in' ? 'Values, separated by commas' : 'Value'}</Label>
          <input
            type={operator === 'in' || operator === 'not_in' ? 'text' : inputType}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            className={inputClass}
            placeholder={operator === 'in' ? 'e.g. scheduled, rest_day' : ''}
          />
          {sampleValues.length > 0 && (
            <span className="mt-2 block text-xs text-gray-600">
              Values in your data:{' '}
              {sampleValues.slice(0, 6).map((v) => (
                <button
                  key={v}
                  type="button"
                  onClick={() => setValue(v)}
                  className="mr-1 rounded border border-gray-300 px-1.5 py-0.5 text-xs text-gray-800 hover:bg-gray-100"
                >
                  {v}
                </button>
              ))}
            </span>
          )}
        </label>
      )}
    </Dialog>
  );
}

// ── Group and summarise ──────────────────────────────────────────────

const AGG_CHOICES: { value: AggregateFunc; label: string; needsColumn: boolean; numeric: boolean }[] = [
  { value: 'count', label: 'How many rows', needsColumn: false, numeric: false },
  { value: 'sum', label: 'Total of', needsColumn: true, numeric: true },
  { value: 'avg', label: 'Average of', needsColumn: true, numeric: true },
  { value: 'min', label: 'Lowest', needsColumn: true, numeric: false },
  { value: 'max', label: 'Highest', needsColumn: true, numeric: false },
  { value: 'count_distinct', label: 'How many different', needsColumn: true, numeric: false },
];

export function aggLabelFor(agg: AggregationSpec, fields: FieldOption[]): string {
  const choice = AGG_CHOICES.find((c) => c.value === agg.func);
  const col = fields.find((f) => f.key === agg.column)?.label || agg.column;
  if (agg.func === 'count') return 'How many rows';
  return `${choice?.label || agg.func} ${col}`;
}

export function GroupDialog({
  fields,
  groupBy,
  aggregations,
  onSave,
  onClose,
}: {
  fields: FieldOption[];
  groupBy: string[];
  aggregations: AggregationSpec[];
  onSave: (groupBy: string[], aggregations: AggregationSpec[]) => void;
  onClose: () => void;
}) {
  const [groups, setGroups] = useState<string[]>(groupBy.length ? groupBy : []);
  const [aggs, setAggs] = useState<AggregationSpec[]>(
    aggregations.length ? aggregations : [{ column: '', func: 'count', output_key: 'count_rows' }]
  );

  const numericFields = fields.filter((f) => f.type === 'number');

  const toggleGroup = (key: string) =>
    setGroups((g) => (g.includes(key) ? g.filter((x) => x !== key) : [...g, key]));

  const setAgg = (i: number, patch: Partial<AggregationSpec>) =>
    setAggs((a) => a.map((x, ix) => (ix === i ? { ...x, ...patch } : x)));

  return (
    <Dialog
      title="Summarise the data"
      subtitle="One row per group, with totals instead of every individual record — the same thing as a pivot table."
      onClose={onClose}
      footer={
        <>
          {groupBy.length > 0 && (
            <button
              type="button"
              onClick={() => onSave([], [])}
              className="min-h-[44px] rounded-lg border border-gray-300 px-4 text-sm font-medium text-gray-700 hover:bg-gray-50"
            >
              Stop summarising
            </button>
          )}
          <button
            type="button"
            disabled={groups.length === 0}
            onClick={() =>
              onSave(
                groups,
                aggs
                  .filter((a) => a.func === 'count' || a.column)
                  .map((a, i) => ({ ...a, output_key: a.output_key || `agg_${i}` }))
              )
            }
            className="min-h-[44px] rounded-lg bg-purple-600 px-4 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
          >
            Summarise
          </button>
        </>
      }
    >
      <div>
        <Label>One row for each…</Label>
        <div className="max-h-44 overflow-y-auto rounded-lg border border-gray-200 p-2">
          {fields.map((f) => (
            <label key={f.key} className="flex min-h-[36px] cursor-pointer items-center gap-2 px-1 text-sm text-gray-800">
              <input
                type="checkbox"
                checked={groups.includes(f.key)}
                onChange={() => toggleGroup(f.key)}
                className="h-4 w-4"
              />
              {f.label}
            </label>
          ))}
        </div>
        {groups.length > 1 && (
          <p className="mt-1 text-xs text-gray-600">
            Picking several gives one row per combination, e.g. per person per month.
          </p>
        )}
      </div>

      <div>
        <Label>And show…</Label>
        <div className="space-y-2">
          {aggs.map((a, i) => {
            const choice = AGG_CHOICES.find((c) => c.value === a.func);
            const options = choice?.numeric ? numericFields : fields;
            return (
              <div key={i} className="flex flex-wrap items-center gap-2">
                <select
                  value={a.func}
                  onChange={(e) => setAgg(i, { func: e.target.value as AggregateFunc })}
                  className="min-h-[44px] flex-1 rounded-lg border border-gray-300 px-2 text-sm"
                >
                  {AGG_CHOICES.map((c) => (
                    <option key={c.value} value={c.value}>
                      {c.label}
                    </option>
                  ))}
                </select>
                {choice?.needsColumn && (
                  <select
                    value={a.column}
                    onChange={(e) => setAgg(i, { column: e.target.value })}
                    className="min-h-[44px] flex-1 rounded-lg border border-gray-300 px-2 text-sm"
                  >
                    <option value="">Choose a column…</option>
                    {options.map((f) => (
                      <option key={f.key} value={f.key}>
                        {f.label}
                      </option>
                    ))}
                  </select>
                )}
                {aggs.length > 1 && (
                  <button
                    type="button"
                    onClick={() => setAggs((x) => x.filter((_, ix) => ix !== i))}
                    className="min-h-[44px] px-2 text-sm text-red-700 hover:underline"
                  >
                    Remove
                  </button>
                )}
              </div>
            );
          })}
        </div>
        <button
          type="button"
          onClick={() =>
            setAggs((a) => [...a, { column: '', func: 'sum', output_key: `agg_${a.length}` }])
          }
          className="mt-2 min-h-[44px] text-sm font-medium text-purple-700 hover:underline"
        >
          + Add another figure
        </button>
      </div>

      <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900">
        Summarising replaces the individual rows. Only the groups above and the figures you choose
        will be in the report.
      </p>
    </Dialog>
  );
}

// ── Formatting ───────────────────────────────────────────────────────

export function FormatDialog({
  field,
  existing,
  onSave,
  onClose,
}: {
  field: FieldOption;
  existing?: ColumnFormat;
  onSave: (f: ColumnFormat | null) => void;
  onClose: () => void;
}) {
  const isDate = field.type === 'date' || field.type === 'datetime';
  const isTime = field.type === 'time';
  const isNumber = field.type === 'number';
  const [pattern, setPattern] = useState(existing?.pattern || (isDate ? 'iso' : '24h'));
  const [decimals, setDecimals] = useState(String(existing?.decimals ?? 0));
  const [thousands, setThousands] = useState(existing?.thousands ?? true);
  const [transform, setTransform] = useState(existing?.transform || 'none');

  const build = (): ColumnFormat | null => {
    if (isDate) return { kind: 'date', pattern };
    if (isTime) return { kind: 'time', pattern };
    if (isNumber)
      return { kind: 'number', decimals: parseInt(decimals, 10) || 0, thousands };
    if (transform === 'none') return null;
    return { kind: 'text', transform };
  };

  return (
    <Dialog
      title={`How should ${field.label} look?`}
      subtitle="Changes the display only — the underlying value is untouched."
      onClose={onClose}
      footer={
        <>
          {existing && (
            <button
              type="button"
              onClick={() => onSave(null)}
              className="min-h-[44px] rounded-lg border border-gray-300 px-4 text-sm font-medium text-gray-700 hover:bg-gray-50"
            >
              Reset
            </button>
          )}
          <button
            type="button"
            onClick={() => onSave(build())}
            className="min-h-[44px] rounded-lg bg-purple-600 px-4 text-sm font-medium text-white hover:bg-purple-700"
          >
            Apply
          </button>
        </>
      }
    >
      {isDate && (
        <label className="block">
          <Label>Date style</Label>
          <select value={pattern} onChange={(e) => setPattern(e.target.value)} className={inputClass}>
            <option value="iso">2026-09-06</option>
            <option value="dmy">06/09/2026</option>
            <option value="mdy">09/06/2026</option>
            <option value="long">06 September 2026</option>
            <option value="day_month">06 Sep</option>
            <option value="weekday">Sun 06 Sep</option>
            <option value="month_year">September 2026</option>
          </select>
        </label>
      )}
      {isTime && (
        <label className="block">
          <Label>Time style</Label>
          <select value={pattern} onChange={(e) => setPattern(e.target.value)} className={inputClass}>
            <option value="24h">14:30</option>
            <option value="12h">2:30 PM</option>
          </select>
        </label>
      )}
      {isNumber && (
        <>
          <label className="block">
            <Label>Decimal places</Label>
            <select value={decimals} onChange={(e) => setDecimals(e.target.value)} className={inputClass}>
              <option value="0">0 — 1235</option>
              <option value="1">1 — 1234.5</option>
              <option value="2">2 — 1234.50</option>
            </select>
          </label>
          <label className="flex min-h-[44px] cursor-pointer items-center gap-2 text-sm text-gray-800">
            <input type="checkbox" checked={thousands} onChange={(e) => setThousands(e.target.checked)} className="h-4 w-4" />
            Group thousands with commas (1,234)
          </label>
        </>
      )}
      {!isDate && !isTime && !isNumber && (
        <label className="block">
          <Label>Letter case</Label>
          <select value={transform} onChange={(e) => setTransform(e.target.value)} className={inputClass}>
            <option value="none">Leave as it is</option>
            <option value="upper">UPPERCASE</option>
            <option value="lower">lowercase</option>
            <option value="title">Title Case</option>
          </select>
        </label>
      )}
    </Dialog>
  );
}

// ── Rename ───────────────────────────────────────────────────────────

export function RenameDialog({
  field,
  current,
  onSave,
  onClose,
}: {
  field: FieldOption;
  current?: string;
  onSave: (name: string | null) => void;
  onClose: () => void;
}) {
  const [name, setName] = useState(current || field.label);
  return (
    <Dialog
      title="Rename this column"
      subtitle="This is the heading people will see in the file."
      onClose={onClose}
      footer={
        <>
          {current && (
            <button
              type="button"
              onClick={() => onSave(null)}
              className="min-h-[44px] rounded-lg border border-gray-300 px-4 text-sm font-medium text-gray-700 hover:bg-gray-50"
            >
              Use original
            </button>
          )}
          <button
            type="button"
            onClick={() => onSave(name.trim() || null)}
            className="min-h-[44px] rounded-lg bg-purple-600 px-4 text-sm font-medium text-white hover:bg-purple-700"
          >
            Rename
          </button>
        </>
      }
    >
      <label className="block">
        <Label>Column heading</Label>
        <input value={name} onChange={(e) => setName(e.target.value)} className={inputClass} autoFocus />
        <span className="mt-1 block text-xs text-gray-600">Originally “{field.label}”.</span>
      </label>
    </Dialog>
  );
}

// ── Calculated column ────────────────────────────────────────────────

/**
 * The formula box used to be a bare text input expecting
 * `CONCAT({first_name}, " ", {last_name})` with `#ERROR` in the cells when it
 * went wrong. Here the shapes are offered as recipes, columns are inserted by
 * clicking them, and the formula text is still shown so anyone who wants the
 * real thing can see and edit it.
 */
const RECIPES: { key: string; label: string; hint: string; build: (cols: string[]) => string }[] = [
  {
    key: 'join',
    label: 'Join two columns together',
    hint: 'e.g. first name and last name in one cell',
    build: (c) => `CONCAT({${c[0] || 'column_a'}}, " ", {${c[1] || 'column_b'}})`,
  },
  {
    key: 'add',
    label: 'Add two columns',
    hint: 'e.g. paid break plus unpaid break',
    build: (c) => `{${c[0] || 'column_a'}} + {${c[1] || 'column_b'}}`,
  },
  {
    key: 'subtract',
    label: 'Subtract one column from another',
    hint: 'e.g. hours worked minus contracted hours',
    build: (c) => `{${c[0] || 'column_a'}} - {${c[1] || 'column_b'}}`,
  },
  {
    key: 'divide60',
    label: 'Convert minutes to hours',
    hint: 'divides by 60 and rounds to 2 decimals',
    build: (c) => `ROUND({${c[0] || 'column_a'}} / 60, 2)`,
  },
  {
    key: 'ifelse',
    label: 'Label rows by a condition',
    hint: 'e.g. write “Late” when tardiness is above zero',
    build: (c) => `IF({${c[0] || 'column_a'}} > 0, "Yes", "No")`,
  },
  {
    key: 'month',
    label: 'Take the month from a date',
    hint: 'useful for grouping by month afterwards',
    build: (c) => `MONTH({${c[0] || 'column_a'}})`,
  },
  {
    key: 'upper',
    label: 'Make text uppercase',
    hint: '',
    build: (c) => `UPPER({${c[0] || 'column_a'}})`,
  },
  { key: 'blank', label: 'Write it myself', hint: 'full formula syntax', build: () => '' },
];

export function CalculatedColumnDialog({
  fields,
  existing,
  onSave,
  onClose,
}: {
  fields: FieldOption[];
  existing?: { name: string; formula: string };
  onSave: (name: string, formula: string) => void;
  onClose: () => void;
}) {
  const [name, setName] = useState(existing?.name || '');
  const [formula, setFormula] = useState(existing?.formula || '');
  const [picked, setPicked] = useState<string[]>([]);
  const [recipe, setRecipe] = useState<string>(existing ? 'blank' : '');

  const applyRecipe = (key: string, cols: string[]) => {
    const r = RECIPES.find((x) => x.key === key);
    if (!r) return;
    setFormula(r.build(cols));
  };

  const toggleColumn = (key: string) => {
    const next = picked.includes(key) ? picked.filter((k) => k !== key) : [...picked, key].slice(-2);
    setPicked(next);
    if (recipe && recipe !== 'blank') applyRecipe(recipe, next);
  };

  const valid = name.trim().length > 0 && formula.trim().length > 0;

  return (
    <Dialog
      title="Add a calculated column"
      subtitle="A new column worked out from the ones you already have."
      onClose={onClose}
      footer={
        <button
          type="button"
          disabled={!valid}
          onClick={() => onSave(name.trim(), formula.trim())}
          className="min-h-[44px] rounded-lg bg-purple-600 px-4 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
        >
          Add column
        </button>
      }
    >
      <label className="block">
        <Label>What should this column be called?</Label>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          className={inputClass}
          placeholder="e.g. Overtime hours"
        />
      </label>

      <div>
        <Label>What should it work out?</Label>
        <div className="space-y-1">
          {RECIPES.map((r) => (
            <button
              key={r.key}
              type="button"
              onClick={() => {
                setRecipe(r.key);
                applyRecipe(r.key, picked);
              }}
              className={`flex w-full flex-col items-start rounded-lg border px-3 py-2 text-left ${
                recipe === r.key ? 'border-purple-500 bg-purple-50' : 'border-gray-200 hover:bg-gray-50'
              }`}
            >
              <span className="text-sm font-medium text-gray-900">{r.label}</span>
              {r.hint && <span className="text-xs text-gray-600">{r.hint}</span>}
            </button>
          ))}
        </div>
      </div>

      {recipe && recipe !== 'blank' && (
        <div>
          <Label>Using which columns? (pick up to two, in order)</Label>
          <div className="max-h-40 overflow-y-auto rounded-lg border border-gray-200 p-2">
            {fields.map((f) => (
              <label key={f.key} className="flex min-h-[36px] cursor-pointer items-center gap-2 px-1 text-sm text-gray-800">
                <input
                  type="checkbox"
                  checked={picked.includes(f.key)}
                  onChange={() => toggleColumn(f.key)}
                  className="h-4 w-4"
                />
                {f.label}
                <span className="ml-auto text-xs text-gray-500">{f.type}</span>
              </label>
            ))}
          </div>
        </div>
      )}

      <label className="block">
        <Label>Formula</Label>
        <textarea
          value={formula}
          onChange={(e) => setFormula(e.target.value)}
          rows={2}
          className="w-full rounded-lg border border-gray-300 px-3 py-2 font-mono text-sm text-gray-900"
          placeholder="Pick a recipe above, or type a formula"
        />
        <span className="mt-1 block text-xs text-gray-600">
          Column names go in curly braces. Available: CONCAT, UPPER, LOWER, IF, ROUND, YEAR, MONTH,
          and + − × ÷.
        </span>
      </label>
    </Dialog>
  );
}
