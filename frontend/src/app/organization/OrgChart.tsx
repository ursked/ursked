'use client';

import { useCallback, useRef, useState, useEffect, WheelEvent } from 'react';
import { OrgTreeNode as OrgTreeNodeType, OrgLevel } from '@/types';
import { LEVEL_COLORS } from './OrgTree';

const MIN_ZOOM = 0.2;
const MAX_ZOOM = 2.0;
const ZOOM_STEP = 0.15;

type Orientation = 'vertical' | 'horizontal';

interface Props {
  nodes: OrgTreeNodeType[];
  levels: OrgLevel[];
  selectedNodeId: number | null;
  onSelectNode: (id: number | null) => void;
  onAddChild?: (parentId: number | null) => void;
}

interface ChartNodeProps {
  node: OrgTreeNodeType;
  selectedNodeId: number | null;
  onSelect: (id: number | null) => void;
  onAddChild?: (parentId: number | null) => void;
  getLevelColor: (levelNumber: number) => { bg: string; text: string; border: string };
  maxLevelNumber: number;
  orientation: Orientation;
}

function OrgChartNode({
  node,
  selectedNodeId,
  onSelect,
  onAddChild,
  getLevelColor,
  maxLevelNumber,
  orientation,
}: ChartNodeProps) {
  const hasChildren = node.children && node.children.length > 0;
  const isSelected = selectedNodeId === node.id;
  const color = getLevelColor(node.level_number);
  const canHaveChildren = node.level_number < maxLevelNumber;
  const isVertical = orientation === 'vertical';

  const card = (
    <div
      onClick={() => onSelect(isSelected ? null : node.id)}
      className={`group relative w-52 rounded-lg border-2 p-3 cursor-pointer transition-all shadow-sm hover:shadow-md ${
        isSelected
          ? 'border-purple-400 ring-2 ring-purple-200 bg-purple-50'
          : `${color.border} bg-white hover:border-purple-300`
      }`}
    >
      {/* Level badge */}
      <span
        className={`inline-flex px-1.5 py-0.5 rounded text-[10px] font-semibold ${color.bg} ${color.text}`}
      >
        {node.level_name}
      </span>

      {/* Node name */}
      <p className="mt-1.5 text-sm font-semibold text-gray-900 truncate">{node.name}</p>

      {/* Code */}
      {node.code && <p className="text-[11px] text-gray-400 truncate">{node.code}</p>}

      {/* Head user */}
      {node.head_user_name && (
        <div className="mt-1.5 flex items-center gap-1 text-xs text-gray-500">
          <svg className="w-3 h-3 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"
            />
          </svg>
          <span className="truncate">{node.head_user_name}</span>
        </div>
      )}

      {/* Member count + inactive badge */}
      <div className="mt-1 flex items-center gap-2">
        {node.member_count > 0 && (
          <span className="text-[11px] text-gray-400 flex items-center gap-0.5">
            <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z"
              />
            </svg>
            {node.member_count}
          </span>
        )}
        {!node.is_active && (
          <span className="px-1 py-0.5 rounded text-[10px] font-medium bg-gray-100 text-gray-500">
            Inactive
          </span>
        )}
      </div>

      {/* Add child button (hover) — bottom for vertical, right for horizontal */}
      {onAddChild && canHaveChildren && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            onAddChild(node.id);
          }}
          className={`absolute opacity-0 group-hover:opacity-100 w-6 h-6 rounded-full bg-purple-600 text-white flex items-center justify-center shadow-md hover:bg-purple-700 transition-all z-10 ${
            isVertical
              ? '-bottom-3 left-1/2 -translate-x-1/2'
              : '-right-3 top-1/2 -translate-y-1/2'
          }`}
          title="Add child unit"
        >
          <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
          </svg>
        </button>
      )}
    </div>
  );

  // ── VERTICAL: card on top, children in a row below ──
  if (isVertical) {
    return (
      <div className="flex flex-col items-center">
        {card}
        {hasChildren && (
          <>
            <div className="w-px h-6 bg-gray-300" />
            <div className="flex items-start">
              {node.children.map((child, index) => (
                <div key={child.id} className="flex flex-col items-center relative px-3">
                  {node.children.length > 1 && (
                    <div
                      className={`h-px bg-gray-300 absolute top-0 ${
                        index === 0
                          ? 'left-1/2 right-0'
                          : index === node.children.length - 1
                            ? 'left-0 right-1/2'
                            : 'left-0 right-0'
                      }`}
                    />
                  )}
                  <div className="w-px h-6 bg-gray-300" />
                  <OrgChartNode
                    node={child}
                    selectedNodeId={selectedNodeId}
                    onSelect={onSelect}
                    onAddChild={onAddChild}
                    getLevelColor={getLevelColor}
                    maxLevelNumber={maxLevelNumber}
                    orientation={orientation}
                  />
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    );
  }

  // ── HORIZONTAL: card on left, children in a column to the right ──
  return (
    <div className="flex items-center">
      {card}
      {hasChildren && (
        <>
          {/* Horizontal line right from card */}
          <div className="h-px w-6 bg-gray-300" />
          {/* Children column */}
          <div className="flex flex-col justify-center">
            {node.children.map((child, index) => (
              <div key={child.id} className="flex items-center relative py-3">
                {/* Vertical connector segment spanning siblings */}
                {node.children.length > 1 && (
                  <div
                    className={`w-px bg-gray-300 absolute left-0 ${
                      index === 0
                        ? 'top-1/2 bottom-0'
                        : index === node.children.length - 1
                          ? 'top-0 bottom-1/2'
                          : 'top-0 bottom-0'
                    }`}
                  />
                )}
                {/* Horizontal line right to child card */}
                <div className="h-px w-6 bg-gray-300" />
                <OrgChartNode
                  node={child}
                  selectedNodeId={selectedNodeId}
                  onSelect={onSelect}
                  onAddChild={onAddChild}
                  getLevelColor={getLevelColor}
                  maxLevelNumber={maxLevelNumber}
                  orientation={orientation}
                />
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

export default function OrgChart({ nodes, levels, selectedNodeId, onSelectNode, onAddChild }: Props) {
  const [zoom, setZoom] = useState(1);
  const [orientation, setOrientation] = useState<Orientation>('vertical');
  const containerRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);

  const getLevelColor = (levelNumber: number) => {
    return LEVEL_COLORS[(levelNumber - 1) % LEVEL_COLORS.length];
  };

  const maxLevelNumber = levels.length > 0 ? Math.max(...levels.map((l) => l.level_number)) : 1;

  const zoomIn = useCallback(() => {
    setZoom((z) => Math.min(MAX_ZOOM, Math.round((z + ZOOM_STEP) * 100) / 100));
  }, []);

  const zoomOut = useCallback(() => {
    setZoom((z) => Math.max(MIN_ZOOM, Math.round((z - ZOOM_STEP) * 100) / 100));
  }, []);

  const resetZoom = useCallback(() => setZoom(1), []);

  const fitToView = useCallback(() => {
    if (!containerRef.current || !contentRef.current) return;
    const prevZoom = zoom;
    contentRef.current.style.transform = 'scale(1)';
    const contentW = contentRef.current.scrollWidth;
    const contentH = contentRef.current.scrollHeight;
    contentRef.current.style.transform = `scale(${prevZoom})`;

    const containerW = containerRef.current.clientWidth - 32;
    const containerH = containerRef.current.clientHeight - 32;

    if (contentW === 0 || contentH === 0) return;
    const fit = Math.min(containerW / contentW, containerH / contentH, 1);
    setZoom(Math.max(MIN_ZOOM, Math.round(fit * 100) / 100));
  }, [zoom]);

  const handleWheel = useCallback(
    (e: WheelEvent<HTMLDivElement>) => {
      if (e.ctrlKey || e.metaKey) {
        e.preventDefault();
        if (e.deltaY < 0) zoomIn();
        else zoomOut();
      }
    },
    [zoomIn, zoomOut],
  );

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const prevent = (e: globalThis.WheelEvent) => {
      if (e.ctrlKey || e.metaKey) e.preventDefault();
    };
    el.addEventListener('wheel', prevent, { passive: false });
    return () => el.removeEventListener('wheel', prevent);
  }, []);

  if (nodes.length === 0) {
    return (
      <div className="py-8 text-center text-gray-400 text-sm">No organization units found.</div>
    );
  }

  const isVertical = orientation === 'vertical';

  const orientationToggle = (
    <div className="flex items-center bg-white/90 backdrop-blur border border-gray-200 rounded-lg shadow-sm p-0.5">
      <button
        onClick={() => setOrientation('vertical')}
        className={`px-2 py-1.5 rounded-md text-xs font-medium transition-colors flex items-center gap-1.5 ${
          isVertical ? 'bg-purple-600 text-white' : 'text-gray-500 hover:text-gray-700'
        }`}
        title="Top-down (vertical) layout"
      >
        {/* vertical tree icon */}
        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <rect x="9" y="3" width="6" height="4" rx="1" strokeWidth={2} />
          <rect x="3" y="15" width="6" height="4" rx="1" strokeWidth={2} />
          <rect x="15" y="15" width="6" height="4" rx="1" strokeWidth={2} />
          <path strokeLinecap="round" strokeWidth={2} d="M12 7v4M6 15v-2h12v2" />
        </svg>
        Vertical
      </button>
      <button
        onClick={() => setOrientation('horizontal')}
        className={`px-2 py-1.5 rounded-md text-xs font-medium transition-colors flex items-center gap-1.5 ${
          !isVertical ? 'bg-purple-600 text-white' : 'text-gray-500 hover:text-gray-700'
        }`}
        title="Left-to-right (horizontal) layout"
      >
        {/* horizontal tree icon */}
        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <rect x="3" y="9" width="4" height="6" rx="1" strokeWidth={2} />
          <rect x="15" y="3" width="4" height="6" rx="1" strokeWidth={2} />
          <rect x="15" y="15" width="4" height="6" rx="1" strokeWidth={2} />
          <path strokeLinecap="round" strokeWidth={2} d="M7 12h4m0-6v12h2M11 6h2" />
        </svg>
        Horizontal
      </button>
    </div>
  );

  return (
    <div className="relative">
      {/* Orientation toggle: in normal flow on mobile (avoids colliding with
          the floating zoom controls), floated top-left on sm+ screens. */}
      <div className="mb-2 flex sm:hidden">{orientationToggle}</div>
      <div className="hidden sm:block absolute top-2 left-2 z-20">{orientationToggle}</div>

      {/* Zoom controls */}
      <div className="absolute top-2 right-2 z-20 flex items-center gap-1 bg-white/90 backdrop-blur border border-gray-200 rounded-lg shadow-sm p-1">
        <button
          onClick={zoomOut}
          disabled={zoom <= MIN_ZOOM}
          className="w-7 h-7 flex items-center justify-center rounded-md text-gray-600 hover:bg-gray-100 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
          title="Zoom out"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20 12H4" />
          </svg>
        </button>
        <button
          onClick={resetZoom}
          className="min-w-[3rem] h-7 px-1.5 text-xs font-medium text-gray-700 rounded-md hover:bg-gray-100 transition-colors"
          title="Reset zoom"
        >
          {Math.round(zoom * 100)}%
        </button>
        <button
          onClick={zoomIn}
          disabled={zoom >= MAX_ZOOM}
          className="w-7 h-7 flex items-center justify-center rounded-md text-gray-600 hover:bg-gray-100 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
          title="Zoom in"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
          </svg>
        </button>
        <div className="w-px h-5 bg-gray-200 mx-0.5" />
        <button
          onClick={fitToView}
          className="w-7 h-7 flex items-center justify-center rounded-md text-gray-600 hover:bg-gray-100 transition-colors"
          title="Fit to view"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4" />
          </svg>
        </button>
      </div>

      {/* Hint */}
      <div className="absolute bottom-2 left-2 z-20 text-[10px] text-gray-400 select-none pointer-events-none">
        Ctrl + scroll to zoom &middot; Drag to pan
      </div>

      {/* Scrollable + zoomable area */}
      <div
        ref={containerRef}
        onWheel={handleWheel}
        className="overflow-auto py-6 px-4"
        style={{ maxHeight: 'calc(100vh - 260px)' }}
      >
        <div
          ref={contentRef}
          className={`transition-transform duration-150 ${
            isVertical
              ? 'inline-flex justify-center gap-8 min-w-full'
              : 'inline-flex flex-col justify-center gap-8'
          }`}
          style={{
            transform: `scale(${zoom})`,
            transformOrigin: isVertical ? 'top center' : 'left center',
          }}
        >
          {nodes.map((node) => (
            <OrgChartNode
              key={node.id}
              node={node}
              selectedNodeId={selectedNodeId}
              onSelect={onSelectNode}
              onAddChild={onAddChild}
              getLevelColor={getLevelColor}
              maxLevelNumber={maxLevelNumber}
              orientation={orientation}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
