'use client';

import React, { useEffect, useRef, useState } from 'react';
import type { PreviewColumn } from '@/types';

export interface ColumnAction {
  key: string;
  label: string;
  hint?: string;
  danger?: boolean;
  onSelect: () => void;
}

interface PreviewGridProps {
  columns: PreviewColumn[];
  rows: Record<string, unknown>[];
  total: number;
  returned: number;
  isLoading: boolean;
  isError: boolean;
  errorMessage?: string;
  onRetry?: () => void;
  /** Actions offered by a column's own menu, built by the parent per column. */
  actionsFor: (columnKey: string) => ColumnAction[];
  /** Marks which columns currently carry a filter/sort/rename, for the badges. */
  markersFor: (columnKey: string) => string[];
  emptyHint?: string;
}

/**
 * The live result table.
 *
 * This is the centre of the redesign: previously you assembled an export from
 * checkboxes and found out what you had built only after downloading it. Here
 * the data is on screen from the first click and every change re-runs against
 * the real rows, so a filter that matches nothing is visible immediately rather
 * than arriving as an empty file.
 */
export default function PreviewGrid({
  columns,
  rows,
  total,
  returned,
  isLoading,
  isError,
  errorMessage,
  onRetry,
  actionsFor,
  markersFor,
  emptyHint,
}: PreviewGridProps) {
  const [openMenu, setOpenMenu] = useState<string | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!openMenu) return;
    const onDown = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setOpenMenu(null);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpenMenu(null);
    };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [openMenu]);

  if (isError) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-6">
        <p className="text-sm font-medium text-red-800">This report could not run.</p>
        <p className="mt-1 text-sm text-red-700">
          {errorMessage || 'Something in the definition is not valid.'}
        </p>
        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            className="mt-3 rounded-lg border border-red-300 bg-white px-3 py-2 text-sm font-medium text-red-700 hover:bg-red-100"
          >
            Try again
          </button>
        )}
      </div>
    );
  }

  if (columns.length === 0) {
    return (
      <div className="flex min-h-[280px] flex-col items-center justify-center rounded-xl border border-dashed border-gray-300 bg-gray-50 p-8 text-center">
        <svg className="mb-3 h-10 w-10 text-gray-400" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6A2.25 2.25 0 016 3.75h12A2.25 2.25 0 0120.25 6v12A2.25 2.25 0 0118 20.25H6A2.25 2.25 0 013.75 18V6zM3.75 9h16.5M9 20.25V9" />
        </svg>
        <p className="text-sm font-medium text-gray-900">Nothing to show yet</p>
        <p className="mt-1 max-w-sm text-sm text-gray-600">
          {emptyHint || 'Pick some information to include and it will appear here straight away.'}
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-gray-200 bg-white">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-gray-200 px-4 py-2.5">
        <p className="text-sm text-gray-700">
          {isLoading ? (
            <span className="inline-flex items-center gap-2 text-gray-600">
              <span className="h-3 w-3 animate-spin rounded-full border-2 border-purple-200 border-t-purple-600" />
              Updating…
            </span>
          ) : total === 0 ? (
            <span className="font-medium text-amber-700">
              No rows match — check the filters on the right
            </span>
          ) : (
            <>
              Showing <span className="font-semibold text-gray-900">{returned.toLocaleString()}</span> of{' '}
              <span className="font-semibold text-gray-900">{total.toLocaleString()}</span> rows
            </>
          )}
        </p>
        <p className="text-xs text-gray-600">Click any column heading for options</p>
      </div>

      {/* Own scrollport so a wide report scrolls sideways without moving the
          page. overscroll-none stops iOS rubber-banding the whole table away
          from its pinned header, and pinch-zoom stays available. */}
      <div className="overflow-auto overscroll-none touch-pan-x touch-pan-y touch-pinch-zoom max-h-[62vh] rounded-b-xl">
        <table className="w-full border-separate border-spacing-0 text-sm">
          <caption className="sr-only">
            Preview of the report: {returned} of {total} rows, {columns.length} columns.
          </caption>
          <thead>
            <tr>
              {columns.map((c) => {
                const marks = markersFor(c.key);
                const actions = actionsFor(c.key);
                const isOpen = openMenu === c.key;
                return (
                  <th
                    key={c.key}
                    scope="col"
                    className="sticky top-0 z-20 whitespace-nowrap border-b border-r border-gray-200 bg-gray-50 p-0 text-left"
                  >
                    <div className="relative">
                      <button
                        type="button"
                        onClick={() => setOpenMenu(isOpen ? null : c.key)}
                        aria-expanded={isOpen}
                        aria-haspopup="menu"
                        className="flex w-full min-h-[44px] items-center gap-1.5 px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-gray-700 hover:bg-gray-100"
                      >
                        <span className="truncate">{c.header}</span>
                        {marks.map((m) => (
                          <span
                            key={m}
                            className="rounded bg-purple-100 px-1 py-0.5 text-[10px] font-medium normal-case text-purple-800"
                          >
                            {m}
                          </span>
                        ))}
                        <svg className="ml-auto h-3.5 w-3.5 flex-shrink-0 text-gray-500" fill="none" viewBox="0 0 24 24" strokeWidth={2.5} stroke="currentColor" aria-hidden="true">
                          <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
                        </svg>
                      </button>
                      {isOpen && (
                        <div
                          ref={menuRef}
                          role="menu"
                          className="absolute left-0 top-full z-40 mt-1 w-60 rounded-lg border border-gray-200 bg-white py-1 shadow-xl"
                        >
                          {actions.map((a) => (
                            <button
                              key={a.key}
                              type="button"
                              role="menuitem"
                              onClick={() => {
                                setOpenMenu(null);
                                a.onSelect();
                              }}
                              className={`flex w-full flex-col items-start gap-0.5 px-3 py-2 text-left hover:bg-gray-50 ${
                                a.danger ? 'text-red-700' : 'text-gray-800'
                              }`}
                            >
                              <span className="text-sm font-medium normal-case tracking-normal">{a.label}</span>
                              {a.hint && (
                                <span className="text-xs font-normal normal-case tracking-normal text-gray-600">
                                  {a.hint}
                                </span>
                              )}
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && !isLoading && (
              <tr>
                <td colSpan={columns.length} className="px-4 py-10 text-center text-sm text-gray-600">
                  No rows match this definition.
                </td>
              </tr>
            )}
            {rows.map((r, i) => (
              <tr key={i} className={i % 2 ? 'bg-gray-50/60' : 'bg-white'}>
                {columns.map((c) => {
                  const v = r[c.key];
                  const text = v === null || v === undefined ? '' : String(v);
                  return (
                    <td
                      key={c.key}
                      className="max-w-[260px] truncate border-b border-r border-gray-100 px-3 py-2 text-gray-800"
                      title={text}
                    >
                      {text === '' ? <span className="text-gray-400">—</span> : text}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
