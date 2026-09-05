'use client';

import React from 'react';
import { Shift } from '@/types';
import {
  resolveStatus,
  formatShiftTime,
  shiftTimeParts,
  readableOnTint,
  WORK_ARRANGEMENT_LABELS,
  type StatusMaps,
} from './scheduleHelpers';

interface ShiftCardProps {
  shift: Shift;
  onClick?: (shift: Shift) => void;
  onCopy?: (shift: Shift) => void;
  compact?: boolean;
  draggable?: boolean;
  onDragStart?: (e: React.DragEvent, shift: Shift) => void;
  /**
   * The tenant's own status types. Without these the card falls back to the
   * built-in codes only, which is how tenant-configured colours used to be
   * ignored on the grid entirely.
   */
  statusMaps?: StatusMaps;
}

export default function ShiftCard({
  shift, onClick, onCopy, compact, draggable: isDraggable, onDragStart, statusMaps,
}: ShiftCardProps) {
  const status = resolveStatus(shift.status, statusMaps);
  // An explicit per-shift colour still wins: it is a deliberate override.
  const bgColor = shift.color || status.color;
  // The chip, border and legend keep the admin's exact colour; only the label
  // text is darkened, and only when the chosen colour cannot be read on its own
  // 9%-alpha tint. Several shipped defaults fail that test — amber at 2.9:1.
  const labelColor = readableOnTint(bgColor);
  const timeStr = formatShiftTime(shift.start_time, shift.end_time);
  const times = shiftTimeParts(shift.start_time, shift.end_time);
  const shortLabel = status.short;
  const waLabel = shift.work_arrangement ? WORK_ARRANGEMENT_LABELS[shift.work_arrangement] : null;
  const isDraft = shift.is_published === false;

  const unknownHint = status.known
    ? undefined
    : `Unrecognised status "${shift.status}" — no matching entry under Settings > status types.`;

  if (compact) {
    return (
      <button
        type="button"
        onClick={() => onClick?.(shift)}
        className={`w-full h-6 rounded text-[10px] font-medium text-white truncate px-1 leading-6 text-left transition-opacity hover:opacity-80 ${
          status.known ? '' : 'ring-1 ring-dashed ring-slate-400'
        }`}
        style={{ backgroundColor: bgColor }}
        title={unknownHint ?? `${status.label}${timeStr ? ` ${timeStr}` : ''}${waLabel ? ` (${waLabel})` : ''}`}
      >
        {shortLabel}{timeStr ? ` ${timeStr}` : ''}
      </button>
    );
  }

  return (
    <div
      className={`relative group/card ${isDraggable ? 'cursor-grab active:cursor-grabbing' : ''}`}
      draggable={isDraggable}
      onDragStart={(e) => {
        if (isDraggable && onDragStart) {
          e.currentTarget.style.opacity = '0.4';
          onDragStart(e, shift);
        }
      }}
      onDragEnd={(e) => {
        e.currentTarget.style.opacity = '1';
      }}
    >
      {/* min-h-[44px] on phones only: a rest-day card carries no time and was
          rendering 25px tall, well under the 44px minimum tap target. */}
      <button
        type="button"
        onClick={() => onClick?.(shift)}
        className={`w-full rounded-md text-left transition-all hover:shadow-md hover:scale-[1.02] cursor-pointer min-h-[44px] sm:min-h-0 ${
          isDraft ? 'border border-dashed border-gray-400 opacity-80' : ''
        } ${status.known ? '' : 'ring-1 ring-dashed ring-slate-400'}`}
        style={{ backgroundColor: bgColor + '18', borderLeft: `3px solid ${bgColor}` }}
        title={
          unknownHint ??
          (isDraft ? 'Draft — not yet published to the employee' : status.label)
        }
      >
        <div className="px-2 py-1">
          {/* flex-wrap matters for column width, not just for looks: an
              unwrapped row of "Sched" + "DRAFT" + "WFH" sets a ~60px min-content
              floor under the whole date column, which is the second thing (after
              the time range) that was keeping phones down to two days on screen. */}
          <div className="flex flex-wrap items-center gap-1">
            <span className="text-[11px] font-semibold" style={{ color: labelColor }}>
              {shortLabel}
            </span>
            {!status.known && (
              <span className="text-[8px] px-1 py-0.5 rounded bg-slate-200 text-slate-700 font-semibold uppercase tracking-wide">
                ?
              </span>
            )}
            {isDraft && (
              <span className="text-[8px] px-1 py-0.5 rounded bg-gray-200 text-gray-600 font-semibold uppercase tracking-wide">
                Draft
              </span>
            )}
            {waLabel && (
              <span className="text-[9px] px-1 py-0.5 rounded bg-white/60 text-gray-600 font-medium">
                {waLabel}
              </span>
            )}
          </div>
          {times && (
            <>
              {/* Phones stack start over end; desktop keeps the range on one
                  line. Both are in the DOM but only one is displayed, and a
                  display:none cell contributes nothing to table column width. */}
              <p className="sm:hidden text-[10px] text-gray-600 mt-0.5 leading-[1.15] tabular-nums">
                <span className="block">{times.start}</span>
                {times.end && <span className="block text-gray-500">{times.end}</span>}
              </p>
              <p className="hidden sm:block text-[10px] text-gray-600 mt-0.5">{timeStr}</p>
            </>
          )}
          {shift.role_name && (
            <p className="text-[9px] text-gray-600 truncate mt-0.5">{shift.role_name}</p>
          )}
        </div>
      </button>
      {onCopy && (
        <button
          type="button"
          draggable={false}
          onClick={(e) => {
            e.stopPropagation();
            onCopy(shift);
          }}
          className="absolute top-0.5 right-0.5 p-1 rounded bg-white/80 text-gray-500 hover:text-purple-600 hover:bg-white opacity-0 group-hover/card:opacity-100 focus:opacity-100 transition-opacity"
          title="Copy shift (Ctrl+C)"
          aria-label={`Copy the ${status.label} shift${timeStr ? ` at ${timeStr}` : ''}`}
        >
          <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
          </svg>
        </button>
      )}
    </div>
  );
}
