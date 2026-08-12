'use client'

import { useState, useRef, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { LeaveApproverAssignment, ApproverRole, User, PaginatedResponse, OrgTreeNode } from '@/types'
import { useToast } from '@/components/ui/Toast'

type ScopeType = 'default' | 'employee' | 'org_node'
type ApproverType = 'user' | 'role'

interface AssignmentFormData {
  scope_type: ScopeType
  employee_id: number | null
  org_node_id: number | null
  approver_type: ApproverType
  approver_id: number | null
  approver_role: ApproverRole | null
  step_order: number
  cascade: boolean
  exclude: boolean
}

const EMPTY_FORM: AssignmentFormData = {
  scope_type: 'default',
  employee_id: null,
  org_node_id: null,
  approver_type: 'user',
  approver_id: null,
  approver_role: null,
  step_order: 1,
  cascade: false,
  exclude: false,
}

const APPROVER_ROLE_LABELS: Record<ApproverRole, string> = {
  node_head: 'Direct Manager',
  node_deputy: 'Alternate Manager',
  parent_head: 'Senior Manager',
  parent_deputy: 'Senior Alternate',
}

const APPROVER_ROLE_DESCRIPTIONS: Record<ApproverRole, string> = {
  node_head: 'The designated leader of the employee\'s own department or unit in the org chart.',
  node_deputy: 'The second-in-command of the employee\'s department or unit. Steps in when the Direct Manager is unavailable.',
  parent_head: 'The designated leader of the department one level above the employee\'s unit in the org chart.',
  parent_deputy: 'The second-in-command of the department one level above. Steps in when the Senior Manager is unavailable.',
}

interface FlatOrgNode {
  id: number
  name: string
  level_name: string
  depth: number
  parent_id: number | null
  head_user_name: string | null
  deputy_head_user_name: string | null
}

function flattenOrgNodes(nodes: OrgTreeNode[], depth = 0): FlatOrgNode[] {
  const result: FlatOrgNode[] = []
  const walk = (ns: OrgTreeNode[], d: number) => {
    for (const n of ns) {
      result.push({
        id: n.id,
        name: n.name,
        level_name: n.level_name,
        depth: d,
        parent_id: n.parent_id,
        head_user_name: n.head_user_name,
        deputy_head_user_name: n.deputy_head_user_name,
      })
      if (n.children) walk(n.children, d + 1)
    }
  }
  walk(nodes, depth)
  return result
}

/** Resolve a position-based role to the person currently holding it */
function resolvePositionHolder(
  role: ApproverRole,
  nodeId: number | null,
  flatNodes: FlatOrgNode[],
): { name: string | null; vacant: boolean } {
  if (!nodeId) return { name: null, vacant: false }

  const node = flatNodes.find((n) => n.id === nodeId)
  if (!node) return { name: null, vacant: false }

  if (role === 'node_head') {
    return { name: node.head_user_name, vacant: !node.head_user_name }
  }
  if (role === 'node_deputy') {
    return { name: node.deputy_head_user_name, vacant: !node.deputy_head_user_name }
  }
  if (role === 'parent_head' || role === 'parent_deputy') {
    if (!node.parent_id) return { name: null, vacant: false }
    const parent = flatNodes.find((n) => n.id === node.parent_id)
    if (!parent) return { name: null, vacant: false }
    const personName = role === 'parent_head' ? parent.head_user_name : parent.deputy_head_user_name
    return { name: personName, vacant: !personName }
  }
  return { name: null, vacant: false }
}

const SCOPE_OPTIONS: { value: ScopeType; label: string; description: string; icon: JSX.Element }[] = [
  {
    value: 'default',
    label: 'Default (All Employees)',
    description: 'Fallback rule for employees without a more specific match.',
    icon: (
      <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" d="M18 18.72a9.094 9.094 0 003.741-.479 3 3 0 00-4.682-2.72m.94 3.198l.001.031c0 .225-.012.447-.037.666A11.944 11.944 0 0112 21c-2.17 0-4.207-.576-5.963-1.584A6.062 6.062 0 016 18.719m12 0a5.971 5.971 0 00-.941-3.197m0 0A5.995 5.995 0 0012 12.75a5.995 5.995 0 00-5.058 2.772m0 0a3 3 0 00-4.681 2.72 8.986 8.986 0 003.74.477m.94-3.197a5.971 5.971 0 00-.94 3.197M15 6.75a3 3 0 11-6 0 3 3 0 016 0zm6 3a2.25 2.25 0 11-4.5 0 2.25 2.25 0 014.5 0zm-13.5 0a2.25 2.25 0 11-4.5 0 2.25 2.25 0 014.5 0z" />
      </svg>
    ),
  },
  {
    value: 'employee',
    label: 'Specific Employee',
    description: 'Target a single employee. Can also exclude them from other rules.',
    icon: (
      <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z" />
      </svg>
    ),
  },
  {
    value: 'org_node',
    label: 'Organization Node',
    description: 'Target employees in a department, section, or unit.',
    icon: (
      <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 21h19.5m-18-18v18m10.5-18v18m6-13.5V21M6.75 6.75h.75m-.75 3h.75m-.75 3h.75m3-6h.75m-.75 3h.75m-.75 3h.75M6.75 21v-3.375c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125V21M3 3h12m-.75 4.5H21m-3.75 3.75h.008v.008h-.008v-.008zm0 3h.008v.008h-.008v-.008zm0 3h.008v.008h-.008v-.008z" />
      </svg>
    ),
  },
]

/** Build a human-readable description for a rule */
function describeRule(a: LeaveApproverAssignment): { text: string; detail?: string } {
  const approver = a.approver_role
    ? APPROVER_ROLE_LABELS[a.approver_role]
    : (a.approver_name || 'Unknown')
  const step = a.step_order > 1 ? ` (Step ${a.step_order} in the approval chain)` : ''
  const roleDetail = a.approver_role
    ? 'Assigned by position — automatically updates when the person in this role changes.'
    : undefined

  if (a.employee_id) {
    const employee = a.employee_name ?? `Employee #${a.employee_id}`
    if (a.exclude) {
      return {
        text: `${employee} is excluded from approval rules`,
        detail: `No other approval rules apply to ${employee}'s leave requests. Their leave bypasses manual approval.`,
      }
    }
    return {
      text: `If ${employee} files a leave, ${approver} is the approver${step}`,
      detail: roleDetail,
    }
  }

  if (a.org_node_id) {
    const node = a.org_node_name ?? `Node #${a.org_node_id}`
    if (a.cascade) {
      return {
        text: `Leave requests from ${node} and all sub-levels are approved by ${approver}${step}`,
        detail: roleDetail,
      }
    }
    return {
      text: `Leave requests from ${node} are approved by ${approver}${step}`,
      detail: roleDetail,
    }
  }

  // Default (all employees)
  return {
    text: `All employees' leave can be approved by ${approver}${step}`,
    detail: roleDetail,
  }
}

export default function ApprovalRulesTab() {
  const queryClient = useQueryClient()
  const { showToast } = useToast()

  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [form, setForm] = useState<AssignmentFormData>(EMPTY_FORM)
  const [deleteConfirmId, setDeleteConfirmId] = useState<number | null>(null)
  const [showStepHelp, setShowStepHelp] = useState(false)
  const [showHowItWorks, setShowHowItWorks] = useState(false)

  // Drag state
  const [dragIndex, setDragIndex] = useState<number | null>(null)
  const [dragOverIndex, setDragOverIndex] = useState<number | null>(null)
  const dragNodeRef = useRef<HTMLDivElement | null>(null)

  // ── Queries ────────────────────────────────────────────────────────
  const { data: assignments, isLoading } = useQuery<LeaveApproverAssignment[]>({
    queryKey: ['approver-assignments'],
    queryFn: () => api.getApproverAssignments(),
  })

  const { data: users } = useQuery<PaginatedResponse<User>>({
    queryKey: ['users-all'],
    queryFn: () => api.getUsers({ per_page: '100', is_active: 'true' }),
  })

  const { data: orgTree } = useQuery({
    queryKey: ['org-tree'],
    queryFn: () => api.getOrgTree(),
  })

  const flatNodes = orgTree ? flattenOrgNodes(orgTree.nodes) : []
  const allUsers = users?.items ?? []

  // ── Mutations ──────────────────────────────────────────────────────
  const createMutation = useMutation({
    mutationFn: (data: Record<string, unknown>) => api.createApproverAssignment(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['approver-assignments'] })
      resetForm()
      showToast('Approver rule created', 'success')
    },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Record<string, unknown> }) => api.updateApproverAssignment(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['approver-assignments'] })
      resetForm()
      showToast('Approver rule updated', 'success')
    },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.deleteApproverAssignment(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['approver-assignments'] })
      setDeleteConfirmId(null)
      showToast('Approver rule deleted', 'success')
    },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  const reorderMutation = useMutation({
    mutationFn: (orderedIds: number[]) => api.reorderApproverAssignments(orderedIds),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['approver-assignments'] })
      showToast('Rule order updated', 'success')
    },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  // ── Form helpers ───────────────────────────────────────────────────
  const resetForm = () => {
    setShowForm(false)
    setEditingId(null)
    setForm(EMPTY_FORM)
    setShowStepHelp(false)
  }

  const handleEdit = (a: LeaveApproverAssignment) => {
    let scopeType: ScopeType = 'default'
    if (a.employee_id) scopeType = 'employee'
    else if (a.org_node_id) scopeType = 'org_node'

    setEditingId(a.id)
    setShowForm(false)
    setForm({
      scope_type: scopeType,
      employee_id: a.employee_id ?? null,
      org_node_id: a.org_node_id ?? null,
      approver_type: a.approver_role ? 'role' : 'user',
      approver_id: a.approver_id ?? null,
      approver_role: a.approver_role ?? null,
      step_order: a.step_order,
      cascade: a.cascade ?? false,
      exclude: a.exclude ?? false,
    })
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const payload: Record<string, unknown> = {
      step_order: form.step_order,
      // New rules go to the bottom — assign a high priority; reorder will fix it
      priority: assignments ? (assignments.length + 1) * 10 : 10,
    }

    // Approver: either specific user or position-based role
    if (form.approver_type === 'role' && form.approver_role) {
      payload.approver_role = form.approver_role
      payload.approver_id = null
    } else {
      payload.approver_id = form.approver_id
      payload.approver_role = null
    }

    if (form.scope_type === 'employee' && form.employee_id) {
      payload.employee_id = form.employee_id
      payload.exclude = form.exclude
    }
    if (form.scope_type === 'org_node' && form.org_node_id) {
      payload.org_node_id = form.org_node_id
      payload.cascade = form.cascade
    }

    if (editingId !== null) {
      updateMutation.mutate({ id: editingId, data: payload })
    } else {
      createMutation.mutate(payload)
    }
  }

  const isMutating = createMutation.isPending || updateMutation.isPending || deleteMutation.isPending

  // Rules come sorted by priority from the API
  const sortedAssignments = assignments ?? []

  // ── Drag and drop handlers ─────────────────────────────────────────
  const handleDragStart = useCallback((e: React.DragEvent<HTMLDivElement>, index: number) => {
    setDragIndex(index)
    dragNodeRef.current = e.currentTarget
    e.dataTransfer.effectAllowed = 'move'
    e.dataTransfer.setData('text/plain', String(index))
    // Slight delay for visual feedback
    requestAnimationFrame(() => {
      if (dragNodeRef.current) {
        dragNodeRef.current.style.opacity = '0.4'
      }
    })
  }, [])

  const handleDragOver = useCallback((e: React.DragEvent<HTMLDivElement>, index: number) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
    setDragOverIndex(index)
  }, [])

  const handleDragEnd = useCallback(() => {
    if (dragNodeRef.current) {
      dragNodeRef.current.style.opacity = '1'
    }
    setDragIndex(null)
    setDragOverIndex(null)
    dragNodeRef.current = null
  }, [])

  const handleDrop = useCallback((e: React.DragEvent<HTMLDivElement>, dropIndex: number) => {
    e.preventDefault()
    const fromIndex = dragIndex
    if (fromIndex === null || fromIndex === dropIndex) {
      handleDragEnd()
      return
    }

    // Reorder the list
    const newList = [...sortedAssignments]
    const [moved] = newList.splice(fromIndex, 1)
    newList.splice(dropIndex, 0, moved)

    // Send the new order to the backend
    const orderedIds = newList.map((a) => a.id)
    reorderMutation.mutate(orderedIds)

    handleDragEnd()
  }, [dragIndex, sortedAssignments, reorderMutation, handleDragEnd])

  // ── Scope badge for the rule card ──────────────────────────────────
  const scopeBadge = (a: LeaveApproverAssignment) => {
    if (a.employee_id) {
      return (
        <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-medium text-amber-700">
          <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z" />
          </svg>
          Employee
        </span>
      )
    }
    if (a.org_node_id) {
      return (
        <span className="inline-flex items-center gap-1 rounded-full bg-blue-100 px-2 py-0.5 text-[11px] font-medium text-blue-700">
          <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 21h19.5m-18-18v18m10.5-18v18m6-13.5V21M6.75 6.75h.75m-.75 3h.75m-.75 3h.75m3-6h.75m-.75 3h.75m-.75 3h.75M6.75 21v-3.375c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125V21M3 3h12m-.75 4.5H21m-3.75 3.75h.008v.008h-.008v-.008zm0 3h.008v.008h-.008v-.008zm0 3h.008v.008h-.008v-.008z" />
          </svg>
          Org Node{a.cascade ? ' (Cascade)' : ''}
        </span>
      )
    }
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-600">
        <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" d="M18 18.72a9.094 9.094 0 003.741-.479 3 3 0 00-4.682-2.72m.94 3.198l.001.031c0 .225-.012.447-.037.666A11.944 11.944 0 0112 21c-2.17 0-4.207-.576-5.963-1.584A6.062 6.062 0 016 18.719m12 0a5.971 5.971 0 00-.941-3.197m0 0A5.995 5.995 0 0012 12.75a5.995 5.995 0 00-5.058 2.772m0 0a3 3 0 00-4.681 2.72 8.986 8.986 0 003.74.477m.94-3.197a5.971 5.971 0 00-.94 3.197M15 6.75a3 3 0 11-6 0 3 3 0 016 0zm6 3a2.25 2.25 0 11-4.5 0 2.25 2.25 0 014.5 0zm-13.5 0a2.25 2.25 0 11-4.5 0 2.25 2.25 0 014.5 0z" />
        </svg>
        Default
      </span>
    )
  }

  return (
    <div className="space-y-6">
      <div className="bg-white shadow-sm ring-1 ring-gray-900/5 rounded-xl">
        <div className="border-b border-gray-200 px-6 py-4 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Approval Rules</h2>
            <p className="mt-1 text-sm text-gray-500">
              Define who approves leave requests. Drag rules to reorder &mdash; rules are evaluated top to bottom, first match wins.
            </p>
          </div>
          {!showForm && editingId === null && (
            <button
              type="button"
              onClick={() => { setShowForm(true); setEditingId(null); setForm(EMPTY_FORM) }}
              className="inline-flex items-center gap-1.5 rounded-md bg-purple-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-purple-700 transition-colors"
            >
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
              </svg>
              Add Rule
            </button>
          )}
        </div>

        <div className="px-6 py-6 space-y-6">
          {/* ── Form ──────────────────────────────────────────────── */}
          {(showForm || editingId !== null) && (
            <form onSubmit={handleSubmit} className="bg-gray-50 border border-gray-200 rounded-lg p-6 space-y-5">
              <h4 className="text-sm font-semibold text-gray-900">{editingId ? 'Edit Rule' : 'New Approver Rule'}</h4>

              {/* Scope type — card selection */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-3">Who does this rule apply to?</label>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                  {SCOPE_OPTIONS.map((opt) => (
                    <button
                      key={opt.value}
                      type="button"
                      onClick={() => setForm((p) => ({ ...p, scope_type: opt.value, employee_id: null, org_node_id: null, cascade: false, exclude: false }))}
                      className={`text-left p-3 rounded-lg border-2 transition-all ${
                        form.scope_type === opt.value
                          ? 'border-purple-500 bg-purple-50 ring-1 ring-purple-500'
                          : 'border-gray-200 bg-white hover:border-gray-300'
                      }`}
                    >
                      <div className="flex items-center gap-2 mb-1">
                        <span className={form.scope_type === opt.value ? 'text-purple-600' : 'text-gray-400'}>{opt.icon}</span>
                        <span className={`text-sm font-medium ${form.scope_type === opt.value ? 'text-purple-900' : 'text-gray-700'}`}>
                          {opt.label}
                        </span>
                      </div>
                      <p className="text-xs text-gray-500 ml-7">{opt.description}</p>
                    </button>
                  ))}
                </div>
              </div>

              {/* Scope-specific fields */}
              {form.scope_type === 'employee' && (
                <div className="space-y-3">
                  <div className="max-w-md">
                    <label className="block text-sm font-medium text-gray-700 mb-1">Select Employee</label>
                    <select
                      required
                      value={form.employee_id ?? ''}
                      onChange={(e) => setForm((p) => ({ ...p, employee_id: parseInt(e.target.value, 10) || null }))}
                      className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none"
                    >
                      <option value="">Select employee...</option>
                      {allUsers.map((u) => (
                        <option key={u.id} value={u.id}>{u.first_name} {u.last_name}</option>
                      ))}
                    </select>
                  </div>

                  {/* Exclude checkbox */}
                  <div className={`border rounded-lg p-4 max-w-lg ${form.exclude ? 'bg-red-50 border-red-200' : 'bg-white border-gray-200'}`}>
                    <label className="flex items-start gap-3 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={form.exclude}
                        onChange={(e) => setForm((p) => ({ ...p, exclude: e.target.checked }))}
                        className="mt-0.5 h-4 w-4 rounded border-gray-300 text-red-600 focus:ring-red-500"
                      />
                      <div>
                        <span className={`text-sm font-medium ${form.exclude ? 'text-red-900' : 'text-gray-900'}`}>
                          Exclude from approval rules
                        </span>
                        <p className={`text-xs mt-0.5 ${form.exclude ? 'text-red-600' : 'text-gray-500'}`}>
                          {form.exclude
                            ? 'This employee will be EXCLUDED from all other approval rules. Their leave will bypass manual approval entirely (auto-approved or org-hierarchy fallback).'
                            : 'Check this to exclude this employee from broader org-node or default rules. Useful for executives who don\'t need approval.'}
                        </p>
                      </div>
                    </label>
                  </div>
                </div>
              )}

              {form.scope_type === 'org_node' && (
                <div className="space-y-3">
                  <div className="max-w-md">
                    <label className="block text-sm font-medium text-gray-700 mb-1">Select Organization Node</label>
                    <select
                      required
                      value={form.org_node_id ?? ''}
                      onChange={(e) => setForm((p) => ({ ...p, org_node_id: parseInt(e.target.value, 10) || null }))}
                      className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none"
                    >
                      <option value="">Select org node...</option>
                      {flatNodes.map((n) => (
                        <option key={n.id} value={n.id}>
                          {'\u00A0'.repeat(n.depth * 3)}{n.depth > 0 ? '\u2514\u2500 ' : ''}{n.level_name}: {n.name}
                        </option>
                      ))}
                    </select>
                  </div>

                  {/* Cascade checkbox */}
                  <div className="bg-white border border-gray-200 rounded-lg p-4 max-w-lg">
                    <label className="flex items-start gap-3 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={form.cascade}
                        onChange={(e) => setForm((p) => ({ ...p, cascade: e.target.checked }))}
                        className="mt-0.5 h-4 w-4 rounded border-gray-300 text-purple-600 focus:ring-purple-500"
                      />
                      <div>
                        <span className="text-sm font-medium text-gray-900">Include sub-levels (cascade)</span>
                        <p className="text-xs text-gray-500 mt-0.5">
                          {form.cascade
                            ? 'This approver will handle leave requests from employees in the selected node AND all nodes below it in the hierarchy.'
                            : 'Only employees directly assigned to the selected node will have their leave routed to this approver. Sub-levels are excluded.'}
                        </p>
                      </div>
                    </label>
                  </div>
                </div>
              )}

              {/* Approver + Step order (no priority field — auto-managed) */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 max-w-2xl">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">Approver</label>

                  {/* Toggle: Specific User vs Position-Based */}
                  {!form.exclude && (
                    <div className="flex rounded-md border border-gray-200 mb-2 overflow-hidden">
                      <button
                        type="button"
                        onClick={() => setForm((p) => ({ ...p, approver_type: 'user', approver_role: null }))}
                        className={`flex-1 py-1.5 text-xs font-medium transition-colors ${
                          form.approver_type === 'user'
                            ? 'bg-purple-600 text-white'
                            : 'bg-white text-gray-600 hover:bg-gray-50'
                        }`}
                      >
                        Specific User
                      </button>
                      <button
                        type="button"
                        onClick={() => setForm((p) => ({ ...p, approver_type: 'role', approver_id: null }))}
                        className={`flex-1 py-1.5 text-xs font-medium transition-colors ${
                          form.approver_type === 'role'
                            ? 'bg-purple-600 text-white'
                            : 'bg-white text-gray-600 hover:bg-gray-50'
                        }`}
                      >
                        Position-Based
                      </button>
                    </div>
                  )}

                  {form.approver_type === 'user' || form.exclude ? (
                    <>
                      <select
                        required={!form.exclude}
                        disabled={form.exclude}
                        value={form.approver_id ?? ''}
                        onChange={(e) => setForm((p) => ({ ...p, approver_id: parseInt(e.target.value, 10) || null }))}
                        className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none disabled:bg-gray-100 disabled:text-gray-400"
                      >
                        <option value="">{form.exclude ? 'N/A (excluded)' : 'Select approver...'}</option>
                        {allUsers.map((u) => (
                          <option key={u.id} value={u.id}>{u.first_name} {u.last_name}</option>
                        ))}
                      </select>
                      <p className="mt-1 text-xs text-gray-400">
                        {form.exclude ? 'No approver needed for exclude rules.' : 'The person who will approve or reject leave requests.'}
                      </p>
                    </>
                  ) : (
                    <>
                      <div className="flex items-center gap-1.5">
                        <select
                          required
                          value={form.approver_role ?? ''}
                          onChange={(e) => setForm((p) => ({ ...p, approver_role: (e.target.value || null) as ApproverRole | null }))}
                          className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none"
                        >
                          <option value="">Select position...</option>
                          {(Object.keys(APPROVER_ROLE_LABELS) as ApproverRole[]).map((role) => (
                            <option key={role} value={role}>{APPROVER_ROLE_LABELS[role]}</option>
                          ))}
                        </select>
                        {form.approver_role && (
                          <div className="relative group/tip flex-shrink-0">
                            <svg className="h-4 w-4 text-gray-400 hover:text-purple-600 cursor-help transition-colors" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                              <path strokeLinecap="round" strokeLinejoin="round" d="M11.25 11.25l.041-.02a.75.75 0 011.063.852l-.708 2.836a.75.75 0 001.063.853l.041-.021M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9-3.75h.008v.008H12V8.25z" />
                            </svg>
                            <div className="absolute bottom-full right-0 mb-2 w-64 p-2.5 bg-gray-900 text-white text-xs rounded-lg opacity-0 invisible group-hover/tip:opacity-100 group-hover/tip:visible transition-all z-50 pointer-events-none shadow-lg">
                              {APPROVER_ROLE_DESCRIPTIONS[form.approver_role]}
                              <div className="absolute top-full right-2 border-4 border-transparent border-t-gray-900" />
                            </div>
                          </div>
                        )}
                      </div>
                      <p className="mt-1 text-xs text-gray-400">
                        Approver is determined by org position. Automatically updates when the person in this role changes.
                      </p>
                    </>
                  )}
                </div>

                <div>
                  <div className="flex items-center gap-1.5 mb-1">
                    <label className="block text-sm font-medium text-gray-700">Step Order</label>
                    <button
                      type="button"
                      onClick={() => setShowStepHelp(!showStepHelp)}
                      className="text-gray-400 hover:text-purple-600 transition-colors"
                      title="What is step order?"
                    >
                      <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" d="M9.879 7.519c1.171-1.025 3.071-1.025 4.242 0 1.172 1.025 1.172 2.687 0 3.712-.203.179-.43.326-.67.442-.745.361-1.45.999-1.45 1.827m0 0v.75m0-3.375c0-.621.504-1.125 1.125-1.125h.008v.008h-.008c-.621 0-1.125.504-1.125 1.125zm0 3.375h.007v.008H12v-.008z" />
                      </svg>
                    </button>
                  </div>
                  <input
                    type="number"
                    min="1"
                    required
                    disabled={form.exclude}
                    value={form.step_order}
                    onChange={(e) => setForm((p) => ({ ...p, step_order: parseInt(e.target.value, 10) || 1 }))}
                    className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none disabled:bg-gray-100 disabled:text-gray-400"
                  />
                  {showStepHelp ? (
                    <div className="mt-2 bg-purple-50 border border-purple-200 rounded-md p-3">
                      <p className="text-xs text-purple-800 font-medium mb-1">How Step Order Works</p>
                      <p className="text-xs text-purple-700">
                        Step order defines a sequential approval chain:
                      </p>
                      <ul className="text-xs text-purple-700 mt-1 ml-3 list-disc space-y-0.5">
                        <li><strong>Step 1</strong> approver is notified first</li>
                        <li>Once Step 1 approves, <strong>Step 2</strong> is notified</li>
                        <li>If any step rejects, the request is denied immediately</li>
                        <li>The request is approved only when all steps approve</li>
                      </ul>
                      <p className="text-xs text-purple-600 mt-1.5 italic">
                        Use step 1 for single-level approval. Add steps 2, 3, etc. for multi-level chains.
                      </p>
                    </div>
                  ) : (
                    <p className="mt-1 text-xs text-gray-400">
                      {form.exclude ? 'N/A for exclude rules.' : 'Position in approval chain (1 = first).'}
                    </p>
                  )}
                </div>
              </div>

              {/* Preview of what the rule will look like */}
              {(form.scope_type !== 'employee' || form.employee_id) && (() => {
                const approverLabel = form.approver_type === 'role' && form.approver_role
                  ? APPROVER_ROLE_LABELS[form.approver_role]
                  : form.approver_id
                    ? `${allUsers.find(u => u.id === form.approver_id)?.first_name ?? ''} ${allUsers.find(u => u.id === form.approver_id)?.last_name ?? ''}`
                    : ''
                const hasApprover = form.exclude || approverLabel
                const stepLabel = form.step_order > 1 ? ` (Step ${form.step_order})` : ''

                // Resolve the actual person for position-based roles
                const isRoleBased = form.approver_type === 'role' && form.approver_role
                let resolvedName: string | null = null
                let resolvedVacant = false
                let resolvedNodeName: string | null = null
                if (isRoleBased) {
                  const refNodeId = form.scope_type === 'org_node' ? form.org_node_id : null
                  if (refNodeId) {
                    const resolved = resolvePositionHolder(form.approver_role!, refNodeId, flatNodes)
                    resolvedName = resolved.name
                    resolvedVacant = resolved.vacant
                    // Show which node was resolved against
                    const refNode = flatNodes.find(n => n.id === refNodeId)
                    resolvedNodeName = refNode?.name ?? null
                  }
                }

                return (
                  <div className="bg-purple-50 border border-purple-200 rounded-md p-3 max-w-2xl">
                    <p className="text-xs font-medium text-purple-800 mb-1">Rule preview</p>
                    <p className="text-sm text-purple-900">
                      {form.exclude && form.scope_type === 'employee' && form.employee_id
                        ? `${allUsers.find(u => u.id === form.employee_id)?.first_name ?? ''} ${allUsers.find(u => u.id === form.employee_id)?.last_name ?? ''} is excluded from approval rules`
                        : form.scope_type === 'employee' && form.employee_id && hasApprover
                          ? `If ${allUsers.find(u => u.id === form.employee_id)?.first_name ?? ''} ${allUsers.find(u => u.id === form.employee_id)?.last_name ?? ''} files a leave, ${approverLabel} is the approver${stepLabel}`
                          : form.scope_type === 'org_node' && form.org_node_id && hasApprover
                            ? `Leave requests from ${flatNodes.find(n => n.id === form.org_node_id)?.name ?? 'selected node'}${form.cascade ? ' and all sub-levels' : ''} are approved by ${approverLabel}${stepLabel}`
                            : form.scope_type === 'default' && hasApprover
                              ? `All employees' leave can be approved by ${approverLabel}${stepLabel}`
                              : 'Complete the form to see a preview...'}
                    </p>
                    {isRoleBased && resolvedName && (
                      <p className="text-xs text-purple-700 mt-1.5 flex items-center gap-1.5">
                        <svg className="h-3.5 w-3.5 text-green-600 flex-shrink-0" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z" />
                        </svg>
                        Currently: <strong>{resolvedName}</strong>
                        {resolvedNodeName && <span className="text-purple-500">({resolvedNodeName})</span>}
                      </p>
                    )}
                    {isRoleBased && resolvedVacant && (
                      <p className="text-xs text-amber-600 mt-1.5 flex items-center gap-1.5">
                        <svg className="h-3.5 w-3.5 flex-shrink-0" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
                        </svg>
                        Position currently vacant — this step will be skipped until someone is assigned.
                      </p>
                    )}
                    {isRoleBased && !resolvedName && !resolvedVacant && (
                      <p className="text-xs text-purple-600 mt-1 italic">
                        Resolves to the person in this position based on the employee&apos;s department.
                      </p>
                    )}
                  </div>
                )
              })()}

              <div className="flex items-center gap-3 pt-2">
                <button
                  type="submit"
                  disabled={isMutating || (!form.exclude && form.approver_type === 'user' && !form.approver_id) || (!form.exclude && form.approver_type === 'role' && !form.approver_role)}
                  className="inline-flex items-center rounded-md bg-purple-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  {isMutating ? 'Saving...' : editingId ? 'Update Rule' : 'Create Rule'}
                </button>
                <button
                  type="button"
                  onClick={resetForm}
                  className="inline-flex items-center rounded-md bg-white px-4 py-2 text-sm font-semibold text-gray-700 shadow-sm ring-1 ring-inset ring-gray-300 hover:bg-gray-50 transition-colors"
                >
                  Cancel
                </button>
              </div>
            </form>
          )}

          {/* ── How It Works info (always shown, collapsible) ─────── */}
          {!showForm && editingId === null && (
            <div className="rounded-lg border border-blue-200 bg-blue-50 overflow-hidden">
              <button
                type="button"
                onClick={() => setShowHowItWorks(!showHowItWorks)}
                className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-blue-100/50 transition-colors"
              >
                <div className="flex items-center gap-2">
                  <svg className="h-4 w-4 text-blue-600" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M11.25 11.25l.041-.02a.75.75 0 011.063.852l-.708 2.836a.75.75 0 001.063.853l.041-.021M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9-3.75h.008v.008H12V8.25z" />
                  </svg>
                  <span className="text-sm font-semibold text-blue-800">How Approval Rules Work</span>
                </div>
                <svg className={`h-4 w-4 text-blue-600 transition-transform ${showHowItWorks ? 'rotate-180' : ''}`} fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
                </svg>
              </button>
              {showHowItWorks && (
                <div className="px-4 pb-4">
                  <p className="text-xs text-blue-700">
                    Approval rules are evaluated from top to bottom. The first rule that matches an employee&apos;s situation is used.
                  </p>
                  <ul className="text-xs text-blue-700 mt-1.5 ml-4 list-disc space-y-0.5">
                    <li>Rules at the <strong>top</strong> of the list have the highest priority</li>
                    <li><strong>Exclude</strong> rules skip manual approval for a specific employee (e.g., CEO)</li>
                    <li><strong>Cascade</strong> on org-node rules extends the match to all sub-levels</li>
                    <li><strong>Position-based</strong> roles automatically update when the person in that role changes</li>
                    <li>Drag and drop rules to change their order</li>
                  </ul>
                  {assignments && assignments.length === 0 && (
                    <p className="text-xs text-blue-600 mt-1.5">
                      Click &quot;Add Rule&quot; to create your first approval rule.
                    </p>
                  )}
                </div>
              )}
            </div>
          )}

          {/* ── Rules List (draggable cards) ───────────────────────── */}
          {isLoading ? (
            <div className="flex items-center gap-3 text-sm text-gray-500">
              <svg className="h-5 w-5 animate-spin text-purple-600" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              Loading...
            </div>
          ) : sortedAssignments.length > 0 ? (
            <div className="space-y-2">
              {/* Top-to-bottom hint */}
              <div className="flex items-center gap-2 text-xs text-gray-500 mb-3">
                <svg className="h-4 w-4 shrink-0 text-purple-500" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M3 4.5h14.25M3 9h9.75M3 13.5h5.25m5.25 0H21m-6.75 0l-3 3m0 0l3 3m-3-3h12" />
                </svg>
                <span>Rules are evaluated <strong>top to bottom</strong>. The first matching rule wins. Drag to reorder.</span>
              </div>

              {sortedAssignments.map((a, index) => {
                const { text, detail } = describeRule(a)
                const isExclude = a.exclude
                const isDragging = dragIndex === index
                const isDragOver = dragOverIndex === index && dragIndex !== index

                // Resolve position holder for role-based rules
                const cardResolved = a.approver_role && a.org_node_id
                  ? resolvePositionHolder(a.approver_role, a.org_node_id, flatNodes)
                  : null

                return (
                  <div
                    key={a.id}
                    draggable
                    onDragStart={(e) => handleDragStart(e, index)}
                    onDragOver={(e) => handleDragOver(e, index)}
                    onDragEnd={handleDragEnd}
                    onDrop={(e) => handleDrop(e, index)}
                    className={`
                      group relative flex items-start gap-3 rounded-lg border p-4 transition-all cursor-grab active:cursor-grabbing
                      ${isExclude
                        ? 'bg-red-50/60 border-red-200 hover:border-red-300'
                        : 'bg-white border-gray-200 hover:border-gray-300 hover:shadow-sm'}
                      ${isDragging ? 'opacity-40 scale-[0.98]' : ''}
                      ${isDragOver ? 'border-purple-400 bg-purple-50/30 shadow-md ring-2 ring-purple-200' : ''}
                    `}
                  >
                    {/* Drag handle */}
                    <div className="flex-shrink-0 mt-0.5 text-gray-300 group-hover:text-gray-400 transition-colors">
                      <svg className="h-5 w-5" fill="currentColor" viewBox="0 0 20 20">
                        <path d="M7 2a2 2 0 1 0 0 4 2 2 0 0 0 0-4zM7 8a2 2 0 1 0 0 4 2 2 0 0 0 0-4zM7 14a2 2 0 1 0 0 4 2 2 0 0 0 0-4zM13 2a2 2 0 1 0 0 4 2 2 0 0 0 0-4zM13 8a2 2 0 1 0 0 4 2 2 0 0 0 0-4zM13 14a2 2 0 1 0 0 4 2 2 0 0 0 0-4z" />
                      </svg>
                    </div>

                    {/* Rule content */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap mb-1">
                        {scopeBadge(a)}
                        {isExclude && (
                          <span className="inline-flex items-center gap-1 rounded-full bg-red-100 px-2 py-0.5 text-[11px] font-semibold text-red-700">
                            <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                              <path strokeLinecap="round" strokeLinejoin="round" d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636" />
                            </svg>
                            Excluded
                          </span>
                        )}
                        {a.approver_role && (
                          <span className="inline-flex items-center gap-1 rounded-full bg-green-100 px-2 py-0.5 text-[11px] font-medium text-green-700">
                            <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                              <path strokeLinecap="round" strokeLinejoin="round" d="M20.25 14.15v4.25c0 1.094-.787 2.036-1.872 2.18-2.087.277-4.216.42-6.378.42s-4.291-.143-6.378-.42c-1.085-.144-1.872-1.086-1.872-2.18v-4.25m16.5 0a2.18 2.18 0 00.75-1.661V8.706c0-1.081-.768-2.015-1.837-2.175a48.114 48.114 0 00-3.413-.387m4.5 8.006c-.194.165-.42.295-.673.38A23.978 23.978 0 0112 15.75c-2.648 0-5.195-.429-7.577-1.22a2.016 2.016 0 01-.673-.38m0 0A2.18 2.18 0 013 12.489V8.706c0-1.081.768-2.015 1.837-2.175a48.111 48.111 0 013.413-.387m7.5 0V5.25A2.25 2.25 0 0013.5 3h-3a2.25 2.25 0 00-2.25 2.25v.894m7.5 0a48.667 48.667 0 00-7.5 0M12 12.75h.008v.008H12v-.008z" />
                            </svg>
                            Position
                          </span>
                        )}
                        {!isExclude && a.step_order > 1 && (
                          <span className="inline-flex items-center rounded-full bg-purple-100 px-2 py-0.5 text-[11px] font-medium text-purple-700">
                            Step {a.step_order}
                          </span>
                        )}
                        {!a.is_active && (
                          <span className="inline-flex items-center rounded-full bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-500">
                            Inactive
                          </span>
                        )}
                      </div>
                      <p className={`text-sm leading-relaxed ${isExclude ? 'text-red-800' : 'text-gray-900'}`}>
                        {text}
                      </p>
                      {cardResolved?.name && (
                        <p className="text-xs text-gray-600 mt-1 flex items-center gap-1">
                          <svg className="h-3 w-3 text-green-500 flex-shrink-0" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z" />
                          </svg>
                          Currently: <strong>{cardResolved.name}</strong>
                        </p>
                      )}
                      {cardResolved?.vacant && (
                        <p className="text-xs text-amber-600 mt-1 flex items-center gap-1">
                          <svg className="h-3 w-3 flex-shrink-0" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
                          </svg>
                          Position vacant — step will be skipped
                        </p>
                      )}
                      {detail && !cardResolved && (
                        <p className="text-xs text-gray-500 mt-1">{detail}</p>
                      )}
                    </div>

                    {/* Actions */}
                    <div className="flex-shrink-0 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                      <button
                        type="button"
                        onClick={(e) => { e.stopPropagation(); handleEdit(a) }}
                        className="inline-flex items-center rounded-md p-1.5 text-gray-400 hover:text-purple-600 hover:bg-purple-50 transition-colors"
                        title="Edit rule"
                      >
                        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125M18 14v4.75A2.25 2.25 0 0115.75 21H5.25A2.25 2.25 0 013 18.75V8.25A2.25 2.25 0 015.25 6H10" />
                        </svg>
                      </button>
                      {deleteConfirmId === a.id ? (
                        <div className="flex items-center gap-1">
                          <button
                            type="button"
                            onClick={(e) => { e.stopPropagation(); deleteMutation.mutate(a.id) }}
                            disabled={deleteMutation.isPending}
                            className="inline-flex items-center rounded-md bg-red-600 px-2 py-1 text-xs font-medium text-white hover:bg-red-700 disabled:opacity-50 transition-colors"
                          >
                            Confirm
                          </button>
                          <button
                            type="button"
                            onClick={(e) => { e.stopPropagation(); setDeleteConfirmId(null) }}
                            className="inline-flex items-center rounded-md bg-gray-100 px-2 py-1 text-xs font-medium text-gray-600 hover:bg-gray-200 transition-colors"
                          >
                            Cancel
                          </button>
                        </div>
                      ) : (
                        <button
                          type="button"
                          onClick={(e) => { e.stopPropagation(); setDeleteConfirmId(a.id) }}
                          className="inline-flex items-center rounded-md p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 transition-colors"
                          title="Delete rule"
                        >
                          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
                          </svg>
                        </button>
                      )}
                    </div>
                  </div>
                )
              })}

              {/* Bottom drop zone indicator */}
              {reorderMutation.isPending && (
                <div className="flex items-center justify-center py-2 text-xs text-purple-600">
                  <svg className="h-4 w-4 animate-spin mr-1.5" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  Saving new order...
                </div>
              )}
            </div>
          ) : !isLoading && (
            <p className="text-sm text-gray-500">
              No approval rules configured yet.
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
