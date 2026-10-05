'use client';

import { useState, useEffect, useMemo } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useToast } from '@/components/ui/Toast';
import { ErrorMessage } from '@/components/ui/ErrorBoundary';
import { UserPicker } from '@/components/ui';
import { api } from '@/lib/api';
import { EffectiveChainResponse, OrgNodeDeletePreview, OrgNodeDetail, OrgNodeMember, OrgTreeNode } from '@/types';
import { ApproverCheckNote } from '@/app/leaves/leaveUi';
import MemberAssignModal from './MemberAssignModal';

const VISIBILITY_LABELS: Record<string, string> = {
  '': 'Inherited',
  own_node: 'Own node only',
  own_and_children: 'Own node + below',
  own_and_parent: 'Own node + parent',
  all: 'Whole organization',
};

const CHAIN_SOURCE: Record<string, string> = {
  auto: 'unit head',
  hybrid_org_chart: 'unit head',
  manual_employee: 'approval rule for this person',
  manual_org_node: 'approval rule for this unit',
  manual_cascade: 'approval rule for a unit above',
  manual_default: 'default approval rule',
  fallback_manager: 'line manager (no other approver)',
  fallback_tenant_admin: 'administrator (no other approver)',
  fallback_hr: 'HR (no other approver)',
  fallback_leave_editor: 'leave administrator (no other approver)',
  self_approval: 'self-approval: nobody else can approve',
};

interface Props {
  nodeId: number;
  canEdit: boolean;
  canDelete?: boolean;
  canViewMembers?: boolean;
  nodes?: OrgTreeNode[];
  onClose: () => void;
  onUpdated: () => void;
  onDeleted: () => void;
  onAddChild?: (parentId: number) => void;
}

interface FlatNode { id: number; name: string; level_number: number; level_name: string; depth: number; parent_id: number | null }

function flatten(nodes: OrgTreeNode[], depth = 0, acc: FlatNode[] = []): FlatNode[] {
  for (const n of nodes) {
    acc.push({ id: n.id, name: n.name, level_number: n.level_number, level_name: n.level_name, depth, parent_id: n.parent_id });
    flatten(n.children || [], depth + 1, acc);
  }
  return acc;
}

function descendantIds(nodes: FlatNode[], rootId: number): Set<number> {
  const out = new Set<number>([rootId]);
  let grew = true;
  while (grew) {
    grew = false;
    for (const n of nodes) {
      if (n.parent_id !== null && out.has(n.parent_id) && !out.has(n.id)) {
        out.add(n.id);
        grew = true;
      }
    }
  }
  return out;
}

const FIELD = 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brand-500 focus:border-transparent outline-none';

