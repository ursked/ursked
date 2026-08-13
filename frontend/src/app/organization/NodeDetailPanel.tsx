'use client';

import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useToast } from '@/components/ui/Toast';
import { api } from '@/lib/api';
import { OrgNodeDetail, OrgNodeMember } from '@/types';
import MemberAssignModal from './MemberAssignModal';

const VISIBILITY_LABELS: Record<string, string> = {
  '': 'Inherited',
  own_node: 'Own node only',
  own_and_children: 'Own node + below',
  own_and_parent: 'Own node + parent',
  all: 'Whole organization',
};

interface Props {
  nodeId: number;
  canEdit: boolean;
  onClose: () => void;
  onUpdated: () => void;
  onDeleted: () => void;
  onAddChild?: (parentId: number) => void;
}

export default function NodeDetailPanel({ nodeId, canEdit, onClose, onUpdated, onDeleted, onAddChild }: Props) {
  const { showToast } = useToast();
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [showMemberModal, setShowMemberModal] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [formData, setFormData] = useState({
    name: '',
    code: '',
    description: '',
    schedule_visibility: '',
  });

  const { data: node, isLoading } = useQuery<OrgNodeDetail>({
    queryKey: ['org-node', nodeId],
    queryFn: () => api.getOrgNode(nodeId),
    staleTime: 15_000,
  });

  const { data: membersData } = useQuery({
    queryKey: ['org-node-members', nodeId],
    queryFn: () => api.getOrgNodeMembers(nodeId),
    staleTime: 15_000,
  });

  useEffect(() => {
    if (node) {
      setFormData({
        name: node.name,
        code: node.code || '',
        description: node.description || '',
        schedule_visibility: node.schedule_visibility || '',
      });
      setEditing(false);
      setConfirmDelete(false);
    }
  }, [node]);

  const updateMutation = useMutation({
    mutationFn: (data: Record<string, unknown>) => api.updateOrgNode(nodeId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['org-node', nodeId] });
      setEditing(false);
      onUpdated();
    },
    onError: (error: Error) => {
      showToast(error.message, 'error');
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => api.deleteOrgNode(nodeId),
    onSuccess: () => {
      onDeleted();
    },
    onError: (error: Error) => {
      showToast(error.message, 'error');
    },
  });

  const unassignMutation = useMutation({
    mutationFn: (userId: number) => api.unassignOrgNodeMembers(nodeId, [userId]),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['org-node-members', nodeId] });
      queryClient.invalidateQueries({ queryKey: ['org-tree'] });
      showToast('Member removed', 'success');
    },
    onError: (error: Error) => {
      showToast(error.message, 'error');
    },
  });

  const handleSave = () => {
    const updates: Record<string, unknown> = {};
    if (formData.name !== node?.name) updates.name = formData.name;
    if (formData.code !== (node?.code || '')) updates.code = formData.code || null;
    if (formData.description !== (node?.description || '')) updates.description = formData.description || null;
    if (formData.schedule_visibility !== (node?.schedule_visibility || '')) {
      // Empty string means "inherit" — send 'inherit' so the backend clears the override.
      updates.schedule_visibility = formData.schedule_visibility || 'inherit';
    }

    if (Object.keys(updates).length === 0) {
      setEditing(false);
      return;
    }
    updateMutation.mutate(updates);
  };

  const handleDelete = () => {
    if (!confirmDelete) {
      setConfirmDelete(true);
      return;
    }
    deleteMutation.mutate();
  };

  const handleMembersAssigned = () => {
    queryClient.invalidateQueries({ queryKey: ['org-node-members', nodeId] });
    queryClient.invalidateQueries({ queryKey: ['org-tree'] });
    setShowMemberModal(false);
    showToast('Members assigned', 'success');
  };

  const members: OrgNodeMember[] = membersData?.members ?? [];

  if (isLoading || !node) {
    return (
      <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
        <div className="flex items-center justify-center py-8">
          <svg className="w-6 h-6 animate-spin text-purple-600" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
        </div>
      </div>
    );
  }

  return (
    <>
      <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b bg-gray-50">
          <h3 className="text-sm font-semibold text-gray-900">Node Details</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="p-4 space-y-4">
          {/* Level badge + name */}
          <div>
            <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-purple-100 text-purple-700 mb-2">
              {node.level_name}
            </span>
            {editing ? (
              <div className="space-y-3 mt-2">
                <div>
                  <label className="block text-xs font-medium text-gray-500 mb-1">Name</label>
                  <input
                    type="text"
                    value={formData.name}
                    onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-purple-500 focus:border-transparent outline-none"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-500 mb-1">Code</label>
                  <input
                    type="text"
                    value={formData.code}
                    onChange={(e) => setFormData({ ...formData, code: e.target.value })}
                    placeholder="Optional short code"
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-purple-500 focus:border-transparent outline-none"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-500 mb-1">Description</label>
                  <textarea
                    value={formData.description}
                    onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                    placeholder="Optional description"
                    rows={2}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-purple-500 focus:border-transparent outline-none resize-none"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-500 mb-1">Schedule visibility</label>
                  <select
                    value={formData.schedule_visibility}
                    onChange={(e) => setFormData({ ...formData, schedule_visibility: e.target.value })}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-purple-500 focus:border-transparent outline-none"
                  >
                    <option value="">Inherit from parent / tenant default</option>
                    <option value="own_node">Own node only</option>
                    <option value="own_and_children">Own node + everything below</option>
                    <option value="own_and_parent">Own node + parent</option>
                    <option value="all">Everyone (whole organization)</option>
                  </select>
                  <p className="mt-1 text-xs text-gray-400">
                    Controls whose schedules members of this node can see. Overrides the tenant default; child nodes inherit unless they set their own.
                  </p>
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={handleSave}
                    disabled={updateMutation.isPending}
                    className="px-3 py-1.5 text-xs font-medium text-white bg-purple-600 hover:bg-purple-700 rounded-lg disabled:opacity-50"
                  >
                    {updateMutation.isPending ? 'Saving...' : 'Save'}
                  </button>
                  <button
                    onClick={() => { setEditing(false); setFormData({ name: node.name, code: node.code || '', description: node.description || '', schedule_visibility: node.schedule_visibility || '' }); }}
                    className="px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-100 rounded-lg"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <div>
                <h4 className="text-lg font-semibold text-gray-900">{node.name}</h4>
                {node.code && <p className="text-sm text-gray-500">Code: {node.code}</p>}
                {node.description && <p className="text-sm text-gray-500 mt-1">{node.description}</p>}
                {!node.is_active && (
                  <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-red-100 text-red-700 mt-1">
                    Inactive
                  </span>
                )}
              </div>
            )}
          </div>

          {/* Head / Deputy */}
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-sm">
              <svg className="w-4 h-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
              </svg>
              <span className="text-gray-500">Head:</span>
              <span className="font-medium text-gray-900">{node.head_user_name || '—'}</span>
            </div>
            <div className="flex items-center gap-2 text-sm">
              <svg className="w-4 h-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
              </svg>
              <span className="text-gray-500">Deputy:</span>
              <span className="font-medium text-gray-900">{node.deputy_head_user_name || '—'}</span>
            </div>
            <div className="flex items-center gap-2 text-sm">
              <svg className="w-4 h-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
              </svg>
              <span className="text-gray-500">Visibility:</span>
              <span className="font-medium text-gray-900">
                {VISIBILITY_LABELS[node.schedule_visibility || ''] || 'Inherited'}
              </span>
            </div>
          </div>

          {/* Actions */}
          {canEdit && !editing && (
            <div className="flex flex-wrap gap-2">
              <button
                onClick={() => setEditing(true)}
                className="px-3 py-1.5 text-xs font-medium text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors"
              >
                Edit
              </button>
              {onAddChild && (
                <button
                  onClick={() => onAddChild(node.id)}
                  className="px-3 py-1.5 text-xs font-medium text-purple-700 bg-purple-50 hover:bg-purple-100 rounded-lg transition-colors"
                >
                  Add Child
                </button>
              )}
              <button
                onClick={handleDelete}
                disabled={deleteMutation.isPending}
                className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${
                  confirmDelete
                    ? 'text-white bg-red-600 hover:bg-red-700'
                    : 'text-red-600 bg-red-50 hover:bg-red-100'
                } disabled:opacity-50`}
              >
                {deleteMutation.isPending ? 'Deleting...' : confirmDelete ? 'Confirm Delete' : 'Delete'}
              </button>
              {confirmDelete && (
                <button
                  onClick={() => setConfirmDelete(false)}
                  className="px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-100 rounded-lg"
                >
                  Cancel
                </button>
              )}
            </div>
          )}

          {/* Members section */}
          <div className="border-t pt-4">
            <div className="flex items-center justify-between mb-3">
              <h4 className="text-sm font-semibold text-gray-900">
                Members ({members.length})
              </h4>
              {canEdit && (
                <button
                  onClick={() => setShowMemberModal(true)}
                  className="text-xs font-medium text-purple-600 hover:text-purple-700 flex items-center gap-1"
                >
                  <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                  </svg>
                  Assign
                </button>
              )}
            </div>
            {members.length === 0 ? (
              <p className="text-sm text-gray-400 text-center py-3">No members assigned</p>
            ) : (
              <div className="space-y-2 max-h-60 overflow-y-auto">
                {members.map(member => (
                  <div key={`${member.id}-${member.is_primary ? 'p' : 's'}`} className="flex items-center justify-between group">
                    <div className="flex items-center gap-2 min-w-0">
                      <div className="w-7 h-7 rounded-full bg-gray-200 flex items-center justify-center text-xs font-medium text-gray-600 flex-shrink-0">
                        {member.first_name[0]}{member.last_name[0]}
                      </div>
                      <div className="min-w-0">
                        <div className="flex items-center gap-1.5">
                          <p className="text-sm font-medium text-gray-900 truncate">
                            {member.first_name} {member.last_name}
                          </p>
                          {!member.is_primary && (
                            <span className="inline-flex items-center rounded-full bg-gray-100 text-gray-500 px-1.5 py-0.5 text-[10px] font-medium flex-shrink-0">
                              Secondary
                            </span>
                          )}
                        </div>
                        {member.job_title && (
                          <p className="text-xs text-gray-400 truncate">{member.job_title}</p>
                        )}
                      </div>
                    </div>
                    {canEdit && (
                      <button
                        onClick={() => unassignMutation.mutate(member.id)}
                        className="opacity-0 group-hover:opacity-100 p-1 text-gray-400 hover:text-red-500 transition-all flex-shrink-0"
                        title="Remove from node"
                      >
                        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                        </svg>
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Member assign modal */}
      {showMemberModal && (
        <MemberAssignModal
          nodeId={nodeId}
          nodeName={node.name}
          existingMemberIds={members.map(m => m.id)}
          onClose={() => setShowMemberModal(false)}
          onAssigned={handleMembersAssigned}
        />
      )}
    </>
  );
}
