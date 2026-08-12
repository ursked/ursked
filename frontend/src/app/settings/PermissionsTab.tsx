'use client'

import { useState, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { PermissionMatrixEntry, PermissionModule } from '@/types'
import { useToast } from '@/components/ui/Toast'

const MODULES: { key: PermissionModule; label: string }[] = [
  { key: 'employees', label: 'Employees' },
  { key: 'organization', label: 'Organization' },
  { key: 'schedules', label: 'Schedules' },
  { key: 'leave', label: 'Leave' },
  { key: 'finances', label: 'Finances' },
  { key: 'settings', label: 'Settings' },
  { key: 'reports', label: 'Reports' },
]

const ACTIONS = [
  { key: 'can_view', label: 'V', title: 'View' },
  { key: 'can_create', label: 'C', title: 'Create' },
  { key: 'can_edit', label: 'E', title: 'Edit' },
  { key: 'can_delete', label: 'D', title: 'Delete' },
] as const

type ActionKey = (typeof ACTIONS)[number]['key']

interface LocalPermission {
  can_view: boolean
  can_create: boolean
  can_edit: boolean
  can_delete: boolean
  extra_permissions: Record<string, boolean>
}

type LocalMatrix = Record<number, { modules: Record<string, LocalPermission> }>

function buildLocalMatrix(entries: PermissionMatrixEntry[]): LocalMatrix {
  const matrix: LocalMatrix = {}
  for (const entry of entries) {
    const modules: Record<string, LocalPermission> = {}
    for (const mod of MODULES) {
      const perm = entry.modules[mod.key]
      modules[mod.key] = perm
        ? {
            can_view: perm.can_view,
            can_create: perm.can_create,
            can_edit: perm.can_edit,
            can_delete: perm.can_delete,
            extra_permissions: perm.extra_permissions ?? {},
          }
        : { can_view: false, can_create: false, can_edit: false, can_delete: false, extra_permissions: {} }
    }
    matrix[entry.role_id] = { modules }
  }
  return matrix
}

export default function PermissionsTab() {
  const queryClient = useQueryClient()
  const { showToast } = useToast()
  const [localMatrix, setLocalMatrix] = useState<LocalMatrix>({})
  const [dirty, setDirty] = useState<Set<number>>(new Set())

  const { data: matrixData, isLoading } = useQuery({
    queryKey: ['permission-matrix'],
    queryFn: () => api.getPermissionMatrix(),
    select: (data) => data.entries,
  })

  // Sync server data → local state when fresh
  const serverEntries = matrixData
  const isInitialized = Object.keys(localMatrix).length > 0

  if (serverEntries && !isInitialized) {
    // Initial population (only once)
    const m = buildLocalMatrix(serverEntries)
    setLocalMatrix(m)
  }

  const saveMutation = useMutation({
    mutationFn: async (roleId: number) => {
      const entry = localMatrix[roleId]
      if (!entry) return
      const permissions = MODULES.map((mod) => {
        const p = entry.modules[mod.key]
        return {
          module: mod.key,
          can_view: p.can_view,
          can_create: p.can_create,
          can_edit: p.can_edit,
          can_delete: p.can_delete,
          extra_permissions: p.extra_permissions,
        }
      })
      await api.updateRolePermissions(roleId, permissions)
    },
    onSuccess: (_data, roleId) => {
      queryClient.invalidateQueries({ queryKey: ['permission-matrix'] })
      setDirty((prev) => {
        const next = new Set(prev)
        next.delete(roleId)
        return next
      })
      showToast('Permissions updated', 'success')
    },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  const toggleAction = useCallback(
    (roleId: number, module: string, action: ActionKey) => {
      setLocalMatrix((prev) => {
        const entry = prev[roleId]
        if (!entry) return prev
        const current = entry.modules[module]
        return {
          ...prev,
          [roleId]: {
            ...entry,
            modules: {
              ...entry.modules,
              [module]: { ...current, [action]: !current[action] },
            },
          },
        }
      })
      setDirty((prev) => new Set(prev).add(roleId))
    },
    []
  )

  if (isLoading) {
    return (
      <div className="flex items-center gap-3 text-sm text-gray-500 py-12">
        <svg className="h-5 w-5 animate-spin text-purple-600" fill="none" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
        Loading permission matrix...
      </div>
    )
  }

  if (!serverEntries || serverEntries.length === 0) {
    return (
      <div className="text-center py-12">
        <h3 className="text-sm font-semibold text-gray-900">No roles found</h3>
        <p className="mt-1 text-sm text-gray-500">Permission matrix requires system roles to be seeded.</p>
      </div>
    )
  }

  return (
    <div className="space-y-8">
      <div className="bg-white shadow-sm ring-1 ring-gray-900/5 rounded-xl">
        <div className="border-b border-gray-200 px-6 py-4">
          <h2 className="text-lg font-semibold text-gray-900">Permission Matrix</h2>
          <p className="mt-1 text-sm text-gray-500">
            Configure module-level permissions for each role. Changes are saved per role.
          </p>
        </div>

        <div className="px-6 py-6">
          {/* Legend */}
          <div className="flex items-center gap-4 mb-4 text-xs text-gray-500">
            <span className="font-medium text-gray-700">Legend:</span>
            {ACTIONS.map((a) => (
              <span key={a.key}>
                <span className="font-semibold text-gray-700">{a.label}</span> = {a.title}
              </span>
            ))}
          </div>

          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead>
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500 w-40">
                    Role
                  </th>
                  {MODULES.map((mod) => (
                    <th
                      key={mod.key}
                      className="px-3 py-3 text-center text-xs font-semibold uppercase tracking-wider text-gray-500"
                    >
                      {mod.label}
                    </th>
                  ))}
                  <th className="px-3 py-3 text-center text-xs font-semibold uppercase tracking-wider text-gray-500 w-24">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {serverEntries.map((entry) => {
                  const isTenantAdmin = entry.role_code === 'tenant_admin'
                  const isRoleDirty = dirty.has(entry.role_id)
                  const local = localMatrix[entry.role_id]

                  return (
                    <tr key={entry.role_id} className="hover:bg-gray-50 transition-colors">
                      <td className="px-4 py-3">
                        <div className="text-sm font-medium text-gray-900">{entry.role_name}</div>
                        <div className="text-xs text-gray-500 font-mono">{entry.role_code}</div>
                      </td>
                      {MODULES.map((mod) => {
                        const perm = local?.modules[mod.key]
                        return (
                          <td key={mod.key} className="px-3 py-3">
                            <div className="flex items-center justify-center gap-1">
                              {ACTIONS.map((action) => {
                                const checked = isTenantAdmin ? true : perm?.[action.key] ?? false
                                return (
                                  <label
                                    key={action.key}
                                    className="relative flex items-center justify-center"
                                    title={`${action.title} ${mod.label}`}
                                  >
                                    <input
                                      type="checkbox"
                                      checked={checked}
                                      disabled={isTenantAdmin}
                                      onChange={() => toggleAction(entry.role_id, mod.key, action.key)}
                                      className="h-4 w-4 rounded border-gray-300 text-purple-600 focus:ring-purple-500 disabled:opacity-50 disabled:cursor-not-allowed"
                                    />
                                    <span className="sr-only">
                                      {action.title} {mod.label}
                                    </span>
                                  </label>
                                )
                              })}
                            </div>
                          </td>
                        )
                      })}
                      <td className="px-3 py-3 text-center">
                        {!isTenantAdmin && (
                          <button
                            type="button"
                            disabled={!isRoleDirty || saveMutation.isPending}
                            onClick={() => saveMutation.mutate(entry.role_id)}
                            className={`inline-flex items-center rounded-md px-3 py-1.5 text-xs font-semibold shadow-sm transition-colors ${
                              isRoleDirty
                                ? 'bg-purple-600 text-white hover:bg-purple-700'
                                : 'bg-gray-100 text-gray-400 cursor-not-allowed'
                            } disabled:opacity-50`}
                          >
                            {saveMutation.isPending ? 'Saving...' : 'Save'}
                          </button>
                        )}
                        {isTenantAdmin && (
                          <span className="text-xs text-gray-400 italic">Full access</span>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          <div className="mt-4 rounded-md bg-blue-50 p-3">
            <p className="text-xs text-blue-700">
              <span className="font-semibold">Note:</span> Tenant administrators always have full access to all
              modules and cannot be restricted. Permissions are merged across roles -- if a user has multiple roles,
              they receive the union of all granted permissions. Salary visibility is no longer set here — it is
              granted per user under <span className="font-semibold">Finances &rarr; Salary Access</span>.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