export default function NodeDetailPanel({
  nodeId, canEdit, canDelete = false, canViewMembers = true, nodes = [], onClose, onUpdated, onDeleted, onAddChild,
}: Props) {
  const { showToast } = useToast();
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [memberModal, setMemberModal] = useState<null | 'primary' | 'secondary'>(null);
  const [showDelete, setShowDelete] = useState(false);
  const [sampleMember, setSampleMember] = useState<number | null>(null);
  const [formData, setFormData] = useState({
    name: '',
    code: '',
    description: '',
    schedule_visibility: '',
    head_user_id: null as number | null,
    deputy_head_user_id: null as number | null,
    parent_id: null as number | null,
  });

  const { data: node, isLoading, isError, refetch } = useQuery<OrgNodeDetail>({
    queryKey: ['org-node', nodeId],
    queryFn: () => api.getOrgNode(nodeId),
    staleTime: 15_000,
  });

  const { data: membersData } = useQuery({
    queryKey: ['org-node-members', nodeId],
    queryFn: () => api.getOrgNodeMembers(nodeId),
    staleTime: 15_000,
    enabled: canViewMembers,
  });

  const { data: chain, isFetching: chainLoading, error: chainError } = useQuery<EffectiveChainResponse>({
    queryKey: ['effective-chain', sampleMember],
    queryFn: () => api.getEffectiveApprovalChain(sampleMember as number),
    enabled: sampleMember !== null,
  });

  const { data: deletePreview, isFetching: previewLoading } = useQuery<OrgNodeDeletePreview>({
    queryKey: ['org-node-delete-preview', nodeId],
    queryFn: () => api.getOrgNodeDeletePreview(nodeId),
    enabled: showDelete,
  });

  const flat = useMemo(() => flatten(nodes), [nodes]);
  const self = flat.find((n) => n.id === nodeId);
  // Where this unit may move: any unit on a higher level that is not itself
  // or below it (the server refuses cycles too; this just avoids offering them).
  const moveTargets = useMemo(() => {
    if (!self) return [];
    const banned = descendantIds(flat, nodeId);
    return flat.filter((n) => !banned.has(n.id) && n.level_number < self.level_number);
  }, [flat, self, nodeId]);

  const resetForm = (n: OrgNodeDetail) => ({
    name: n.name,
    code: n.code || '',
    description: n.description || '',
    schedule_visibility: n.schedule_visibility || '',
    head_user_id: n.head_user_id,
    deputy_head_user_id: n.deputy_head_user_id,
    parent_id: n.parent_id,
  });

  useEffect(() => {
    if (!node) return;
    let active = true;
    // Defer so state updates do not run synchronously in the effect body
    // (react-hooks/set-state-in-effect).
    void Promise.resolve().then(() => {
      if (!active) return;
      setFormData(resetForm(node));
      setEditing(false);
      setShowDelete(false);
      setSampleMember(null);
    });
    return () => {
      active = false;
    };
  }, [node]);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['org-node', nodeId] });
    queryClient.invalidateQueries({ queryKey: ['org-node-members', nodeId] });
    queryClient.invalidateQueries({ queryKey: ['org-tree'] });
    queryClient.invalidateQueries({ queryKey: ['effective-chain'] });
  };

  const updateMutation = useMutation({
    mutationFn: (data: Record<string, unknown>) => api.updateOrgNode(nodeId, data),
    onSuccess: () => {
      invalidate();
      setEditing(false);
      onUpdated();
    },
    onError: (error: Error) => showToast(error.message, 'error'),
  });

  const deleteMutation = useMutation({
    mutationFn: () => api.deleteOrgNode(nodeId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['approver-assignments'] });
      onDeleted();
    },
    onError: (error: Error) => showToast(error.message, 'error'),
  });

  // Primary and secondary memberships are removed through different
  // endpoints. Both used to go to the primary one, which took a secondary
  // member out of their real team elsewhere.
  const removeMutation = useMutation({
    mutationFn: async (m: OrgNodeMember): Promise<void> => {
      if (m.is_primary) await api.unassignOrgNodeMembers(nodeId, [m.id]);
      else await api.removeSecondaryMembers(nodeId, [m.id]);
    },
    onSuccess: (_d, m) => {
      invalidate();
      showToast(m.is_primary ? 'Member removed from this unit' : 'Secondary membership removed', 'success');
    },
    onError: (error: Error) => showToast(error.message, 'error'),
  });

  const handleSave = () => {
    if (!node) return;
    const updates: Record<string, unknown> = {};
    if (formData.name !== node.name) updates.name = formData.name;
    if (formData.code !== (node.code || '')) updates.code = formData.code || null;
    if (formData.description !== (node.description || '')) updates.description = formData.description || null;
    if (formData.schedule_visibility !== (node.schedule_visibility || '')) {
      // Empty string means "inherit" — send 'inherit' so the backend clears the override.
      updates.schedule_visibility = formData.schedule_visibility || 'inherit';
    }
    if (formData.head_user_id !== node.head_user_id) updates.head_user_id = formData.head_user_id;
    if (formData.deputy_head_user_id !== node.deputy_head_user_id) updates.deputy_head_user_id = formData.deputy_head_user_id;
    if (formData.parent_id !== node.parent_id) updates.parent_id = formData.parent_id;

    if (Object.keys(updates).length === 0) {
      setEditing(false);
      return;
    }
    updateMutation.mutate(updates);
  };

  const members: OrgNodeMember[] = membersData?.members ?? [];

  // `isLoading || !node` spun forever on failure: isLoading goes false, node
  // stays undefined, and the panel never leaves its loading branch.
  if (isError || (!isLoading && !node)) {
    return (
      <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
        <ErrorMessage message="Could not load this unit." onRetry={() => refetch()} />
      </div>
    );
  }

  if (isLoading || !node) {
    return (
      <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
        <div className="flex items-center justify-center py-8 text-sm text-gray-500">Loading...</div>
      </div>
    );
  }

  const parentName = flat.find((n) => n.id === node.parent_id)?.name;

  return (
    <>
      <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b bg-gray-50">
          <h3 className="text-sm font-semibold text-gray-900">Unit details</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600" aria-label="Close details">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="p-4 space-y-4">
          <div>
            <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-brand-100 text-brand-700 mb-2">
              {node.level_name}
            </span>
            {editing ? (
              <div className="space-y-3 mt-2">
                <div>
                  <label htmlFor="nd-name" className="block text-xs font-medium text-gray-500 mb-1">Name</label>
                  <input id="nd-name" type="text" value={formData.name}
                    onChange={(e) => setFormData({ ...formData, name: e.target.value })} className={FIELD} />
                </div>
                <div>
                  <label htmlFor="nd-code" className="block text-xs font-medium text-gray-500 mb-1">Code</label>
                  <input id="nd-code" type="text" value={formData.code} placeholder="Optional short code"
                    onChange={(e) => setFormData({ ...formData, code: e.target.value })} className={FIELD} />
                </div>
                <div>
                  <label htmlFor="nd-desc" className="block text-xs font-medium text-gray-500 mb-1">Description</label>
                  <textarea id="nd-desc" value={formData.description} placeholder="Optional description" rows={2}
                    onChange={(e) => setFormData({ ...formData, description: e.target.value })} className={`${FIELD} resize-none`} />
                </div>
                <div>
                  <UserPicker label="Head" value={formData.head_user_id}
                    onChange={(id) => setFormData({ ...formData, head_user_id: id })} />
                  {formData.head_user_id !== node.head_user_id && <ApproverCheckNote userId={formData.head_user_id} />}
                </div>
                <div>
                  <UserPicker label="Deputy" value={formData.deputy_head_user_id}
                    onChange={(id) => setFormData({ ...formData, deputy_head_user_id: id })}
                    excludeIds={formData.head_user_id ? [formData.head_user_id] : []} />
                  {formData.deputy_head_user_id !== node.deputy_head_user_id && (
                    <ApproverCheckNote userId={formData.deputy_head_user_id} />
                  )}
                  <p className="mt-1 text-xs text-gray-400">
                    When the unit routes leave through the org chart, the head approves it. The deputy stands in
                    whenever the head is not set, inactive, or on approved leave that day.
                  </p>
                </div>
                <div>
                  <label htmlFor="nd-parent" className="block text-xs font-medium text-gray-500 mb-1">Move under…</label>
                  <select id="nd-parent" value={formData.parent_id ?? ''}
                    onChange={(e) => setFormData({ ...formData, parent_id: e.target.value ? Number(e.target.value) : null })}
                    className={FIELD}>
                    {self?.level_number === 1 && <option value="">(Top level)</option>}
                    {moveTargets.map((n) => (
                      <option key={n.id} value={n.id}>
                        {' '.repeat(n.depth * 3)}{n.level_name}: {n.name}
                      </option>
                    ))}
                  </select>
                  <p className="mt-1 text-xs text-gray-400">
                    Only units on a higher level, and not this unit&apos;s own sub-units, are offered. Its members and
                    sub-units move with it.
                  </p>
                </div>
                <div>
                  <label htmlFor="nd-vis" className="block text-xs font-medium text-gray-500 mb-1">Schedule visibility</label>
                  <select id="nd-vis" value={formData.schedule_visibility}
                    onChange={(e) => setFormData({ ...formData, schedule_visibility: e.target.value })} className={FIELD}>
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
                  <button onClick={handleSave} disabled={updateMutation.isPending}
                    className="px-3 py-1.5 text-xs font-medium text-white bg-brand-600 hover:bg-brand-700 rounded-lg disabled:opacity-50">
                    {updateMutation.isPending ? 'Saving...' : 'Save'}
                  </button>
                  <button onClick={() => { setEditing(false); setFormData(resetForm(node)); }}
                    className="px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-100 rounded-lg">
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <div>
                <h4 className="text-lg font-semibold text-gray-900">{node.name}</h4>
                {node.code && <p className="text-sm text-gray-500">Code: {node.code}</p>}
                {node.description && <p className="text-sm text-gray-500 mt-1">{node.description}</p>}
                {parentName && <p className="text-sm text-gray-500 mt-1">Part of: {parentName}</p>}
                {!node.is_active && (
                  <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-red-100 text-red-700 mt-1">Inactive</span>
                )}
              </div>
            )}
          </div>

          {!editing && (
            <dl className="space-y-1 text-sm">
              <div className="flex gap-2"><dt className="text-gray-500">Head:</dt><dd className="font-medium text-gray-900">{node.head_user_name || '—'}</dd></div>
              <div className="flex gap-2"><dt className="text-gray-500">Deputy:</dt><dd className="font-medium text-gray-900">{node.deputy_head_user_name || '—'}</dd></div>
              <div className="flex gap-2"><dt className="text-gray-500">Visibility:</dt><dd className="font-medium text-gray-900">{VISIBILITY_LABELS[node.schedule_visibility || ''] || 'Inherited'}</dd></div>
            </dl>
          )}

          {/* Actions */}
          {!editing && (canEdit || canDelete || onAddChild) && (
            <div className="flex flex-wrap gap-2">
              {canEdit && (
                <button onClick={() => setEditing(true)}
                  className="px-3 py-1.5 text-xs font-medium text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors">
                  Edit
                </button>
              )}
              {onAddChild && (
                <button onClick={() => onAddChild(node.id)}
                  className="px-3 py-1.5 text-xs font-medium text-brand-700 bg-brand-50 hover:bg-brand-100 rounded-lg transition-colors">
                  Add Child
                </button>
              )}
              {canDelete && (
                <button onClick={() => setShowDelete(true)}
                  className="px-3 py-1.5 text-xs font-medium rounded-lg text-red-600 bg-red-50 hover:bg-red-100">
                  Delete
                </button>
              )}
            </div>
          )}

          {/* Members */}
          {canViewMembers && (
            <div className="border-t pt-4">
              <div className="flex items-center justify-between mb-3 gap-2">
                <h4 className="text-sm font-semibold text-gray-900">Members ({members.length})</h4>
                {canEdit && (
                  <div className="flex gap-3">
                    <button onClick={() => setMemberModal('primary')} className="text-xs font-medium text-brand-600 hover:text-brand-700">
                      Assign
                    </button>
                    <button onClick={() => setMemberModal('secondary')} className="text-xs font-medium text-brand-600 hover:text-brand-700">
                      Add secondary member
                    </button>
                  </div>
                )}
              </div>
              {members.length === 0 ? (
                <p className="text-sm text-gray-400 text-center py-3">No members assigned</p>
              ) : (
                <ul className="space-y-2 max-h-60 overflow-y-auto">
                  {members.map(member => (
                    <li key={`${member.id}-${member.is_primary ? 'p' : 's'}`} className="flex items-center justify-between">
                      <div className="min-w-0">
                        <div className="flex items-center gap-1.5">
                          <p className="text-sm font-medium text-gray-900 truncate">{member.first_name} {member.last_name}</p>
                          {!member.is_primary && (
                            <span className="inline-flex items-center rounded-full bg-gray-100 text-gray-500 px-1.5 py-0.5 text-[10px] font-medium flex-shrink-0">Secondary</span>
                          )}
                        </div>
                        {member.job_title && <p className="text-xs text-gray-400 truncate">{member.job_title}</p>}
                      </div>
                      {canEdit && (
                        <button
                          onClick={() => removeMutation.mutate(member)}
                          disabled={removeMutation.isPending}
                          className="p-1.5 text-gray-400 hover:text-red-500 transition-colors flex-shrink-0"
                          title={member.is_primary ? 'Remove from this unit' : 'Remove secondary membership'}
                          aria-label={`Remove ${member.first_name} ${member.last_name}`}
                        >
                          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                          </svg>
                        </button>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {/* Who approves leave here */}
          {canViewMembers && members.length > 0 && (
            <div className="border-t pt-4 space-y-2">
              <h4 className="text-sm font-semibold text-gray-900">Who approves leave here</h4>
              <label htmlFor="nd-sample" className="block text-xs text-gray-500">
                Pick a member to see exactly who their leave would go to if they filed now.
              </label>
              <select id="nd-sample" value={sampleMember ?? ''} className={FIELD}
                onChange={(e) => setSampleMember(e.target.value ? Number(e.target.value) : null)}>
                <option value="">Choose a member…</option>
                {members.map((m) => <option key={m.id} value={m.id}>{m.first_name} {m.last_name}</option>)}
              </select>
              {chainLoading && <p className="text-xs text-gray-500">Working it out…</p>}
              {chainError && <p className="text-xs text-red-700">{(chainError as Error).message}</p>}
              {chain && !chainLoading && (
                <ol className="space-y-1">
                  {chain.chain.map((s) => (
                    <li key={s.step_order} className="text-sm text-gray-800">
                      <span className="font-medium">{s.step_order}. {s.approver_name}</span>
                      <span className="ml-1 text-xs text-gray-500">
                        {CHAIN_SOURCE[s.source] ?? s.source}
                        {s.is_deputy ? ', standing in as deputy' : ''}
                        {s.node_name ? ` (${s.node_name})` : ''}
                      </span>
                    </li>
                  ))}
                </ol>
              )}
            </div>
          )}
        </div>
      </div>

      {memberModal && (
        <MemberAssignModal
          nodeId={nodeId}
          nodeName={node.name}
          mode={memberModal}
          existingMemberIds={members.map(m => m.id)}
          onClose={() => setMemberModal(null)}
          onAssigned={() => {
            invalidate();
            setMemberModal(null);
            showToast(memberModal === 'secondary' ? 'Secondary members added' : 'Members assigned', 'success');
          }}
        />
      )}

      {showDelete && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" role="dialog" aria-modal="true" aria-label="Delete unit">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-lg mx-4 p-6 space-y-4 max-h-[90vh] overflow-y-auto">
            <h3 className="text-lg font-semibold text-gray-900">Delete {node.name}?</h3>
            {previewLoading || !deletePreview ? (
              <p className="text-sm text-gray-500">Checking what this would change…</p>
            ) : !deletePreview.can_delete ? (
              <p className="text-sm text-red-700" role="alert">{deletePreview.blocked_reason}</p>
            ) : (
              <div className="space-y-3 text-sm text-gray-700">
                <p>Only this unit is deleted. Nothing below it is deleted with it. These changes will be made:</p>
                <ul className="list-disc pl-5 space-y-1">
                  {deletePreview.members_moved.length > 0 && (
                    <li>
                      {deletePreview.members_moved.length} member(s) move to{' '}
                      {deletePreview.parent_name ?? 'no unit (unassigned)'}:{' '}
                      {deletePreview.members_moved.map((m) => m.name).join(', ')}
                    </li>
                  )}
                  {deletePreview.secondary_members.length > 0 && (
                    <li>
                      {deletePreview.secondary_members.length} secondary membership(s) move to{' '}
                      {deletePreview.parent_name ?? 'nowhere and are removed'}.
                    </li>
                  )}
                  {deletePreview.children_moved.length > 0 && (
                    <li>
                      Sub-unit(s) {deletePreview.children_moved.map((c) => c.name).join(', ')} move under{' '}
                      {deletePreview.parent_name}.
                    </li>
                  )}
                  {deletePreview.approver_rules_deactivated.map((r) => (
                    <li key={`r${r.id}`}>{r.description} is switched off (kept, so you can point it at another unit).</li>
                  ))}
                  {deletePreview.policy_rules_changed.map((r) => (
                    <li key={`p${r.id}`}>
                      Policy rule &ldquo;{r.name}&rdquo; {r.deactivated
                        ? 'applied only to this unit and is switched off.'
                        : 'no longer includes this unit.'}
                    </li>
                  ))}
                  {deletePreview.members_moved.length + deletePreview.children_moved.length +
                    deletePreview.approver_rules_deactivated.length + deletePreview.policy_rules_changed.length +
                    deletePreview.secondary_members.length === 0 && <li>Nothing else refers to this unit.</li>}
                </ul>
              </div>
            )}
            <div className="flex items-center justify-end gap-3">
              <button type="button" onClick={() => setShowDelete(false)}
                className="inline-flex items-center rounded-md bg-white px-4 py-2 text-sm font-semibold text-gray-700 shadow-sm ring-1 ring-inset ring-gray-300 hover:bg-gray-50">
                Cancel
              </button>
              {deletePreview?.can_delete && (
                <button type="button" onClick={() => deleteMutation.mutate()} disabled={deleteMutation.isPending}
                  className="inline-flex items-center rounded-md bg-red-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-red-700 disabled:opacity-50">
                  {deleteMutation.isPending
                    ? 'Deleting...'
                    : deletePreview.parent_name
                      ? `Delete and move everything to ${deletePreview.parent_name}`
                      : 'Delete'}
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
