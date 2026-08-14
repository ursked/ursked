'use client';

import { useState, useMemo } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import { useToast } from '@/components/ui/Toast';
import { api } from '@/lib/api';
import { User } from '@/types';

interface Props {
  nodeId: number;
  nodeName: string;
  existingMemberIds: number[];
  onClose: () => void;
  onAssigned: () => void;
}

export default function MemberAssignModal({ nodeId, nodeName, existingMemberIds, onClose, onAssigned }: Props) {
  const { showToast } = useToast();
  const [search, setSearch] = useState('');
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());

  const { data: usersData, isLoading } = useQuery({
    queryKey: ['users-for-assign'],
    queryFn: () => api.getUsers({ per_page: '100', is_active: 'true' }),
    staleTime: 30_000,
  });

  // Memoized so the array reference is stable across renders (its identity feeds
  // the filteredUsers useMemo below) — react-hooks/exhaustive-deps.
  const users: User[] = useMemo(() => usersData?.items ?? [], [usersData]);

  // Filter out already-assigned members and apply search
  const filteredUsers = useMemo(() => {
    const existingSet = new Set(existingMemberIds);
    return users.filter(u => {
      if (existingSet.has(u.id)) return false;
      if (!search.trim()) return true;
      const q = search.toLowerCase();
      return (
        u.first_name.toLowerCase().includes(q) ||
        u.last_name.toLowerCase().includes(q) ||
        u.email.toLowerCase().includes(q) ||
        (u.job_title && u.job_title.toLowerCase().includes(q))
      );
    });
  }, [users, existingMemberIds, search]);

  const assignMutation = useMutation({
    mutationFn: (userIds: number[]) => api.assignOrgNodeMembers(nodeId, userIds),
    onSuccess: (data) => {
      onAssigned();
    },
    onError: (error: Error) => {
      showToast(error.message, 'error');
    },
  });

  const toggleUser = (userId: number) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(userId)) {
        next.delete(userId);
      } else {
        next.add(userId);
      }
      return next;
    });
  };

  const toggleAll = () => {
    if (selectedIds.size === filteredUsers.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(filteredUsers.map(u => u.id)));
    }
  };

  const handleAssign = () => {
    if (selectedIds.size === 0) {
      showToast('Select at least one employee', 'error');
      return;
    }
    assignMutation.mutate(Array.from(selectedIds));
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative bg-white rounded-xl shadow-2xl w-full max-w-lg mx-4 max-h-[85vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b flex-shrink-0">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Assign Members</h2>
            <p className="text-sm text-gray-500 mt-0.5">to {nodeName}</p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Search */}
        <div className="px-6 py-3 border-b flex-shrink-0">
          <div className="relative">
            <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search employees..."
              className="w-full pl-9 pr-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-purple-500 focus:border-transparent outline-none"
              autoFocus
            />
          </div>
        </div>

        {/* User list */}
        <div className="flex-1 overflow-y-auto px-6 py-2 min-h-0">
          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <svg className="w-6 h-6 animate-spin text-purple-600" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
            </div>
          ) : filteredUsers.length === 0 ? (
            <p className="text-sm text-gray-400 text-center py-8">
              {search ? 'No matching employees found.' : 'All employees are already assigned.'}
            </p>
          ) : (
            <>
              {/* Select all */}
              <button
                onClick={toggleAll}
                className="text-xs font-medium text-purple-600 hover:text-purple-700 mb-2"
              >
                {selectedIds.size === filteredUsers.length ? 'Deselect All' : 'Select All'}
                {' '}({filteredUsers.length})
              </button>
              <div className="space-y-1">
                {filteredUsers.map(user => (
                  <label
                    key={user.id}
                    className={`flex items-center gap-3 px-3 py-2 rounded-lg cursor-pointer transition-colors ${
                      selectedIds.has(user.id) ? 'bg-purple-50' : 'hover:bg-gray-50'
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={selectedIds.has(user.id)}
                      onChange={() => toggleUser(user.id)}
                      className="w-4 h-4 text-purple-600 border-gray-300 rounded focus:ring-purple-500"
                    />
                    <div className="w-7 h-7 rounded-full bg-gray-200 flex items-center justify-center text-xs font-medium text-gray-600 flex-shrink-0">
                      {user.first_name[0]}{user.last_name[0]}
                    </div>
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-gray-900 truncate">
                        {user.first_name} {user.last_name}
                      </p>
                      <p className="text-xs text-gray-400 truncate">
                        {user.job_title || user.email}
                      </p>
                    </div>
                  </label>
                ))}
              </div>
            </>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-6 py-4 border-t bg-gray-50 rounded-b-xl flex-shrink-0">
          <span className="text-sm text-gray-500">
            {selectedIds.size} selected
          </span>
          <div className="flex gap-2">
            <button
              onClick={onClose}
              className="px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100 rounded-lg transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleAssign}
              disabled={assignMutation.isPending || selectedIds.size === 0}
              className="px-4 py-2 text-sm font-medium text-white bg-purple-600 hover:bg-purple-700 rounded-lg transition-colors disabled:opacity-50 flex items-center gap-2"
            >
              {assignMutation.isPending && (
                <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
              )}
              Assign ({selectedIds.size})
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
