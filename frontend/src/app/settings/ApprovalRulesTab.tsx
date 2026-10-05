'use client'

import { useState, useRef, useCallback, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { LeaveApproverAssignment, ApproverRole, OrgTreeNode } from '@/types'
import { useToast } from '@/components/ui/Toast'
import { UserPicker } from '@/components/ui'
import { usePermissions } from '@/contexts/PermissionsContext'
import { ApproverCheckNote } from '@/app/leaves/leaveUi'

type ScopeType = 'default' | 'employee' | 'org_node'

interface StepDraft {
  kind: 'user' | 'role'
  approver_id: number | null
  approver_role: ApproverRole | null
}

interface RuleForm {
  scope_type: ScopeType
  employee_id: number | null
  org_node_id: number | null
  steps: StepDraft[]
  cascade: boolean
  exclude: boolean
}

const BLANK_STEP: StepDraft = { kind: 'user', approver_id: null, approver_role: null }
const EMPTY_FORM: RuleForm = {
  scope_type: 'default',
  employee_id: null,
  org_node_id: null,
  steps: [{ ...BLANK_STEP }],
  cascade: false,
  exclude: false,
}

const APPROVER_ROLE_LABELS: Record<ApproverRole, string> = {
  node_head: 'Direct Manager',
  node_deputy: 'Alternate Manager',
  parent_head: 'Senior Manager',
  parent_deputy: 'Senior Alternate',
}

// Matches what the resolver does (LeaveApprovalService._resolve_approver_role):
// a "head" position falls to the deputy when the head is unavailable; a
// "deputy" position always means the deputy.
const APPROVER_ROLE_DESCRIPTIONS: Record<ApproverRole, string> = {
  node_head: "The head of the employee's unit. If the head is not set, inactive or on leave that day, the unit's deputy approves instead.",
  node_deputy: "Always the deputy of the employee's unit. If there is no active deputy, this step is skipped.",
  parent_head: 'The head of the unit one level above. If that head is not set, inactive or on leave, its deputy approves instead.',
  parent_deputy: 'Always the deputy of the unit one level above. Skipped if there is none.',
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

function flattenOrgNodes(nodes: OrgTreeNode[]): FlatOrgNode[] {
  const result: FlatOrgNode[] = []
  const walk = (ns: OrgTreeNode[], d: number) => {
    for (const n of ns) {
      result.push({
        id: n.id, name: n.name, level_name: n.level_name, depth: d, parent_id: n.parent_id,
        head_user_name: n.head_user_name, deputy_head_user_name: n.deputy_head_user_name,
      })
      if (n.children) walk(n.children, d + 1)
    }
  }
  walk(nodes, 0)
  return result
}

function stepLabel(s: { approver_role?: ApproverRole | null; approver_name?: string | null }): string {
  return s.approver_role ? APPROVER_ROLE_LABELS[s.approver_role] : (s.approver_name || 'Unknown')
}

function scopeText(a: LeaveApproverAssignment): string {
  if (a.employee_id) return a.employee_name ?? `Employee #${a.employee_id}`
  if (a.org_node_id) return `${a.org_node_name ?? `Unit #${a.org_node_id}`}${a.cascade ? ' and all units below it' : ''}`
  if (a.deactivated_reason) return 'nobody (its target no longer exists)'
  return 'everyone not matched by a rule above'
}

const FIELD = 'block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-brand-500 focus:ring-brand-500 focus:outline-none'

export default function ApprovalRulesTab() {
  const queryClient = useQueryClient()
  const { showToast } = useToast()
  const { hasPermission } = usePermissions()
  const canEdit = hasPermission('leave', 'edit')
  const canDelete = hasPermission('leave', 'delete')

  const [formOpen, setFormOpen] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [form, setForm] = useState<RuleForm>(EMPTY_FORM)
  const [deleteConfirmId, setDeleteConfirmId] = useState<number | null>(null)
  const [showHowItWorks, setShowHowItWorks] = useState(false)

  const [dragIndex, setDragIndex] = useState<number | null>(null)
  const [dragOverIndex, setDragOverIndex] = useState<number | null>(null)
  const dragNodeRef = useRef<HTMLDivElement | null>(null)

  const { data: assignments, isLoading } = useQuery<LeaveApproverAssignment[]>({
    queryKey: ['approver-assignments'],
    queryFn: () => api.getApproverAssignments(),
  })
  const { data: orgTree } = useQuery({ queryKey: ['org-tree'], queryFn: () => api.getOrgTree() })
  const flatNodes = useMemo(() => (orgTree ? flattenOrgNodes(orgTree.nodes) : []), [orgTree])

  const resetForm = () => {
    setFormOpen(false)
    setEditingId(null)
    setForm(EMPTY_FORM)
  }

  const afterSave = (saved: LeaveApproverAssignment, verb: string) => {
    queryClient.invalidateQueries({ queryKey: ['approver-assignments'] })
    queryClient.invalidateQueries({ queryKey: ['approval-chain-preview'] })
    resetForm()
    const granted = saved.granted_role_to ?? []
    showToast(
      granted.length
        ? `Approval rule ${verb}. ${granted.join(', ')} ${granted.length === 1 ? 'was' : 'were'} given the Leave Approver role.`
        : `Approval rule ${verb}`,
      'success',
    )
  }

  const createMutation = useMutation({
    mutationFn: (data: Record<string, unknown>) => api.createApproverAssignment(data),
    onSuccess: (saved) => afterSave(saved, 'created'),
    onError: (err: Error) => showToast(err.message, 'error'),
  })
  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Record<string, unknown> }) => api.updateApproverAssignment(id, data),
    onSuccess: (saved) => afterSave(saved, 'updated'),
    onError: (err: Error) => showToast(err.message, 'error'),
  })
  const toggleMutation = useMutation({
    mutationFn: ({ id, is_active }: { id: number; is_active: boolean }) => api.updateApproverAssignment(id, { is_active }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['approver-assignments'] }),
    onError: (err: Error) => showToast(err.message, 'error'),
  })
  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.deleteApproverAssignment(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['approver-assignments'] })
      setDeleteConfirmId(null)
      showToast('Approval rule deleted', 'success')
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

  const handleEdit = (a: LeaveApproverAssignment) => {
    const steps: StepDraft[] = (a.steps && a.steps.length ? a.steps : [{ approver_id: a.approver_id, approver_role: a.approver_role }])
      .map((s) => ({
        kind: s.approver_role ? 'role' : 'user',
        approver_id: s.approver_id ?? null,
        approver_role: (s.approver_role as ApproverRole | null) ?? null,
      }))
    setEditingId(a.id)
    setFormOpen(true)
    setForm({
      scope_type: a.employee_id ? 'employee' : a.org_node_id ? 'org_node' : 'default',
      employee_id: a.employee_id ?? null,
      org_node_id: a.org_node_id ?? null,
      steps: steps.length ? steps : [{ ...BLANK_STEP }],
      cascade: a.cascade ?? false,
      exclude: a.exclude ?? false,
    })
  }

  const stepsValid = form.exclude || (form.steps.length > 0 && form.steps.every((s) => (s.kind === 'user' ? !!s.approver_id : !!s.approver_role)))
  const scopeValid =
    form.scope_type === 'default' ||
    (form.scope_type === 'employee' && !!form.employee_id) ||
    (form.scope_type === 'org_node' && !!form.org_node_id)

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const payload: Record<string, unknown> = {
      steps: form.exclude
        ? []
        : form.steps.map((s) => (s.kind === 'role' ? { approver_role: s.approver_role } : { approver_id: s.approver_id })),
      employee_id: form.scope_type === 'employee' ? form.employee_id : null,
      org_node_id: form.scope_type === 'org_node' ? form.org_node_id : null,
      cascade: form.scope_type === 'org_node' ? form.cascade : false,
      exclude: form.scope_type === 'employee' ? form.exclude : false,
    }
    if (form.exclude) delete payload.steps
    if (editingId !== null) {
      // No priority: editing a rule keeps its place in the list. Only
      // dragging (reorder) moves it.
      updateMutation.mutate({ id: editingId, data: { ...payload, scope: form.scope_type } })
    } else {
      createMutation.mutate(payload)
    }
  }

  const patchStep = (i: number, p: Partial<StepDraft>) =>
    setForm((f) => ({ ...f, steps: f.steps.map((s, j) => (j === i ? { ...s, ...p } : s)) }))
  const moveStep = (i: number, d: -1 | 1) =>
    setForm((f) => {
      const steps = [...f.steps]
      const j = i + d
      if (j < 0 || j >= steps.length) return f
      ;[steps[i], steps[j]] = [steps[j], steps[i]]
      return { ...f, steps }
    })

  const isMutating = createMutation.isPending || updateMutation.isPending
  const sortedAssignments = useMemo(() => assignments ?? [], [assignments])

  // ── Drag and drop (reorder = priority) ─────────────────────────────
  const handleDragStart = useCallback((e: React.DragEvent<HTMLDivElement>, index: number) => {
    setDragIndex(index)
    dragNodeRef.current = e.currentTarget
    e.dataTransfer.effectAllowed = 'move'
    e.dataTransfer.setData('text/plain', String(index))
  }, [])
  const handleDragOver = useCallback((e: React.DragEvent<HTMLDivElement>, index: number) => {
    e.preventDefault()
    setDragOverIndex(index)
  }, [])
  const handleDragEnd = useCallback(() => {
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
    const newList = [...sortedAssignments]
    const [moved] = newList.splice(fromIndex, 1)
    newList.splice(dropIndex, 0, moved)
    reorderMutation.mutate(newList.map((a) => a.id))
    handleDragEnd()
  }, [dragIndex, sortedAssignments, reorderMutation, handleDragEnd])
  const moveRule = (index: number, d: -1 | 1) => {
    const j = index + d
    if (j < 0 || j >= sortedAssignments.length) return
    const newList = [...sortedAssignments]
    ;[newList[index], newList[j]] = [newList[j], newList[index]]
    reorderMutation.mutate(newList.map((a) => a.id))
  }

  const positionHolder = (role: ApproverRole, nodeId: number | null) => {
    if (!nodeId) return null
    const node = flatNodes.find((n) => n.id === nodeId)
    if (!node) return null
    const target = role.startsWith('parent') ? flatNodes.find((n) => n.id === node.parent_id) : node
    if (!target) return 'nobody (no unit above)'
    return (role.endsWith('head') ? target.head_user_name : target.deputy_head_user_name) ?? 'nobody (vacant)'
  }

  return (
    <div className="space-y-6">
      <div className="bg-white shadow-sm ring-1 ring-gray-900/5 rounded-xl">
        <div className="border-b border-gray-200 px-6 py-4 flex items-center justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Approval Rules</h2>
            <p className="mt-1 text-sm text-gray-500">
              Who approves leave when a policy uses custom rules. The first rule in the list that matches an
              employee decides their approvers, in the order the rule lists them.
            </p>
          </div>
          {canEdit && !formOpen && (
            <button type="button" onClick={() => { setFormOpen(true); setEditingId(null); setForm(EMPTY_FORM) }}
              className="inline-flex items-center gap-1.5 rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-brand-700">
              Add Rule
            </button>
          )}
        </div>

        <div className="px-6 py-6 space-y-6">
          {formOpen && canEdit && (
            <form onSubmit={handleSubmit} className="bg-gray-50 border border-gray-200 rounded-lg p-6 space-y-5">
              <h4 className="text-sm font-semibold text-gray-900">{editingId ? 'Edit rule' : 'New approval rule'}</h4>

              <fieldset>
                <legend className="block text-sm font-medium text-gray-700 mb-2">Who does this rule apply to?</legend>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                  {([
                    ['default', 'Everyone', 'Fallback for employees no other rule matches.'],
                    ['employee', 'One employee', 'A single person. Can also exclude them from rules.'],
                    ['org_node', 'A unit', 'Employees in a unit, optionally with the units below it.'],
                  ] as const).map(([value, label, desc]) => (
                    <button key={value} type="button"
                      onClick={() => setForm((p) => ({ ...p, scope_type: value, employee_id: null, org_node_id: null, cascade: false, exclude: false }))}
                      aria-pressed={form.scope_type === value}
                      className={`text-left p-3 rounded-lg border-2 transition-all ${
                        form.scope_type === value ? 'border-brand-500 bg-brand-50' : 'border-gray-200 bg-white hover:border-gray-300'
                      }`}>
                      <span className="text-sm font-medium text-gray-900">{label}</span>
                      <p className="text-xs text-gray-500 mt-0.5">{desc}</p>
                    </button>
                  ))}
                </div>
              </fieldset>

              {form.scope_type === 'employee' && (
                <div className="space-y-3 max-w-lg">
                  <UserPicker label="Employee" value={form.employee_id}
                    onChange={(id) => setForm((p) => ({ ...p, employee_id: id }))} />
                  <label className={`flex items-start gap-3 border rounded-lg p-3 ${form.exclude ? 'bg-red-50 border-red-200' : 'bg-white border-gray-200'}`}>
                    <input type="checkbox" checked={form.exclude}
                      onChange={(e) => setForm((p) => ({ ...p, exclude: e.target.checked }))}
                      className="mt-0.5 h-4 w-4 rounded border-gray-300 text-red-600 focus:ring-red-500" />
                    <span>
                      <span className="text-sm font-medium text-gray-900">Leave this employee out of the rules</span>
                      <span className="block text-xs text-gray-500 mt-0.5">
                        Their leave goes to the org chart (in &ldquo;rules then org chart&rdquo; policies) or to the
                        fallback approver: their line manager, else an administrator. It is never unapproved.
                      </span>
                    </span>
                  </label>
                </div>
              )}

              {form.scope_type === 'org_node' && (
                <div className="space-y-3 max-w-lg">
                  <div>
                    <label htmlFor="rule-node" className="block text-sm font-medium text-gray-700 mb-1">Unit</label>
                    <select id="rule-node" required value={form.org_node_id ?? ''}
                      onChange={(e) => setForm((p) => ({ ...p, org_node_id: parseInt(e.target.value, 10) || null }))} className={FIELD}>
                      <option value="">Select a unit...</option>
                      {flatNodes.map((n) => (
                        <option key={n.id} value={n.id}>{' '.repeat(n.depth * 3)}{n.level_name}: {n.name}</option>
                      ))}
                    </select>
                  </div>
                  <label className="flex items-start gap-3 border rounded-lg p-3 bg-white border-gray-200">
                    <input type="checkbox" checked={form.cascade}
                      onChange={(e) => setForm((p) => ({ ...p, cascade: e.target.checked }))}
                      className="mt-0.5 h-4 w-4 rounded border-gray-300 text-brand-600 focus:ring-brand-500" />
                    <span className="text-sm text-gray-900">Also apply to every unit below it</span>
                  </label>
                </div>
              )}

              {!form.exclude && (
                <fieldset className="space-y-3">
                  <legend className="block text-sm font-medium text-gray-700">Approvers, in order</legend>
                  <p className="text-xs text-gray-500">
                    Step 1 is asked first; once they approve, step 2 is asked, and so on. A rejection at any step
                    ends the request. The policy&apos;s &ldquo;levels of approval&rdquo; setting caps how many steps are used.
                    An inactive person or vacant position is skipped and the next step moves up.
                  </p>
                  {form.steps.map((s, i) => (
                    <div key={i} className="rounded-lg border border-gray-200 bg-white p-3 space-y-2">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-sm font-semibold text-gray-800">Step {i + 1}</span>
                        <div className="flex items-center gap-1">
                          <button type="button" onClick={() => moveStep(i, -1)} disabled={i === 0}
                            className="rounded px-2 py-1 text-xs text-gray-600 hover:bg-gray-100 disabled:opacity-30" aria-label={`Move step ${i + 1} up`}>Up</button>
                          <button type="button" onClick={() => moveStep(i, 1)} disabled={i === form.steps.length - 1}
                            className="rounded px-2 py-1 text-xs text-gray-600 hover:bg-gray-100 disabled:opacity-30" aria-label={`Move step ${i + 1} down`}>Down</button>
                          {form.steps.length > 1 && (
                            <button type="button" onClick={() => setForm((f) => ({ ...f, steps: f.steps.filter((_, j) => j !== i) }))}
                              className="rounded px-2 py-1 text-xs text-red-600 hover:bg-red-50">Remove</button>
                          )}
                        </div>
                      </div>
                      <div className="flex rounded-md border border-gray-200 overflow-hidden max-w-xs">
                        {(['user', 'role'] as const).map((k) => (
                          <button key={k} type="button" onClick={() => patchStep(i, { kind: k, approver_id: null, approver_role: null })}
                            aria-pressed={s.kind === k}
                            className={`flex-1 py-1.5 text-xs font-medium ${s.kind === k ? 'bg-brand-600 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}`}>
                            {k === 'user' ? 'A person' : 'A position'}
                          </button>
                        ))}
                      </div>
                      {s.kind === 'user' ? (
                        <div className="max-w-md">
                          <UserPicker value={s.approver_id} onChange={(id) => patchStep(i, { approver_id: id })}
                            excludeIds={form.employee_id ? [form.employee_id] : []} />
                          <ApproverCheckNote userId={s.approver_id} />
                        </div>
                      ) : (
                        <div className="max-w-md space-y-1">
                          <select value={s.approver_role ?? ''} aria-label={`Step ${i + 1} position`}
                            onChange={(e) => patchStep(i, { approver_role: (e.target.value || null) as ApproverRole | null })} className={FIELD}>
                            <option value="">Select a position...</option>
                            {(Object.keys(APPROVER_ROLE_LABELS) as ApproverRole[]).map((r) => (
                              <option key={r} value={r}>{APPROVER_ROLE_LABELS[r]}</option>
                            ))}
                          </select>
                          {s.approver_role && (
                            <p className="text-xs text-gray-500">
                              {APPROVER_ROLE_DESCRIPTIONS[s.approver_role]}
                              {form.scope_type === 'org_node' && form.org_node_id && (
                                <> Currently: <strong>{positionHolder(s.approver_role, form.org_node_id)}</strong>.</>
                              )}
                            </p>
                          )}
                        </div>
                      )}
                    </div>
                  ))}
                  <button type="button" onClick={() => setForm((f) => ({ ...f, steps: [...f.steps, { ...BLANK_STEP }] }))}
                    className="text-sm font-medium text-brand-700 hover:text-brand-800">
                    + Add another approval step
                  </button>
                </fieldset>
              )}

              <div className="flex items-center gap-3 pt-2">
                <button type="submit" disabled={isMutating || !stepsValid || !scopeValid}
                  className="inline-flex items-center rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-brand-700 disabled:opacity-50 disabled:cursor-not-allowed">
                  {isMutating ? 'Saving...' : editingId ? 'Update rule' : 'Create rule'}
                </button>
                <button type="button" onClick={resetForm}
                  className="inline-flex items-center rounded-md bg-white px-4 py-2 text-sm font-semibold text-gray-700 shadow-sm ring-1 ring-inset ring-gray-300 hover:bg-gray-50">
                  Cancel
                </button>
              </div>
            </form>
          )}

          {!formOpen && (
            <div className="rounded-lg border border-blue-200 bg-blue-50">
              <button type="button" onClick={() => setShowHowItWorks(!showHowItWorks)} aria-expanded={showHowItWorks}
                className="w-full flex items-center justify-between px-4 py-3 text-left text-sm font-semibold text-blue-800">
                How approval rules work
                <span className="text-xs font-normal">{showHowItWorks ? 'Hide' : 'Show'}</span>
              </button>
              {showHowItWorks && (
                <ul className="px-4 pb-4 text-xs text-blue-800 ml-4 list-disc space-y-0.5">
                  <li>Rules only apply to policies set to &ldquo;custom rules&rdquo; or &ldquo;custom rules, then the org chart&rdquo;.</li>
                  <li>The list is checked from the top; the first matching rule is used and the rest are ignored.</li>
                  <li>A rule&apos;s approvers are asked in order: step 1, then step 2, and so on.</li>
                  <li>Nobody ever approves their own leave. If no one can be found, the employee&apos;s line manager, then an administrator, approves.</li>
                  <li>Anyone you name who does not approve leave yet is given the Leave Approver role, so they can see and act on the request.</li>
                </ul>
              )}
            </div>
          )}

          {isLoading ? (
            <p className="text-sm text-gray-500">Loading...</p>
          ) : sortedAssignments.length > 0 ? (
            <div className="space-y-2">
              {sortedAssignments.map((a, index) => {
                const steps = a.steps && a.steps.length ? a.steps : []
                return (
                  <div key={a.id}
                    draggable={canEdit}
                    onDragStart={(e) => handleDragStart(e, index)}
                    onDragOver={(e) => handleDragOver(e, index)}
                    onDragEnd={handleDragEnd}
                    onDrop={(e) => handleDrop(e, index)}
                    className={`flex items-start gap-3 rounded-lg border p-4 ${
                      a.exclude ? 'bg-red-50/60 border-red-200' : !a.is_active ? 'bg-gray-50 border-gray-200' : 'bg-white border-gray-200'
                    } ${dragIndex === index ? 'opacity-40' : ''} ${dragOverIndex === index && dragIndex !== index ? 'ring-2 ring-brand-200' : ''} ${canEdit ? 'cursor-grab' : ''}`}
                  >
                    <span className="mt-0.5 w-6 text-xs font-semibold text-gray-400">{index + 1}.</span>
                    <div className="flex-1 min-w-0 space-y-1">
                      <p className={`text-sm ${a.exclude ? 'text-red-800' : 'text-gray-900'}`}>
                        {a.exclude ? (
                          <>{scopeText(a)} is left out of the approval rules.</>
                        ) : (
                          <>For {scopeText(a)}: {steps.map((s, i) => (
                            <span key={i}>
                              {i > 0 && ' → '}
                              <strong className={s.approver_active === false ? 'line-through text-gray-400' : ''}>{stepLabel(s)}</strong>
                            </span>
                          ))}</>
                        )}
                      </p>
                      {steps.some((s) => s.approver_active === false) && (
                        <p className="text-xs text-amber-700">An approver here is inactive and will be skipped.</p>
                      )}
                      {!a.is_active && (
                        <p className="text-xs text-gray-600">
                          Switched off{a.deactivated_reason ? `: ${a.deactivated_reason}` : '.'}
                        </p>
                      )}
                    </div>
                    <div className="flex-shrink-0 flex flex-wrap items-center gap-1">
                      {canEdit && (
                        <>
                          <button type="button" onClick={() => moveRule(index, -1)} disabled={index === 0}
                            className="rounded px-2 py-1 text-xs text-gray-600 hover:bg-gray-100 disabled:opacity-30" aria-label="Move rule up">Up</button>
                          <button type="button" onClick={() => moveRule(index, 1)} disabled={index === sortedAssignments.length - 1}
                            className="rounded px-2 py-1 text-xs text-gray-600 hover:bg-gray-100 disabled:opacity-30" aria-label="Move rule down">Down</button>
                          <button type="button" onClick={() => handleEdit(a)}
                            className="rounded px-2 py-1 text-xs font-medium text-brand-700 hover:bg-brand-50">Edit</button>
                          <button type="button" onClick={() => toggleMutation.mutate({ id: a.id, is_active: !a.is_active })}
                            className="rounded px-2 py-1 text-xs text-gray-700 hover:bg-gray-100">
                            {a.is_active ? 'Switch off' : 'Switch on'}
                          </button>
                        </>
                      )}
                      {canDelete && (
                        deleteConfirmId === a.id ? (
                          <>
                            <button type="button" onClick={() => deleteMutation.mutate(a.id)} disabled={deleteMutation.isPending}
                              className="rounded bg-red-600 px-2 py-1 text-xs font-medium text-white hover:bg-red-700">Confirm delete</button>
                            <button type="button" onClick={() => setDeleteConfirmId(null)}
                              className="rounded bg-gray-100 px-2 py-1 text-xs text-gray-600 hover:bg-gray-200">Keep</button>
                          </>
                        ) : (
                          <button type="button" onClick={() => setDeleteConfirmId(a.id)}
                            className="rounded px-2 py-1 text-xs text-red-600 hover:bg-red-50">Delete</button>
                        )
                      )}
                    </div>
                  </div>
                )
              })}
              {reorderMutation.isPending && <p className="text-xs text-brand-600">Saving new order...</p>}
            </div>
          ) : (
            <p className="text-sm text-gray-500">No approval rules yet.</p>
          )}
        </div>
      </div>
    </div>
  )
}
