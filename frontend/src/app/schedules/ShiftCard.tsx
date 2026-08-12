'use client';

import React from 'react';
import { Shift } from '@/types';
import { getStatusColor, getStatusShort, formatShiftTime, WORK_ARRANGEMENT_LABELS } from './scheduleHelpers';

interface ShiftCardProps {
  shift: Shift;
  onClick?: (shift: Shift) => void;
  onCopy?: (shift: Shift) => void;
  compact?: boolean;
  draggable?: boolean;
  onDragStart?: (e: React.DragEvent, shift: Shift) => void;
}

export default function ShiftCard({ shift, onClick, onCopy, compact, draggable: isDraggable, onDragStart }: ShiftCardProps) {
  const bgColor = shift.color || getStatusColor(shift.status);
  const timeStr = formatShiftTime(shift.start_time, shift.end_time);
  const shortLabel = getStatusShort(shift.status);
  const waLabel = shift.work_arrangement ? WORK_ARRANGEMENT_LABELS[shift.work_arrangement] : null;
  const isDraft = shift.is_published === false;

  if (compact) {
    return (
      <button
        type="button"
        onClick={() => onClick?.(shift)}
        className="w-full h-6 rounded text-[10px] font-medium text-white truncate px-1 leading-6 text-left transition-opacity hover:opacity-80"
        style={{ backgroundColor: bgColor }}
        title={`${shortLabel}${timeStr ? ` ${timeStr}` : ''}${waLabel ? ` (${waLabel})` : ''}`}
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
      <button
        type="button"
        onClick={() => onClick?.(shift)}
        className={`w-full rounded-md text-left transition-all hover:shadow-md hover:scale-[1.02] cursor-pointer ${
          isDraft ? 'border border-dashed border-gray-400 opacity-80' : ''
        }`}
        style={{ backgroundColor: bgColor + '18', borderLeft: `3px solid ${bgColor}` }}
        title={isDraft ? 'Draft — not yet published to the employee' : undefined}
      >
        <div className="px-2 py-1">
          <div className="flex items-center gap-1">
            <span className="text-[11px] font-semibold" style={{ color: bgColor }}>
              {shortLabel}
            </span>
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
          {timeStr && (
            <p className="text-[10px] text-gray-600 mt-0.5">{timeStr}</p>
          )}
          {shift.role_name && (
            <p className="text-[9px] text-gray-400 truncate mt-0.5">{shift.role_name}</p>
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
          className="absolute top-0.5 right-0.5 p-0.5 rounded bg-white/80 text-gray-500 hover:text-purple-600 hover:bg-white opacity-0 group-hover/card:opacity-100 transition-opacity"
          title="Copy shift (Ctrl+C)"
        >
          <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
          </svg>
        </button>
      )}
    </div>
  );
}
