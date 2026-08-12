'use client';

import { OrgTreeNode as OrgTreeNodeType } from '@/types';

interface Props {
  node: OrgTreeNodeType;
  depth: number;
  isExpanded: boolean;
  isSelected: boolean;
  onToggle: (id: number) => void;
  onSelect: (id: number | null) => void;
  onAddChild?: (parentId: number | null) => void;
  getLevelColor: (levelNumber: number) => { bg: string; text: string; border: string };
  expandedIds: Set<number>;
  selectedNodeId: number | null;
  maxLevelNumber: number;
}

export default function OrgTreeNode({
  node,
  depth,
  isExpanded,
  isSelected,
  onToggle,
  onSelect,
  onAddChild,
  getLevelColor,
  expandedIds,
  selectedNodeId,
  maxLevelNumber,
}: Props) {
  const hasChildren = node.children && node.children.length > 0;
  const color = getLevelColor(node.level_number);
  const canHaveChildren = node.level_number < maxLevelNumber;

  return (
    <div>
      {/* Node row */}
      <div
        className={`group flex items-center gap-2 px-2 py-1.5 rounded-lg cursor-pointer transition-colors ${
          isSelected
            ? 'bg-purple-50 ring-1 ring-purple-200'
            : 'hover:bg-gray-50'
        }`}
        style={{ paddingLeft: `${depth * 24 + 8}px` }}
        onClick={() => onSelect(isSelected ? null : node.id)}
      >
        {/* Expand/collapse toggle */}
        <button
          onClick={(e) => {
            e.stopPropagation();
            if (hasChildren) onToggle(node.id);
          }}
          className={`w-5 h-5 flex-shrink-0 flex items-center justify-center rounded transition-colors ${
            hasChildren
              ? 'text-gray-400 hover:text-gray-600 hover:bg-gray-200'
              : 'text-transparent'
          }`}
        >
          {hasChildren && (
            <svg
              className={`w-3.5 h-3.5 transition-transform ${isExpanded ? 'rotate-90' : ''}`}
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
          )}
        </button>

        {/* Level badge */}
        <span className={`px-1.5 py-0.5 rounded text-xs font-medium flex-shrink-0 ${color.bg} ${color.text}`}>
          {node.level_name}
        </span>

        {/* Node name */}
        <span className="font-medium text-sm text-gray-900 truncate">{node.name}</span>

        {/* Code */}
        {node.code && (
          <span className="text-xs text-gray-400 flex-shrink-0">({node.code})</span>
        )}

        {/* Head user */}
        {node.head_user_name && (
          <span className="text-xs text-gray-500 flex-shrink-0 hidden sm:inline-flex items-center gap-1">
            <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
            </svg>
            {node.head_user_name}
          </span>
        )}

        {/* Member count */}
        {node.member_count > 0 && (
          <span className="text-xs text-gray-400 flex-shrink-0 flex items-center gap-0.5">
            <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
            {node.member_count}
          </span>
        )}

        {/* Inactive badge */}
        {!node.is_active && (
          <span className="px-1.5 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-500 flex-shrink-0">
            Inactive
          </span>
        )}

        {/* Add child button (on hover) */}
        {onAddChild && canHaveChildren && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              onAddChild(node.id);
            }}
            className="ml-auto opacity-0 group-hover:opacity-100 p-1 text-gray-400 hover:text-purple-600 hover:bg-purple-50 rounded transition-all flex-shrink-0"
            title="Add child unit"
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
          </button>
        )}
      </div>

      {/* Children */}
      {hasChildren && isExpanded && (
        <div>
          {node.children.map(child => (
            <OrgTreeNode
              key={child.id}
              node={child}
              depth={depth + 1}
              isExpanded={expandedIds.has(child.id)}
              isSelected={selectedNodeId === child.id}
              onToggle={onToggle}
              onSelect={onSelect}
              onAddChild={onAddChild}
              getLevelColor={getLevelColor}
              expandedIds={expandedIds}
              selectedNodeId={selectedNodeId}
              maxLevelNumber={maxLevelNumber}
            />
          ))}
        </div>
      )}
    </div>
  );
}
