'use client';

import React from 'react';

export interface Step {
  id: string;
  /** Plain English, e.g. "Only rows where Status is rest_day". */
  text: string;
  /** What kind of thing this is, shown as a small tag. */
  kind: 'source' | 'period' | 'filter' | 'group' | 'sort' | 'column' | 'format' | 'rename';
  onEdit?: () => void;
  onRemove?: () => void;
}

const KIND_LABEL: Record<Step['kind'], string> = {
  source: 'Data',
  period: 'Period',
  filter: 'Filter',
  group: 'Summary',
  sort: 'Order',
  column: 'Column',
  format: 'Format',
  rename: 'Renamed',
};

const KIND_TONE: Record<Step['kind'], string> = {
  source: 'bg-gray-100 text-gray-700',
  period: 'bg-blue-100 text-blue-800',
  filter: 'bg-amber-100 text-amber-900',
  group: 'bg-purple-100 text-purple-800',
  sort: 'bg-teal-100 text-teal-900',
  column: 'bg-gray-100 text-gray-700',
  format: 'bg-gray-100 text-gray-700',
  rename: 'bg-gray-100 text-gray-700',
};

/**
 * Everything currently applied, in the order it happens, in words.
 *
 * This is the part that replaces "read the form and hope": a person can check
 * what the report does by reading a list of sentences, and undo any one of them
 * without unpicking the rest.
 */
export default function StepsPanel({ steps }: { steps: Step[] }) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white">
      <div className="border-b border-gray-200 px-4 py-3">
        <h2 className="text-sm font-semibold text-gray-900">What this report does</h2>
        <p className="mt-0.5 text-xs text-gray-600">Applied in this order. Remove any step to undo it.</p>
      </div>
      <ol className="divide-y divide-gray-100">
        {steps.map((s, i) => (
          <li key={s.id} className="flex items-start gap-2 px-4 py-2.5">
            <span className="mt-0.5 w-4 flex-shrink-0 text-xs font-medium text-gray-500">{i + 1}</span>
            <div className="min-w-0 flex-1">
              <span className={`mb-1 inline-block rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${KIND_TONE[s.kind]}`}>
                {KIND_LABEL[s.kind]}
              </span>
              <p className="text-sm text-gray-800">{s.text}</p>
            </div>
            <div className="flex flex-shrink-0 gap-1">
              {s.onEdit && (
                <button
                  type="button"
                  onClick={s.onEdit}
                  className="min-h-[44px] min-w-[44px] rounded text-xs font-medium text-purple-700 hover:bg-purple-50"
                  aria-label={`Change: ${s.text}`}
                >
                  Change
                </button>
              )}
              {s.onRemove && (
                <button
                  type="button"
                  onClick={s.onRemove}
                  className="min-h-[44px] min-w-[44px] rounded text-xs font-medium text-gray-600 hover:bg-gray-100 hover:text-red-700"
                  aria-label={`Remove: ${s.text}`}
                >
                  Remove
                </button>
              )}
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}
