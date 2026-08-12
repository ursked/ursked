'use client';

import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { ScheduleSnapshot, SnapshotPreview } from '@/types';
import { useToast } from '@/components/ui/Toast';

interface SnapshotPanelProps {
  isOpen: boolean;
  onClose: () => void;
  currentStartDate: string;
  currentEndDate: string;
  currentRangeType: string;
}

export default function SnapshotPanel({
  isOpen,
  onClose,
  currentStartDate,
  currentEndDate,
  currentRangeType,
}: SnapshotPanelProps) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();

  const [tab, setTab] = useState<'list' | 'create'>('list');
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [applyingId, setApplyingId] = useState<number | null>(null);
  const [applyDate, setApplyDate] = useState('');
  const [repeatUntil, setRepeatUntil] = useState('');
  const [onConflict, setOnConflict] = useState<'skip' | 'overwrite'>('skip');
  const [preview, setPreview] = useState<SnapshotPreview | null>(null);
  const [deleteConfirmId, setDeleteConfirmId] = useState<number | null>(null);

  const resetApply = () => {
    setApplyingId(null);
    setApplyDate('');
    setRepeatUntil('');
    setOnConflict('skip');
    setPreview(null);
  };

  const { data: snapshots, isLoading } = useQuery<ScheduleSnapshot[]>({
    queryKey: ['schedule-snapshots'],
    queryFn: () => api.getSnapshots(),
    enabled: isOpen,
  });

  const createMutation = useMutation({
    mutationFn: () => api.createSnapshot({
      name,
      description: description || undefined,
      start_date: currentStartDate,
      end_date: currentEndDate,
      range_type: currentRangeType,
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['schedule-snapshots'] });
      setTab('list');
      setName('');
      setDescription('');
      showToast('Snapshot saved', 'success');
    },
    onError: (err: Error) => showToast(err.message, 'error'),
  });

  const previewMutation = useMutation({
    mutationFn: ({ id }: { id: number }) =>
      api.previewSnapshotApply(id, {
        target_start_date: applyDate,
        repeat_until: repeatUntil || undefined,
      }),
    onSuccess: (data) => setPreview(data),
    onError: (err: Error) => showToast(err.message, 'error'),
  });

  const applyMutation = useMutation({
    mutationFn: ({ id }: { id: number }) =>
      api.applySnapshot(id, {
        target_start_date: applyDate,
        repeat_until: repeatUntil || undefined,
        on_conflict: onConflict,
      }),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ['schedule-grid'] });
      const parts = [`Created ${res.created}`];
      if (res.overwritten) parts.push(`overwrote ${res.overwritten}`);
      if (res.skipped.length) parts.push(`skipped ${res.skipped.length}`);
      showToast(parts.join(', '), res.created > 0 ? 'success' : 'info');
      resetApply();
    },
    onError: (err: Error) => showToast(err.message, 'error'),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.deleteSnapshot(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['schedule-snapshots'] });
      setDeleteConfirmId(null);
      showToast('Snapshot deleted', 'success');
    },
    onError: (err: Error) => showToast(err.message, 'error'),
  });

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />
      <div className="relative w-full max-w-md bg-white shadow-2xl flex flex-col">
        {/* Header */}
        <div className="px-6 py-4 border-b flex items-center justify-between">
          <div>
            <h3 className="text-lg font-semibold text-gray-900">Schedule Snapshots</h3>
            <p className="text-xs text-gray-500 mt-0.5">Save and reuse schedule patterns</p>
          </div>
          <button onClick={onClose} className="p-1 rounded-lg hover:bg-gray-100 text-gray-400">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Tabs */}
        <div className="px-6 border-b flex gap-4">
          <button
            onClick={() => setTab('list')}
            className={`py-2.5 text-sm font-medium border-b-2 transition-colors ${
              tab === 'list' ? 'border-purple-600 text-purple-600' : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            Saved Snapshots
          </button>
          <button
            onClick={() => setTab('create')}
            className={`py-2.5 text-sm font-medium border-b-2 transition-colors ${
              tab === 'create' ? 'border-purple-600 text-purple-600' : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            Save Current
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6">
          {tab === 'create' ? (
            <div className="space-y-4">
              <div className="bg-purple-50 border border-purple-200 rounded-lg p-3">
                <p className="text-xs font-medium text-purple-800 mb-1">Capturing schedule from</p>
                <p className="text-sm text-purple-900">{currentStartDate} to {currentEndDate}</p>
                <p className="text-xs text-purple-600 mt-0.5 capitalize">{currentRangeType} view</p>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Snapshot Name</label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. Week 5 Pattern, Night Shift Rotation"
                  className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Description (optional)</label>
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  rows={2}
                  placeholder="Notes about this schedule pattern"
                  className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none resize-none"
                />
              </div>

              <button
                onClick={() => createMutation.mutate()}
                disabled={!name.trim() || createMutation.isPending}
                className="w-full py-2 text-sm font-medium text-white bg-purple-600 rounded-lg hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
              >
                {createMutation.isPending ? (
                  <>
                    <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                    Saving...
                  </>
                ) : (
                  <>
                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M6.827 6.175A2.31 2.31 0 015.186 7.23c-.38.054-.757.112-1.134.175C2.999 7.58 2.25 8.507 2.25 9.574V18a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9.574c0-1.067-.75-1.994-1.802-2.169a47.865 47.865 0 00-1.134-.175 2.31 2.31 0 01-1.64-1.055l-.822-1.316a2.192 2.192 0 00-1.736-1.039 48.774 48.774 0 00-5.232 0 2.192 2.192 0 00-1.736 1.039l-.821 1.316z" />
                      <path strokeLinecap="round" strokeLinejoin="round" d="M16.5 12.75a4.5 4.5 0 11-9 0 4.5 4.5 0 019 0z" />
                    </svg>
                    Save Snapshot
                  </>
                )}
              </button>
            </div>
          ) : (
            <div className="space-y-3">
              {isLoading ? (
                <div className="flex items-center gap-2 text-sm text-gray-500 justify-center py-8">
                  <div className="w-5 h-5 border-2 border-purple-200 border-t-purple-600 rounded-full animate-spin" />
                  Loading...
                </div>
              ) : !snapshots || snapshots.length === 0 ? (
                <div className="text-center py-8">
                  <svg className="mx-auto h-10 w-10 text-gray-300 mb-2" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M6.827 6.175A2.31 2.31 0 015.186 7.23c-.38.054-.757.112-1.134.175C2.999 7.58 2.25 8.507 2.25 9.574V18a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9.574c0-1.067-.75-1.994-1.802-2.169a47.865 47.865 0 00-1.134-.175 2.31 2.31 0 01-1.64-1.055l-.822-1.316a2.192 2.192 0 00-1.736-1.039 48.774 48.774 0 00-5.232 0 2.192 2.192 0 00-1.736 1.039l-.821 1.316z" />
                    <path strokeLinecap="round" strokeLinejoin="round" d="M16.5 12.75a4.5 4.5 0 11-9 0 4.5 4.5 0 019 0z" />
                  </svg>
                  <p className="text-sm text-gray-500">No snapshots yet</p>
                  <p className="text-xs text-gray-400 mt-1">Save the current schedule to create a reusable pattern</p>
                  <button
                    onClick={() => setTab('create')}
                    className="mt-3 px-4 py-1.5 text-xs font-medium text-purple-700 bg-purple-50 rounded-lg hover:bg-purple-100 transition-colors"
                  >
                    Save Current Schedule
                  </button>
                </div>
              ) : (
                snapshots.map((snap) => (
                  <div key={snap.id} className="border border-gray-200 rounded-lg p-4 hover:border-gray-300 transition-colors">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0 flex-1">
                        <h4 className="text-sm font-medium text-gray-900 truncate">{snap.name}</h4>
                        {snap.description && (
                          <p className="text-xs text-gray-500 mt-0.5 truncate">{snap.description}</p>
                        )}
                        <div className="flex items-center gap-3 mt-2 text-xs text-gray-400">
                          <span>{snap.source_start_date} - {snap.source_end_date}</span>
                          <span>&middot;</span>
                          <span>{snap.employee_count} employees</span>
                          <span>&middot;</span>
                          <span>{snap.shift_count} shifts</span>
                        </div>
                      </div>

                      {/* Delete button */}
                      {deleteConfirmId === snap.id ? (
                        <div className="flex items-center gap-1">
                          <button
                            onClick={() => deleteMutation.mutate(snap.id)}
                            disabled={deleteMutation.isPending}
                            className="px-2 py-1 text-[10px] font-medium text-white bg-red-600 rounded hover:bg-red-700 disabled:opacity-50"
                          >
                            Confirm
                          </button>
                          <button
                            onClick={() => setDeleteConfirmId(null)}
                            className="px-2 py-1 text-[10px] font-medium text-gray-600 bg-gray-100 rounded hover:bg-gray-200"
                          >
                            Cancel
                          </button>
                        </div>
                      ) : (
                        <button
                          onClick={() => setDeleteConfirmId(snap.id)}
                          className="p-1 rounded hover:bg-red-50 text-gray-400 hover:text-red-500 transition-colors"
                          title="Delete snapshot"
                        >
                          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
                          </svg>
                        </button>
                      )}
                    </div>

                    {/* Apply section */}
                    {applyingId === snap.id ? (
                      <div className="mt-3 bg-blue-50 border border-blue-200 rounded-lg p-3 space-y-2">
                        <div>
                          <label className="block text-xs font-medium text-blue-800 mb-1">Start applying from</label>
                          <input
                            type="date"
                            value={applyDate}
                            onChange={(e) => { setApplyDate(e.target.value); setPreview(null); }}
                            className="w-full text-xs border border-blue-300 rounded-md px-2 py-1.5 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                          />
                        </div>
                        <div>
                          <label className="block text-xs font-medium text-blue-800 mb-1">
                            Repeat until <span className="font-normal text-blue-500">(optional — leave empty for a single copy)</span>
                          </label>
                          <input
                            type="date"
                            value={repeatUntil}
                            min={applyDate || undefined}
                            onChange={(e) => { setRepeatUntil(e.target.value); setPreview(null); }}
                            className="w-full text-xs border border-blue-300 rounded-md px-2 py-1.5 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                          />
                          <p className="mt-1 text-[11px] text-blue-500">
                            Copies repeat back-to-back every {snap.range_type === 'month' ? 'month' : `${Math.max(
                              (new Date(snap.source_end_date).getTime() - new Date(snap.source_start_date).getTime()) / 86400000 + 1, 1)
                            } day(s)`} until this date.
                          </p>
                        </div>

                        {/* Preview result */}
                        {preview && (
                          <div className="rounded-md border border-blue-200 bg-white p-2 space-y-1.5">
                            <p className="text-xs font-medium text-gray-800">
                              {preview.occurrences.length} cop{preview.occurrences.length === 1 ? 'y' : 'ies'} · {preview.create_count} of {preview.total_shifts} shift(s) will be created
                            </p>
                            <div className="max-h-16 overflow-y-auto text-[11px] text-gray-500 space-y-0.5">
                              {preview.occurrences.map((o) => (
                                <div key={o.index}>{o.start_date} → {o.end_date}</div>
                              ))}
                            </div>
                            {preview.blocking_conflicts.length > 0 && (
                              <p className="text-[11px] text-amber-700 bg-amber-50 rounded px-1.5 py-1">
                                {preview.blocking_conflicts.length} date(s) on approved leave — always skipped.
                              </p>
                            )}
                            {preview.resolvable_conflicts.length > 0 && (
                              <div className="text-[11px] text-gray-700 space-y-1">
                                <p className="font-medium">
                                  {preview.resolvable_conflicts.length} date(s) already have a shift or hit a guardrail:
                                </p>
                                <label className="flex items-center gap-1.5 cursor-pointer">
                                  <input type="radio" name="onConflict" checked={onConflict === 'skip'} onChange={() => setOnConflict('skip')} />
                                  <span>Skip them (keep existing)</span>
                                </label>
                                <label className="flex items-center gap-1.5 cursor-pointer">
                                  <input type="radio" name="onConflict" checked={onConflict === 'overwrite'} onChange={() => setOnConflict('overwrite')} />
                                  <span>Overwrite them (approved leave still kept)</span>
                                </label>
                              </div>
                            )}
                          </div>
                        )}

                        <div className="flex items-center gap-2 pt-0.5">
                          {!preview ? (
                            <button
                              onClick={() => { if (applyDate) previewMutation.mutate({ id: snap.id }); }}
                              disabled={!applyDate || previewMutation.isPending}
                              className="flex-1 px-3 py-1.5 text-xs font-medium text-blue-700 bg-white border border-blue-300 rounded-md hover:bg-blue-50 disabled:opacity-50 transition-colors"
                            >
                              {previewMutation.isPending ? 'Checking…' : 'Preview'}
                            </button>
                          ) : (
                            <button
                              onClick={() => applyMutation.mutate({ id: snap.id })}
                              disabled={applyMutation.isPending || preview.create_count === 0}
                              className="flex-1 px-3 py-1.5 text-xs font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700 disabled:opacity-50 transition-colors"
                            >
                              {applyMutation.isPending ? 'Applying…' : `Apply (${preview.create_count} shift${preview.create_count === 1 ? '' : 's'})`}
                            </button>
                          )}
                          <button
                            onClick={resetApply}
                            className="px-2 py-1.5 text-xs font-medium text-gray-600 bg-white border border-gray-300 rounded-md hover:bg-gray-50 transition-colors"
                          >
                            Cancel
                          </button>
                        </div>
                      </div>
                    ) : (
                      <button
                        onClick={() => { resetApply(); setApplyingId(snap.id); }}
                        className="mt-3 w-full py-1.5 text-xs font-medium text-blue-700 bg-blue-50 rounded-lg hover:bg-blue-100 transition-colors flex items-center justify-center gap-1.5"
                      >
                        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
                        </svg>
                        Apply / Repeat…
                      </button>
                    )}
                  </div>
                ))
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
