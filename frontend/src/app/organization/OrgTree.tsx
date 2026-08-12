'use client';

import { useState, useCallback } from 'react';
import { OrgTreeNode as OrgTreeNodeType, OrgLevel } from '@/types';
import OrgTreeNode from './OrgTreeNode';

interface Props {
  nodes: OrgTreeNodeType[];
  levels: OrgLevel[];
  selectedNodeId: number | null;
  onSelectNode: (id: number | null) => void;
  onAddChild?: (parentId: number | null) => void;
}

const LEVEL_COLORS = [
  { bg: 'bg-purple-100', text: 'text-purple-700', border: 'border-purple-200' },
  { bg: 'bg-blue-100', text: 'text-blue-700', border: 'border-blue-200' },
  { bg: 'bg-emerald-100', text: 'text-emerald-700', border: 'border-emerald-200' },
  { bg: 'bg-amber-100', text: 'text-amber-700', border: 'border-amber-200' },
  { bg: 'bg-rose-100', text: 'text-rose-700', border: 'border-rose-200' },
  { bg: 'bg-cyan-100', text: 'text-cyan-700', border: 'border-cyan-200' },
  { bg: 'bg-indigo-100', text: 'text-indigo-700', border: 'border-indigo-200' },
  { bg: 'bg-teal-100', text: 'text-teal-700', border: 'border-teal-200' },
  { bg: 'bg-orange-100', text: 'text-orange-700', border: 'border-orange-200' },
];

export default function OrgTree({ nodes, levels, selectedNodeId, onSelectNode, onAddChild }: Props) {
  const [expandedIds, setExpandedIds] = useState<Set<number>>(() => {
    // Auto-expand root nodes
    const initial = new Set<number>();
    for (const node of nodes) {
      initial.add(node.id);
    }
    return initial;
  });

  const toggleExpand = useCallback((nodeId: number) => {
    setExpandedIds(prev => {
      const next = new Set(prev);
      if (next.has(nodeId)) {
        next.delete(nodeId);
      } else {
        next.add(nodeId);
      }
      return next;
    });
  }, []);

  const getLevelColor = (levelNumber: number) => {
    return LEVEL_COLORS[(levelNumber - 1) % LEVEL_COLORS.length];
  };

  const maxLevelNumber = levels.length > 0 ? Math.max(...levels.map(l => l.level_number)) : 1;

  if (nodes.length === 0) {
    return (
      <div className="py-8 text-center text-gray-400 text-sm">
        No organization units found.
      </div>
    );
  }

  return (
    <div className="space-y-1 overflow-x-auto">
      {nodes.map(node => (
        <OrgTreeNode
          key={node.id}
          node={node}
          depth={0}
          isExpanded={expandedIds.has(node.id)}
          isSelected={selectedNodeId === node.id}
          onToggle={toggleExpand}
          onSelect={onSelectNode}
          onAddChild={onAddChild}
          getLevelColor={getLevelColor}
          expandedIds={expandedIds}
          selectedNodeId={selectedNodeId}
          maxLevelNumber={maxLevelNumber}
        />
      ))}
    </div>
  );
}

export { LEVEL_COLORS };
