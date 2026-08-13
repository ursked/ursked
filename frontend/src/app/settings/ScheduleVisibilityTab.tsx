'use client'

import { useMemo, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { useToast } from '@/components/ui/Toast'
import type { OrgTreeNode, OrgTreeResponse, ScheduleVisibilityGrant, User } from '@/types'

type FlatNode = { id: number; label: string; depth: number }

function flatten(nodes: OrgTreeNode[], depth = 0, acc: FlatNode[] = []): FlatNode[] {
  for (const n of nodes) {
    acc.push({ id: n.id, label: n.name, depth })
    if (n.children?.length) flatten(n.children, depth + 1, acc)
  }
  return acc
}

export default function ScheduleVisibilityTab() {
  const queryClient = useQueryClient()
  const { showToast } = useToast()

  const [userId, setUserId] = useState<number | ''>('')
  const [nodeId, setNodeId] = useState<number | ''>('')
  const [includeDescendants, setIncludeDescendants] = useState(true)

  const { data: tree } = useQuery<OrgTreeResponse>({
    queryKey: ['org-tree'],
    queryFn: () => api.getOrgTree(),
    staleTime: 300_000,
  })

  const { data: usersPage } = useQuery({
    queryKey: ['users', 'for-visibility'],
    queryFn: () => api.getUsers({ limit: '500' }),
  })

  const { data: grants } = useQuery<ScheduleVisibilityGrant[]>({
    queryKey: ['schedule-visibility'],
    queryFn: () => api.getScheduleVisibilityGrants(),
  })

  const nodeOptions = useMemo(() => (tree ? flatten(tree.nodes) : []), [tree])
  const users: User[] = usersPage?.items ?? []

  const createMutation = useMutation({
    mutationFn: () =>
      api.createScheduleVisibilityGrant({
        user_id: Number(userId),
        org_node_id: Number(nodeId),
        include_descendants: includeDescendants,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['schedule-visibility'] })
      showToast('Access granted', 'success')
      setUserId('')
      setNodeId('')
      setIncludeDescendants(true)
    },
    onError: () => showToast('Failed to grant access', 'error'),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.deleteScheduleVisibilityGrant(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['schedule-visibility'] })
      showToast('Access removed', 'success')
    },
    onError: () => showToast('Failed to remove access', 'error'),
  })

  const canGrant = userId !== '' && nodeId !== '' && !createMutation.isPending

  const input =
    'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-transparent focus:ring-2 focus:ring-blue-500 outline-none'

  return (
    <div className="space-y-8">
      <div className="rounded-xl border border-gray-200 bg-white p-6">
        <h3 className="text-lg font-semibold text-gray-900">Schedule visibility</h3>
        <p className="mt-1 text-sm text-gray-500">
          Grant a person visibility into a specific part of the organization&apos;s schedule,
          beyond what their role or team already allows.
        </p>

        <div className="mt-6 grid grid-cols-1 gap-5 sm:grid-cols-2">
          <div>
            <label className="block text-sm font-medium text-gray-700">Person</label>
            <select
              className={`mt-1 ${input}`}
              value={userId}
              onChange={(e) => setUserId(e.target.value ? Number(e.target.value) : '')}
            >
              <option value="">Select a person…</option>
              {users.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.first_name} {u.last_name}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700">Org node</label>
            <select
              className={`mt-1 ${input}`}
              value={nodeId}
              onChange={(e) => setNodeId(e.target.value ? Number(e.target.value) : '')}
            >
              <option value="">Select a node…</option>
              {nodeOptions.map((n) => (
                <option key={n.id} value={n.id}>
                  {'\u00A0'.repeat(n.depth * 2)}
                  {n.label}
                </option>
              ))}
            </select>
          </div>
        </div>

        <label className="mt-5 flex items-center gap-2 text-sm text-gray-700">
          <input
            type="checkbox"
            checked={includeDescendants}
            onChange={(e) => setIncludeDescendants(e.target.checked)}
            className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
          />
          Include everything below this node (its whole subtree)
        </label>

        <div className="mt-6 border-t border-gray-100 pt-5">
          <button
            onClick={() => createMutation.mutate()}
            disabled={!canGrant}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {createMutation.isPending ? 'Granting…' : 'Grant access'}
          </button>
        </div>
      </div>

      <div className="rounded-xl border border-gray-200 bg-white p-6">
        <h3 className="text-lg font-semibold text-gray-900">Current grants</h3>
        <div className="mt-4 overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200 text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wide text-gray-500">
                <th className="py-2 pr-4">Person</th>
                <th className="py-2 pr-4">Node</th>
                <th className="py-2 pr-4">Scope</th>
                <th className="py-2 pr-4"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {(grants ?? []).length === 0 && (
                <tr>
                  <td colSpan={4} className="py-6 text-center text-gray-400">
                    No visibility grants yet.
                  </td>
                </tr>
              )}
              {(grants ?? []).map((g) => (
                <tr key={g.id}>
                  <td className="py-2 pr-4 text-gray-700">{g.user_name ?? `#${g.user_id}`}</td>
                  <td className="py-2 pr-4 text-gray-700">{g.org_node_name ?? `#${g.org_node_id}`}</td>
                  <td className="py-2 pr-4 text-gray-500">
                    {g.include_descendants ? 'Node + subtree' : 'Node only'}
                  </td>
                  <td className="py-2 pr-4 text-right">
                    <button
                      onClick={() => deleteMutation.mutate(g.id)}
                      disabled={deleteMutation.isPending}
                      className="text-sm font-medium text-red-600 hover:text-red-700 disabled:opacity-50"
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
