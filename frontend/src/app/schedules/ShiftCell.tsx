'use client';

import React, { useState, useRef } from 'react';
import { Shift, DateRemark } from '@/types';
import ShiftCard from './ShiftCard';

interface ShiftCellProps {
  shifts: Shift[];
  employeeId: number;
  dateStr: string;
  remark?: DateRemark;
  /** Guardrail violation messages for this cell (inline amber warning). */
  warnings?: string[];
  isToday: boolean;
  isWeekend: boolean;
  isSelected?: boolean;
  hasClipboard?: boolean;
  onShiftClick?: (shift: Shift) => void;
  onCellClick?: (dateStr: string) => void;
  onCellSelect?: (employeeId: number, dateStr: string, shift?: Shift) => void;
  onCopyShift?: (shift: Shift) => void;
  onPasteShift?: (employeeId: number, dateStr: string) => void;
  onMoveShift?: (shiftId: number, employeeId: number, dateStr: string) => void;
  isOwnShift?: boolean;
  onSwapRequest?: (shift: Shift) => void;
  onChangeRequest?: (shift: Shift) => void;
}

export default function ShiftCell({
  shifts,
  employeeId,
  dateStr,
  remark,
  warnings,
  isToday,
  isWeekend,
  isSelected,
  hasClipboard,
  onShiftClick,
  onCellClick,
  onCellSelect,
  onCopyShift,
  onPasteShift,
  onMoveShift,
  isOwnShift,
  onSwapRequest,
  onChangeRequest,
}: ShiftCellProps) {
  const hasShifts = shifts.length > 0;
  const [isDragOver, setIsDragOver] = useState(false);
  const dragCounterRef = useRef(0);

  const handleClick = () => {
    onCellSelect?.(employeeId, dateStr, shifts[0]);
    if (!hasShifts) {
      onCellClick?.(dateStr);
    }
  };

  const handlePaste = (e: React.MouseEvent) => {
    e.stopPropagation();
    onPasteShift?.(employeeId, dateStr);
  };

  // Drag source handler (called by ShiftCard via onDragStart prop)
  const handleDragStart = (e: React.DragEvent, shift: Shift) => {
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData(
      'application/json',
      JSON.stringify({
        shiftId: shift.id,
        sourceEmployeeId: shift.employee_id,
        sourceDateStr: shift.date,
      }),
    );
  };

  // Only respond to shift-card drags, not row-reorder drags
  const isShiftDrag = (e: React.DragEvent) =>
    e.dataTransfer.types.includes('application/json') &&
    !e.dataTransfer.types.includes('application/x-row-reorder');

  // Drop target handlers
  const handleDragOver = (e: React.DragEvent) => {
    if (!isShiftDrag(e)) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
  };

  const handleDragEnter = (e: React.DragEvent) => {
    if (!isShiftDrag(e)) return;
    e.preventDefault();
    dragCounterRef.current += 1;
    if (dragCounterRef.current === 1) {
      setIsDragOver(true);
    }
  };

  const handleDragLeave = (e: React.DragEvent) => {
    if (!isShiftDrag(e)) return;
    dragCounterRef.current -= 1;
    if (dragCounterRef.current === 0) {
      setIsDragOver(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    if (!isShiftDrag(e)) return;
    e.preventDefault();
    dragCounterRef.current = 0;
    setIsDragOver(false);

    const raw = e.dataTransfer.getData('application/json');
    if (!raw) return;

    try {
      const { shiftId, sourceEmployeeId, sourceDateStr } = JSON.parse(raw);
      if (sourceEmployeeId === employeeId && sourceDateStr === dateStr) return;
      onMoveShift?.(shiftId, employeeId, dateStr);
    } catch {
      // Invalid drag data
    }
  };

  return (
    <td
      className={`border-r border-b border-gray-100 p-0.5 align-top min-w-[100px] max-w-[120px] transition-colors cursor-pointer ${
        isToday ? 'bg-purple-50/50' : isWeekend ? 'bg-gray-50/50' : 'bg-white'
      } ${remark?.is_holiday ? 'bg-red-50/40' : ''} ${
        isSelected ? 'ring-2 ring-inset ring-purple-500' : ''
      } ${isDragOver ? 'ring-2 ring-inset ring-blue-400 bg-blue-50/60' : 'hover:bg-gray-50'}`}
      onClick={handleClick}
      onDragOver={handleDragOver}
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      <div className="min-h-[56px] flex flex-col gap-0.5 p-0.5 relative group/cell">
        {warnings && warnings.length > 0 && (
          <span
            className="absolute top-0 right-0 z-20 flex h-4 w-4 items-center justify-center rounded-full bg-amber-400 text-white shadow-sm"
            title={warnings.join('\n')}
          >
            <svg className="h-2.5 w-2.5" viewBox="0 0 24 24" fill="currentColor">
              <path d="M12 2L1 21h22L12 2zm0 6l7.53 13H4.47L12 8zm-1 3v4h2v-4h-2zm0 5v2h2v-2h-2z" />
            </svg>
          </span>
        )}
        {shifts.map((shift) => (
          <div key={shift.id} className="relative">
            <ShiftCard
              shift={shift}
              onClick={onShiftClick}
              onCopy={onCopyShift}
              draggable={!!onMoveShift}
              onDragStart={handleDragStart}
            />
            {/* Swap / Change actions for own shifts */}
            {isOwnShift && onSwapRequest && onChangeRequest && (
              <div className="absolute inset-x-0 bottom-0 translate-y-full z-10 hidden group-hover/cell:flex gap-0.5 justify-center pt-0.5">
                <button
                  type="button"
                  onClick={(e) => { e.stopPropagation(); onSwapRequest(shift); }}
                  className="px-1.5 py-0.5 text-[9px] font-medium bg-blue-100 text-blue-700 rounded hover:bg-blue-200 transition-colors whitespace-nowrap"
                  title="Request swap with another employee"
                >
                  Swap
                </button>
                <button
                  type="button"
                  onClick={(e) => { e.stopPropagation(); onChangeRequest(shift); }}
                  className="px-1.5 py-0.5 text-[9px] font-medium bg-orange-100 text-orange-700 rounded hover:bg-orange-200 transition-colors whitespace-nowrap"
                  title="Request schedule change"
                >
                  Change
                </button>
              </div>
            )}
          </div>
        ))}
        {!hasShifts && hasClipboard && (
          <button
            type="button"
            onClick={handlePaste}
            className="absolute inset-0 flex items-center justify-center opacity-0 hover:opacity-100 transition-opacity bg-purple-50/50 rounded"
            title="Paste shift (Ctrl+V)"
          >
            <svg className="w-4 h-4 text-purple-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
            </svg>
          </button>
        )}
        {!hasShifts && !hasClipboard && (
          <div className="flex-1 flex items-center justify-center opacity-0 hover:opacity-40 transition-opacity">
            <svg className="w-4 h-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
          </div>
        )}
      </div>
    </td>
  );
}
