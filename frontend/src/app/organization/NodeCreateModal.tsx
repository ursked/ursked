'use client';

import { useState, useMemo } from 'react';
import { useMutation } from '@tanstack/react-query';
import { useToast } from '@/components/ui/Toast';
import { api } from '@/lib/api';
import { OrgLevel, OrgTreeNode } from '@/types';

interface Props {
  parentId: number | null;
  levels: OrgLevel[];
  nodes: OrgTreeNode[];
  onClose: () => void;
  onCreated: () => void;
}

function findNodeInTree(nodes: OrgTreeNode[], id: number): OrgTreeNode | null {
  for (const node of nodes) {
    if (node.id === id) return node;
    const found = findNodeInTree(node.children, id);
    if (found) return found;
  }
  return null;
}

export default function NodeCreateModal({ parentId, levels, nodes, onClose, onCreated }: Props) {
  const { showToast } = useToast();

  // Determine the correct level for this new node
  const parentNode = parentId ? findNodeInTree(nodes, parentId) : null;
  const parentLevelNumber = parentNode?.level_number ?? 0;

  // Available levels for this node (must be > parent level)
  const availableLevels = useMemo(() => {
    if (parentId === null) {
      // Root node - must be level 1
      return levels.filter(l => l.level_number === 1);
    }
    return levels.filter(l => l.level_number > parentLevelNumber);
  }, [parentId, levels, parentLevelNumber]);

  const defaultLevelId = availableLevels.length > 0 ? availableLevels[0].id : 0;

  const [formData, setFormData] = useState({
    name: '',
    code: '',
    description: '',
    level_id: defaultLevelId,
  });

  const createMutation = useMutation({
    mutationFn: (data: {
      parent_id?: number | null;
      level_id: number;
      name: string;
      code?: string;
      description?: string;
    }) => api.createOrgNode(data),
    onSuccess: () => {
      onCreated();
    },
    onError: (error: Error) => {
      showToast(error.message, 'error');
    },
  });

  const handleSubmit = () => {
    if (!formData.name.trim()) {
      showToast('Name is required', 'error');
      return;
    }
    if (!formData.level_id) {
      showToast('Level is required', 'error');
      return;
    }

    createMutation.mutate({
      parent_id: parentId,
      level_id: formData.level_id,
      name: formData.name.trim(),
      ...(formData.code.trim() ? { code: formData.code.trim() } : {}),
      ...(formData.description.trim() ? { description: formData.description.trim() } : {}),
    });
  };

  const selectedLevel = levels.find(l => l.id === formData.level_id);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative bg-white rounded-xl shadow-2xl w-full max-w-lg mx-4">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b">
          <h2 className="text-lg font-semibold text-gray-900">
            {parentNode ? `Add child under "${parentNode.name}"` : 'Add Root Organization Unit'}
          </h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-4 space-y-4">
          {/* Level selection */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Level</label>
            {availableLevels.length === 1 ? (
              <div className="flex items-center gap-2">
                <span className="inline-flex items-center px-2.5 py-1 rounded text-sm font-medium bg-purple-100 text-purple-700">
                  {availableLevels[0].name}
                </span>
                <span className="text-xs text-gray-400">(Level {availableLevels[0].level_number})</span>
              </div>
            ) : availableLevels.length > 1 ? (
              <select
                value={formData.level_id}
                onChange={(e) => setFormData({ ...formData, level_id: Number(e.target.value) })}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-purple-500 focus:border-transparent outline-none bg-white"
              >
                {availableLevels.map(l => (
                  <option key={l.id} value={l.id}>
                    {l.name} (Level {l.level_number})
                  </option>
                ))}
              </select>
            ) : (
              <p className="text-sm text-red-500">No available levels. You may need to add more levels first.</p>
            )}
          </div>

          {/* Name */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Name</label>
            <input
              type="text"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              placeholder={`e.g., ${selectedLevel?.name || 'Unit'} A`}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-purple-500 focus:border-transparent outline-none"
              maxLength={200}
              autoFocus
            />
          </div>

          {/* Code */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Code <span className="text-gray-400 font-normal">(optional)</span>
            </label>
            <input
              type="text"
              value={formData.code}
              onChange={(e) => setFormData({ ...formData, code: e.target.value })}
              placeholder="e.g., DEPT-001"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-purple-500 focus:border-transparent outline-none"
              maxLength={50}
            />
          </div>

          {/* Description */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Description <span className="text-gray-400 font-normal">(optional)</span>
            </label>
            <textarea
              value={formData.description}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              placeholder="Brief description of this organization unit"
              rows={2}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-purple-500 focus:border-transparent outline-none resize-none"
            />
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 px-6 py-4 border-t bg-gray-50 rounded-b-xl">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100 rounded-lg transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={createMutation.isPending || !formData.name.trim() || !formData.level_id}
            className="px-4 py-2 text-sm font-medium text-white bg-purple-600 hover:bg-purple-700 rounded-lg transition-colors disabled:opacity-50 flex items-center gap-2"
          >
            {createMutation.isPending && (
              <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
            )}
            Create
          </button>
        </div>
      </div>
    </div>
  );
}
