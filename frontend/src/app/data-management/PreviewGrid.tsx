'use client';

import React, { useEffect, useRef, useState } from 'react';
import type { LayoutSpec, PreviewColumn } from '@/types';
import { bandStarts } from './reportLayout';

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
  /** The page layout, drawn in the table: headings, header bands, blocks. */
  layout?: LayoutSpec | null;
  /** Headings with their {tokens} filled in by the server. */
  headings?: string[];
  /** Worksheet names, shown as tabs when each block gets its own tab. */
  sheetNames?: string[];
  /** Clicking a header band opens it for renaming, re-ranging or removal. */
  onBandClick?: (tier: number, index: number) => void;
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
  layout,
  headings,
  sheetNames,
  onBandClick,
}: PreviewGridProps) {
  const keys = columns.map((c) => c.key);
  const tiers = (layout?.header_tiers || []).filter((t) => t.length > 0);
  const blockBy = layout?.blocks?.by;
  const gap = layout?.blocks ? Math.max(0, Math.min(layout.blocks.blank_rows_between, 5)) : 0;
  const firstOnly = layout?.blocks?.repeat_value === 'first_row';
  const tabs = layout?.blocks?.sheet_per_group ? sheetNames || [] : [];
  const headingText = headings && headings.length ? headings : (layout?.heading_rows || []).map((h) => h.text);
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
              <span className="h-3 w-3 animate-spin rounded-full border-2 border-brand-200 border-t-brand-600" />
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

      {tabs.length > 0 && (
        <div className="flex gap-1 overflow-x-auto border-b border-gray-200 px-4 py-2" aria-label="Tabs in the Excel file">
          {tabs.slice(0, 30).map((t, i) => (
            <span
              key={`${t}-${i}`}
              className={`flex-shrink-0 rounded-full px-2.5 py-1 text-xs ${i === 0 ? 'bg-brand-100 font-medium text-brand-800' : 'bg-gray-100 text-gray-700'}`}
            >
              {t}
            </span>
          ))}
          {tabs.length > 30 && (
            <span className="flex-shrink-0 px-2 py-1 text-xs text-gray-600">and {tabs.length - 30} more tabs</span>
          )}
        </div>
      )}

      {/* Own scrollport so a wide report scrolls sideways without moving the
          page. overscroll-none stops iOS rubber-banding the whole table away
          from its pinned header, and pinch-zoom stays available. */}
      <div className="overflow-auto overscroll-none touch-pan-x touch-pan-y touch-pinch-zoom max-h-[62vh] rounded-b-xl">
        <table className="w-full border-separate border-spacing-0 text-sm">
          <caption className="sr-only">
            Preview of the report: {returned} of {total} rows, {columns.length} columns.
          </caption>
          <thead>
            {/* Heading lines wrap inside the visible width rather than stretching
                the table, so a long title can never push a phone sideways. Only
                the leaf heading row is sticky: several sticky rows drift apart on
                iOS, which is the bug 5.13 and 5.15 fixed. */}
            {headingText.map((text, i) => (
              <tr key={`heading-${i}`}>
                <th colSpan={columns.length} scope="colgroup" className="border-b border-gray-200 bg-white p-0 text-left">
                  <div
                    className={`sticky left-0 max-w-[calc(100vw-3rem)] whitespace-normal break-words px-3 py-2 text-sm text-gray-900 sm:max-w-2xl ${
                      layout?.heading_rows[i]?.bold === false ? 'font-normal' : 'font-semibold'
                    }`}
                  >
                    {text}
                  </div>
                </th>
              </tr>
            ))}
            {tiers.map((tier, t) => {
              const starts = bandStarts(tier, keys);
              const cells: React.ReactNode[] = [];
              for (let i = 0; i < columns.length; ) {
                const b = starts.get(i);
                if (b) {
                  const tierIndex = (layout?.header_tiers || []).indexOf(tier);
                  cells.push(
                    <th key={`band-${t}-${i}`} colSpan={b.span} scope="colgroup" className="border-b border-r border-gray-200 bg-brand-50 p-0">
                      <button
                        type="button"
                        onClick={() => onBandClick?.(tierIndex, b.index)}
                        disabled={!onBandClick}
                        className="flex w-full min-h-[40px] items-center justify-center whitespace-pre-line px-3 py-1.5 text-center text-xs font-semibold uppercase tracking-wide text-brand-900 hover:bg-brand-100"
                        aria-label={`Heading ${b.band.label}: change or remove`}
                      >
                        {b.band.label}
                      </button>
                    </th>
                  );
                  i += b.span;
                } else {
                  cells.push(<th key={`gap-${t}-${i}`} className="border-b border-r border-gray-100 bg-gray-50" aria-hidden="true" />);
                  i += 1;
                }
              }
              return <tr key={`tier-${t}`}>{cells}</tr>;
            })}
            <tr>
              {columns.map((c) => {
                const marks = markersFor(c.key);
                const actions = actionsFor(c.key);
                const isOpen = openMenu === c.key;
                return (
                  <th
                    key={c.key}
                    scope="col"
                    data-leaf="true"
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
                            className="rounded bg-brand-100 px-1 py-0.5 text-[10px] font-medium normal-case text-brand-800"
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
            {rows.map((r, i) => {
              const prev = i > 0 ? rows[i - 1] : null;
              const newBlock = !!blockBy && (!prev || String(prev[blockBy] ?? '') !== String(r[blockBy] ?? ''));
              return (
              <React.Fragment key={i}>
              {newBlock && prev && gap > 0 && (
                <tr aria-hidden="true">
                  <td colSpan={columns.length} className="border-b border-gray-100 bg-white" style={{ height: `${gap * 1.25}rem` }} />
                </tr>
              )}
              <tr className={i % 2 ? 'bg-gray-50/60' : 'bg-white'}>
                {columns.map((c) => {
                  const hidden = firstOnly && c.key === blockBy && !newBlock;
                  const v = hidden ? '' : r[c.key];
                  const text = v === null || v === undefined ? '' : String(v);
                  return (
                    <td
                      key={c.key}
                      className="max-w-[260px] truncate border-b border-r border-gray-100 px-3 py-2 text-gray-800"
                      title={text}
                    >
                      {hidden ? null : text === '' ? <span className="text-gray-400">—</span> : text}
                    </td>
                  );
                })}
              </tr>
              </React.Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
