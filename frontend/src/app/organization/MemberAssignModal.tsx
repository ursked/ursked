'use client';

import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { useToast } from '@/components/ui/Toast';
import { UserPicker } from '@/components/ui';
import { api } from '@/lib/api';

interface Props {
  nodeId: number;
  nodeName: string;
  existingMemberIds: number[];
  // primary: this becomes their unit (moving them out of any other).
  // secondary: they also belong here, keeping their own unit.
  mode?: 'primary' | 'secondary';
  onClose: () => void;
  onAssigned: () => void;
}

// Search-as-you-type instead of a list of the first 100 employees, so the
// 101st person in the company can be assigned too.
export default function MemberAssignModal({ nodeId, nodeName, existingMemberIds, mode = 'primary', onClose, onAssigned }: Props) {
  const { showToast } = useToast();
  const [selected, setSelected] = useState<number[]>([]);

  const assignMutation = useMutation({
    mutationFn: (userIds: number[]) =>
      mode === 'secondary'
        ? api.assignSecondaryMembers(nodeId, userIds)
        : api.assignOrgNodeMembers(nodeId, userIds),
    onSuccess: () => onAssigned(),
    onError: (error: Error) => showToast(error.message, 'error'),
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" role="dialog" aria-modal="true"
      aria-label={mode === 'secondary' ? 'Add secondary members' : 'Assign members'}>
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative bg-white rounded-xl shadow-2xl w-full max-w-lg mx-4 max-h-[85vh] flex flex-col">
        <div className="flex items-center justify-between px-6 py-4 border-b flex-shrink-0">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">
              {mode === 'secondary' ? 'Add secondary members' : 'Assign members'}
            </h2>
            <p className="text-sm text-gray-500 mt-0.5">to {nodeName}</p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600" aria-label="Close">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="flex-1 overflow-visible px-6 py-4 space-y-3 min-h-[16rem]">
          <p className="text-sm text-gray-600">
            {mode === 'secondary'
              ? 'Secondary members also belong to this unit (for schedules and visibility) and keep their own main unit.'
              : 'This becomes their main unit. Anyone whose main unit is elsewhere is moved here.'}
          </p>
          <UserPicker
            multiple
            label="Employees"
            value={selected}
            onChange={(ids) => setSelected(ids)}
            excludeIds={existingMemberIds}
          />
        </div>

        <div className="flex items-center justify-between px-6 py-4 border-t bg-gray-50 rounded-b-xl flex-shrink-0">
          <span className="text-sm text-gray-500">{selected.length} selected</span>
          <div className="flex gap-2">
            <button onClick={onClose} className="px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100 rounded-lg transition-colors">
              Cancel
            </button>
            <button
              onClick={() => (selected.length ? assignMutation.mutate(selected) : showToast('Choose at least one employee', 'error'))}
              disabled={assignMutation.isPending || selected.length === 0}
              className="px-4 py-2 text-sm font-medium text-white bg-purple-600 hover:bg-purple-700 rounded-lg transition-colors disabled:opacity-50"
            >
              {assignMutation.isPending ? 'Saving...' : mode === 'secondary' ? `Add (${selected.length})` : `Assign (${selected.length})`}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
