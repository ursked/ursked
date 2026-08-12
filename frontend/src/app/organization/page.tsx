'use client';

import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import DashboardLayout from '@/components/layout/DashboardLayout';
import { useAuth } from '@/contexts/AuthContext';
import { useToast } from '@/components/ui/Toast';
import { hasAnyRole } from '@/lib/roles';
import { api } from '@/lib/api';
import { OrgTreeNode as OrgTreeNodeType } from '@/types';
import LevelConfigModal from './LevelConfigModal';
import OrgTree from './OrgTree';
import OrgChart from './OrgChart';
import NodeDetailPanel from './NodeDetailPanel';
import NodeCreateModal from './NodeCreateModal';

const EDITOR_ROLES = ['tenant_admin', 'hr'];

export default function OrganizationPage() {
  const { user } = useAuth();
  const { showToast } = useToast();
  const queryClient = useQueryClient();
  const canEdit = user ? hasAnyRole(user, EDITOR_ROLES) : false;

  const [showLevelsModal, setShowLevelsModal] = useState(false);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [selectedNodeId, setSelectedNodeId] = useState<number | null>(null);
  const [createParentId, setCreateParentId] = useState<number | null>(null);
  const [viewMode, setViewMode] = useState<'list' | 'chart'>('list');

  const { data: treeData, isLoading } = useQuery({
    queryKey: ['org-tree'],
    queryFn: () => api.getOrgTree(),
    staleTime: 30_000,
  });

  const levels = treeData?.levels ?? [];
  const nodes = treeData?.nodes ?? [];
  const hasLevels = levels.length > 0;

  const handleAddChild = (parentId: number | null) => {
    setCreateParentId(parentId);
    setShowCreateModal(true);
  };

  const handleNodeCreated = () => {
    queryClient.invalidateQueries({ queryKey: ['org-tree'] });
    setShowCreateModal(false);
    showToast('Organization unit created', 'success');
  };

  const handleNodeUpdated = () => {
    queryClient.invalidateQueries({ queryKey: ['org-tree'] });
    showToast('Organization unit updated', 'success');
  };

  const handleNodeDeleted = () => {
    queryClient.invalidateQueries({ queryKey: ['org-tree'] });
    setSelectedNodeId(null);
    showToast('Organization unit deleted', 'success');
  };

  const handleLevelsSaved = () => {
    queryClient.invalidateQueries({ queryKey: ['org-tree'] });
    queryClient.invalidateQueries({ queryKey: ['org-levels'] });
    setShowLevelsModal(false);
    showToast('Organization levels updated', 'success');
  };

  return (
    <DashboardLayout>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Organization</h1>
            <p className="text-gray-500 mt-1">Manage your organizational hierarchy and structure</p>
          </div>
          {canEdit && (
            <div className="flex flex-wrap gap-2">
              <button
                onClick={() => setShowLevelsModal(true)}
                className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors flex items-center gap-2"
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                </svg>
                Configure Levels
              </button>
              {hasLevels && (
                <button
                  onClick={() => handleAddChild(null)}
                  className="px-4 py-2 text-sm font-medium text-white bg-purple-600 hover:bg-purple-700 rounded-lg transition-colors flex items-center gap-2"
                >
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                  </svg>
                  Add Root Unit
                </button>
              )}
            </div>
          )}
        </div>

        {/* Content */}
        {isLoading ? (
          <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-12 flex items-center justify-center">
            <svg className="w-8 h-8 animate-spin text-purple-600" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
          </div>
        ) : !hasLevels ? (
          <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-12 text-center">
            <div className="mx-auto w-16 h-16 bg-purple-50 rounded-full flex items-center justify-center mb-4">
              <svg className="w-8 h-8 text-purple-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
              </svg>
            </div>
            <h3 className="text-lg font-semibold text-gray-900 mb-2">No levels configured</h3>
            <p className="text-gray-500 mb-6 max-w-md mx-auto">
              Start by defining your organization levels (e.g., Department, Division, Section).
              Add as many levels as you need — shallow or deep.
            </p>
            {canEdit && (
              <button
                onClick={() => setShowLevelsModal(true)}
                className="px-6 py-2.5 text-sm font-medium text-white bg-purple-600 hover:bg-purple-700 rounded-lg transition-colors"
              >
                Configure Levels
              </button>
            )}
          </div>
        ) : nodes.length === 0 ? (
          <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-12 text-center">
            <div className="mx-auto w-16 h-16 bg-purple-50 rounded-full flex items-center justify-center mb-4">
              <svg className="w-8 h-8 text-purple-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 10h16M4 14h16M4 18h16" />
              </svg>
            </div>
            <h3 className="text-lg font-semibold text-gray-900 mb-2">No organization units yet</h3>
            <p className="text-gray-500 mb-2">Levels configured: {levels.map(l => l.name).join(' → ')}</p>
            <p className="text-gray-500 mb-6">Add your first root organization unit to get started.</p>
            {canEdit && (
              <button
                onClick={() => handleAddChild(null)}
                className="px-6 py-2.5 text-sm font-medium text-white bg-purple-600 hover:bg-purple-700 rounded-lg transition-colors"
              >
                Add Root Unit
              </button>
            )}
          </div>
        ) : (
          <div className="flex flex-col lg:flex-row gap-6">
            {/* Tree */}
            <div className={`bg-white rounded-xl shadow-sm border border-gray-100 p-4 min-w-0 ${selectedNodeId ? 'lg:flex-1' : 'w-full'}`}>
              <div className="flex items-center justify-between gap-2 mb-4 px-2">
                <div className="flex items-center gap-2 text-sm text-gray-500 min-w-0 overflow-x-auto">
                  <span className="flex-shrink-0">Levels:</span>
                  {levels.map((l, i) => (
                    <span key={l.id} className="whitespace-nowrap">
                      <span className="font-medium text-gray-700">{l.name}</span>
                      {i < levels.length - 1 && <span className="mx-1">→</span>}
                    </span>
                  ))}
                </div>
                {/* View toggle */}
                <div className="flex items-center bg-gray-100 rounded-lg p-0.5 flex-shrink-0">
                  <button
                    onClick={() => setViewMode('list')}
                    className={`px-2.5 py-1.5 rounded-md text-xs font-medium transition-colors flex items-center gap-1.5 ${
                      viewMode === 'list'
                        ? 'bg-white text-gray-900 shadow-sm'
                        : 'text-gray-500 hover:text-gray-700'
                    }`}
                  >
                    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 10h16M4 14h16M4 18h16" />
                    </svg>
                    List
                  </button>
                  <button
                    onClick={() => setViewMode('chart')}
                    className={`px-2.5 py-1.5 rounded-md text-xs font-medium transition-colors flex items-center gap-1.5 ${
                      viewMode === 'chart'
                        ? 'bg-white text-gray-900 shadow-sm'
                        : 'text-gray-500 hover:text-gray-700'
                    }`}
                  >
                    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 5a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM14 5a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1h-4a1 1 0 01-1-1V5zM9 15a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1h-4a1 1 0 01-1-1v-4z" />
                    </svg>
                    Chart
                  </button>
                </div>
              </div>
              {viewMode === 'list' ? (
                <OrgTree
                  nodes={nodes}
                  levels={levels}
                  selectedNodeId={selectedNodeId}
                  onSelectNode={setSelectedNodeId}
                  onAddChild={canEdit ? handleAddChild : undefined}
                />
              ) : (
                <OrgChart
                  nodes={nodes}
                  levels={levels}
                  selectedNodeId={selectedNodeId}
                  onSelectNode={setSelectedNodeId}
                  onAddChild={canEdit ? handleAddChild : undefined}
                />
              )}
            </div>

            {/* Detail Panel */}
            {selectedNodeId && (
              <div className="w-full lg:w-96 flex-shrink-0">
                <NodeDetailPanel
                  nodeId={selectedNodeId}
                  canEdit={canEdit}
                  onClose={() => setSelectedNodeId(null)}
                  onUpdated={handleNodeUpdated}
                  onDeleted={handleNodeDeleted}
                  onAddChild={canEdit ? handleAddChild : undefined}
                />
              </div>
            )}
          </div>
        )}
      </div>

      {/* Modals */}
      {showLevelsModal && (
        <LevelConfigModal
          currentLevels={levels}
          onClose={() => setShowLevelsModal(false)}
          onSaved={handleLevelsSaved}
        />
      )}

      {showCreateModal && (
        <NodeCreateModal
          parentId={createParentId}
          levels={levels}
          nodes={nodes}
          onClose={() => setShowCreateModal(false)}
          onCreated={handleNodeCreated}
        />
      )}
    </DashboardLayout>
  );
}
