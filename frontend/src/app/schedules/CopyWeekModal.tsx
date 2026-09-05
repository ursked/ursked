'use client';

import React, { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { SnapshotPreview } from '@/types';
import { useToast } from '@/components/ui/Toast';

interface CopyWeekModalProps {
  isOpen: boolean;
  onClose: () => void;
  /** The currently-viewed range = the SOURCE window. */
  sourceStart: string;
  sourceEnd: string;
  /** Optional: narrow the copy to these employees (e.g. dept filter). */
  employeeIds?: number[];
}

/** Duplicate the currently-viewed week (source range) into the NEXT contiguous
 *  window for the visible employees, with a snapshot-style preview + skip/overwrite. */
export default function CopyWeekModal({
  isOpen,
  onClose,
  sourceStart,
  sourceEnd,
  employeeIds,
}: CopyWeekModalProps) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [onConflict, setOnConflict] = useState<'skip' | 'overwrite'>('skip');
  const [preview, setPreview] = useState<SnapshotPreview | null>(null);

  const body = {
    source_start_date: sourceStart,
    source_end_date: sourceEnd,
    ...(employeeIds && employeeIds.length ? { employee_ids: employeeIds } : {}),
  };

  const previewMut = useMutation({
    mutationFn: () => api.copyWeekPreview(body),
    onSuccess: (data) => setPreview(data),
    onError: (e: Error) => showToast(e.message, 'error'),
  });

  const applyMut = useMutation({
    mutationFn: () => api.copyWeek({ ...body, on_conflict: onConflict }),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ['schedule-grid'] });
      const parts = [`${res.created} created`];
      if (res.overwritten) parts.push(`${res.overwritten} overwritten`);
      if (res.skipped.length) parts.push(`${res.skipped.length} skipped`);
      showToast(`Copied to next week — ${parts.join(', ')}`, 'success');
      handleClose();
    },
    onError: (e: Error) => showToast(e.message, 'error'),
  });

  const handleClose = () => {
    setPreview(null);
    setOnConflict('skip');
    onClose();
  };

  if (!isOpen) return null;

  const target = preview?.occurrences?.[0];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-md rounded-xl bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-gray-100 px-4 py-3">
          <div>
            <h3 className="text-sm font-semibold text-gray-900">Duplicate week → next</h3>
            <p className="mt-0.5 text-xs text-gray-500">
              Copies {sourceStart} – {sourceEnd} into the next window for the shown employees.
            </p>
          </div>
          <button onClick={handleClose} className="text-gray-400 hover:text-gray-600" aria-label="Close">
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="space-y-3 px-4 py-3">
          {!preview ? (
            <button
              onClick={() => previewMut.mutate()}
              disabled={previewMut.isPending}
              className="w-full rounded-md bg-purple-600 px-3 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
            >
              {previewMut.isPending ? 'Checking…' : 'Preview'}
            </button>
          ) : (
            <>
              <div className="rounded-md bg-gray-50 p-3 text-xs text-gray-700">
                {target && (
                  <p>
                    Target: <span className="font-medium">{target.start_date} – {target.end_date}</span>
                  </p>
                )}
                <p className="mt-1">
                  {preview.total_shifts} shift(s) · {preview.create_count} would be created.
                </p>
              </div>

              {preview.blocking_conflicts.length > 0 && (
                <div className="rounded-md bg-amber-50 p-2 text-xs text-amber-700">
                  {preview.blocking_conflicts.length} date(s) on approved leave — always skipped.
                </div>
              )}

              {preview.resolvable_conflicts.length > 0 && (
                <div className="space-y-1.5 rounded-md border border-gray-200 p-2">
                  <p className="text-xs text-gray-600">
                    {preview.resolvable_conflicts.length} target slot(s) already have shifts / hit a guardrail:
                  </p>
                  <label className="flex items-center gap-2 text-xs text-gray-700">
                    <input type="radio" name="copy-week-on-conflict" checked={onConflict === 'skip'} onChange={() => setOnConflict('skip')} />
                    Skip them (keep existing)
                  </label>
                  <label className="flex items-center gap-2 text-xs text-gray-700">
                    <input type="radio" name="copy-week-on-conflict" checked={onConflict === 'overwrite'} onChange={() => setOnConflict('overwrite')} />
                    Overwrite them (approved leave still kept)
                  </label>
                </div>
              )}

              <div className="flex gap-2">
                <button
                  onClick={() => applyMut.mutate()}
                  disabled={applyMut.isPending}
                  className="flex-1 rounded-md bg-purple-600 px-3 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
                >
                  {applyMut.isPending ? 'Copying…' : 'Copy to next week'}
                </button>
                <button
                  onClick={() => setPreview(null)}
                  className="rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-700 hover:bg-gray-50"
                >
                  Back
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
