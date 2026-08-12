'use client'

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { PolicyRule, PolicyCondition, PolicyAction, OvertimeCategory, EmployeeTypeConfig } from '@/types'
import { useToast } from '@/components/ui/Toast'
import PolicySimulator from './PolicySimulator'

const RULE_TYPES = [
  { value: 'overtime', label: 'Overtime', description: 'Automatically categorize and process overtime hours' },
  { value: 'tardiness', label: 'Tardiness', description: 'Handle late arrivals with deductions or warnings' },
  { value: 'leave_conversion', label: 'Leave Conversion', description: 'Convert overtime or credits to leave' },
  { value: 'attendance', label: 'Attendance', description: 'General attendance tracking rules' },
  { value: 'night_differential', label: 'Night Differential', description: 'Extra pay for hours worked during night shifts' },
  { value: 'holiday_shift', label: 'Holiday Shift', description: 'Premium pay for working on holidays' },
]

const CONDITION_FIELDS: { value: string; label: string; type: 'number' | 'boolean' | 'select' | 'text'; options?: { value: string; label: string }[] }[] = [
  { value: 'overtime_minutes', label: 'Overtime (minutes)', type: 'number' },
  { value: 'tardiness_minutes', label: 'Tardiness (minutes)', type: 'number' },
  { value: 'undertime_minutes', label: 'Undertime (minutes)', type: 'number' },
  { value: 'hours_worked', label: 'Hours Worked', type: 'number' },
  { value: 'shift_hours', label: 'Shift Duration (hours)', type: 'number' },
  { value: 'is_holiday', label: 'Is Holiday?', type: 'boolean' },
  { value: 'is_special', label: 'Is Special Holiday?', type: 'boolean' },
  // Engine uses ISO weekday numbering (Mon=1 … Sun=7); these values MUST match or
  // the condition never fires (the engine never emits 0).
  { value: 'day_of_week', label: 'Day of Week', type: 'select', options: [
    { value: '1', label: 'Monday' }, { value: '2', label: 'Tuesday' }, { value: '3', label: 'Wednesday' },
    { value: '4', label: 'Thursday' }, { value: '5', label: 'Friday' }, { value: '6', label: 'Saturday' }, { value: '7', label: 'Sunday' },
  ]},
  { value: 'schedule_format', label: 'Schedule Format', type: 'text' },
  { value: 'employee_type', label: 'Employee Type', type: 'select' },
  // Stateful aggregates — computed at evaluation from the employee's own history.
  { value: 'late_count_month', label: 'Late days this month', type: 'number' },
  { value: 'late_count_week', label: 'Late days this week', type: 'number' },
  { value: 'absent_count_month', label: 'Absences this month', type: 'number' },
]

const OPERATORS = [
  { value: 'eq', label: 'equals', symbol: '=' },
  { value: 'neq', label: 'does not equal', symbol: '!=' },
  { value: 'gt', label: 'is greater than', symbol: '>' },
  { value: 'gte', label: 'is at least', symbol: '>=' },
  { value: 'lt', label: 'is less than', symbol: '<' },
  { value: 'lte', label: 'is at most', symbol: '<=' },
  { value: 'in', label: 'is one of', symbol: 'in' },
  { value: 'not_in', label: 'is not one of', symbol: 'not in' },
]

const ACTION_TYPES = [
  { value: 'apply_ot_category', label: 'Apply OT Category', ruleTypes: ['overtime', 'holiday_shift'] },
  { value: 'salary_deduction', label: 'Salary Deduction', ruleTypes: ['tardiness', 'attendance'] },
  { value: 'leave_deduction', label: 'Leave Deduction', ruleTypes: ['tardiness', 'attendance'] },
  { value: 'mark_excused', label: 'Mark Excused', ruleTypes: ['tardiness', 'attendance'] },
  { value: 'send_warning', label: 'Send Warning', ruleTypes: ['tardiness', 'attendance', 'overtime'] },
  { value: 'apply_night_diff', label: 'Apply Night Diff Pay', ruleTypes: ['night_differential'] },
  { value: 'apply_holiday_pay', label: 'Apply Holiday Pay', ruleTypes: ['holiday_shift'] },
]

/** Get action types relevant to the selected rule type, with others available under "Other" */
function getRelevantActionTypes(ruleType: string) {
  const relevant = ACTION_TYPES.filter(a => a.ruleTypes.includes(ruleType))
  const other = ACTION_TYPES.filter(a => !a.ruleTypes.includes(ruleType))
  return { relevant, other }
}

const RULE_TYPE_BADGE: Record<string, string> = {
  overtime: 'bg-blue-100 text-blue-800',
  tardiness: 'bg-yellow-100 text-yellow-800',
  leave_conversion: 'bg-green-100 text-green-800',
  attendance: 'bg-purple-100 text-purple-800',
  night_differential: 'bg-indigo-100 text-indigo-800',
  holiday_shift: 'bg-red-100 text-red-800',
}

interface FormData {
  name: string
  description: string
  rule_type: string
  priority: number
  is_active: boolean
  matchMode: 'all' | 'any'
  conditions: PolicyCondition[]
  actions: PolicyAction[]
  scope_org_node_ids: number[]
  effective_from: string
  effective_until: string
}

const EMPTY_FORM: FormData = {
  name: '',
  description: '',
  rule_type: 'overtime',
  priority: 0,
  is_active: true,
  matchMode: 'all',
  conditions: [{ field: 'overtime_minutes', operator: 'gt', value: 0 }],
  actions: [{ type: 'apply_ot_category', category_code: '' }],
  scope_org_node_ids: [],
  effective_from: '',
  effective_until: '',
}

/** Flatten a stored condition tree into leaves + the top-level match mode for the
 *  simple builder. Nested groups are flattened (leaves kept). */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function flattenConditions(node: any): { mode: 'all' | 'any'; leaves: PolicyCondition[] } {
  const collect = (n: any): PolicyCondition[] => {
    if (Array.isArray(n)) return n.flatMap(collect)
    if (n && typeof n === 'object') {
      if (Array.isArray(n.all)) return n.all.flatMap(collect)
      if (Array.isArray(n.any)) return n.any.flatMap(collect)
      if (n.not) return collect(n.not)
      if (n.field) return [{ field: n.field, operator: n.operator, value: n.value }]
    }
    return []
  }
  let mode: 'all' | 'any' = 'all'
  if (node && typeof node === 'object' && !Array.isArray(node) && Array.isArray(node.any)) mode = 'any'
  return { mode, leaves: collect(node) }
}

/** Build the condition payload the API expects from the simple builder. */
function buildConditionsPayload(mode: 'all' | 'any', leaves: PolicyCondition[]) {
  const clean = leaves.filter(l => l.field)
  if (mode === 'any') return { any: clean }
  return clean  // flat list = implicit ALL (back-compat)
}

/** Summarize a single leaf condition. */
function summarizeLeaf(c: { field?: string; operator?: string; value?: unknown }): string {
  const fieldDef = CONDITION_FIELDS.find(f => f.value === c.field)
  const fieldLabel = fieldDef?.label ?? c.field ?? '?'
  const opLabel = OPERATORS.find(o => o.value === c.operator)?.label ?? c.operator ?? '?'
  let valueLabel = String(c.value ?? '')
  if (fieldDef?.type === 'boolean') valueLabel = c.value ? 'Yes' : 'No'
  else if (c.field === 'day_of_week') {
    const dayOpts = CONDITION_FIELDS.find(f => f.value === 'day_of_week')?.options
    valueLabel = dayOpts?.find(o => o.value === String(c.value))?.label ?? valueLabel
  }
  return `${fieldLabel} ${opLabel} ${valueLabel}`
}

/** Summarize a condition tree (leaf, or all/any/not group) into readable text. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function summarizeConditions(node: any): string {
  if (Array.isArray(node)) {
    return node.map(summarizeConditions).join(' AND ') || '(no conditions)'
  }
  if (node && typeof node === 'object') {
    if (Array.isArray(node.all)) return '(' + node.all.map(summarizeConditions).join(' AND ') + ')'
    if (Array.isArray(node.any)) return '(' + node.any.map(summarizeConditions).join(' OR ') + ')'
    if (node.not) return 'NOT ' + summarizeConditions(node.not)
    return summarizeLeaf(node)
  }
  return ''
}

/** Build a human-readable summary of a rule's conditions and actions */
function summarizeRule(rule: PolicyRule, otCategories: OvertimeCategory[]): string {
  const condText = summarizeConditions(rule.conditions)
  const actionParts = (rule.actions ?? []).map((a) => {
    if (a.type === 'bands') {
      return `Graduated by ${CONDITION_FIELDS.find(f => f.value === a.field)?.label ?? a.field} (${(a.bands ?? []).length} bands)`
    }
    const actionLabel = ACTION_TYPES.find(t => t.value === a.type)?.label ?? a.type
    if (a.type === 'apply_ot_category' && a.category_code) {
      const cat = otCategories.find(c => c.code === a.category_code)
      return `${actionLabel}: ${cat?.name ?? a.category_code}`
    }
    if (a.type === 'apply_night_diff') {
      return `${actionLabel} (${a.start_hour ?? 22}:00 - ${a.end_hour ?? 6}:00)`
    }
    return actionLabel
  })
  return `When ${condText}, then ${actionParts.join(', ')}`
}

export default function PolicyRulesTab() {
  const queryClient = useQueryClient()
  const { showToast } = useToast()

  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [formData, setFormData] = useState<FormData>(EMPTY_FORM)
  const [deleteConfirmId, setDeleteConfirmId] = useState<number | null>(null)
  const [showInactive, setShowInactive] = useState(false)
  const [showHelp, setShowHelp] = useState(false)

  const { data: rules, isLoading } = useQuery<PolicyRule[]>({
    queryKey: ['policy-rules', showInactive],
    queryFn: () => api.listPolicyRules({ active_only: !showInactive }),
  })

  const { data: otCategories } = useQuery<OvertimeCategory[]>({
    queryKey: ['overtime-categories'],
    queryFn: () => api.getOvertimeCategories(),
  })

  const { data: employeeTypes } = useQuery<EmployeeTypeConfig[]>({
    queryKey: ['employee-types'],
    queryFn: () => api.getEmployeeTypes(),
  })

  const activeOtCategories = (otCategories ?? []).filter(c => c.is_active)

  const createMutation = useMutation({
    mutationFn: (data: Record<string, unknown>) => api.createPolicyRule(data),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['policy-rules'] }); resetForm(); showToast('Policy rule created', 'success') },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Record<string, unknown> }) =>
      api.updatePolicyRule(id, data),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['policy-rules'] }); resetForm(); showToast('Policy rule updated', 'success') },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.deletePolicyRule(id),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['policy-rules'] }); setDeleteConfirmId(null); showToast('Policy rule deleted', 'success') },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  const resetForm = () => { setShowForm(false); setEditingId(null); setFormData(EMPTY_FORM) }

  const handleEdit = (rule: PolicyRule) => {
    setEditingId(rule.id)
    setShowForm(false)
    // Normalize the condition tree into a flat leaf list + match mode for the
    // simple builder. A single top-level all/any group maps to matchMode; deeper
    // nesting is flattened (leaves preserved) so the rule stays editable here.
    const norm = flattenConditions(rule.conditions)
    setFormData({
      name: rule.name,
      description: rule.description ?? '',
      rule_type: rule.rule_type,
      priority: rule.priority,
      is_active: rule.is_active,
      matchMode: norm.mode,
      conditions: norm.leaves.length > 0 ? norm.leaves : [{ field: '', operator: 'eq', value: '' }],
      actions: rule.actions.length > 0 ? rule.actions.map(a => ({ ...a })) : [{ type: 'send_warning' }],
      scope_org_node_ids: rule.scope_org_node_ids ?? [],
      effective_from: rule.effective_from ?? '',
      effective_until: rule.effective_until ?? '',
    })
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    // Assemble the API payload: flat leaves + match mode → condition tree, and
    // the scope fields (empty = cleared/all).
    const payload: Record<string, unknown> = {
      name: formData.name,
      description: formData.description,
      rule_type: formData.rule_type,
      priority: formData.priority,
      is_active: formData.is_active,
      conditions: buildConditionsPayload(formData.matchMode, formData.conditions),
      actions: formData.actions,
      scope_org_node_ids: formData.scope_org_node_ids.length ? formData.scope_org_node_ids : null,
      effective_from: formData.effective_from || null,
      effective_until: formData.effective_until || null,
    }
    if (editingId !== null) {
      updateMutation.mutate({ id: editingId, data: payload })
    } else {
      createMutation.mutate(payload)
    }
  }

  const addCondition = () => {
    setFormData(prev => ({
      ...prev,
      conditions: [...prev.conditions, { field: '', operator: 'eq', value: '' }],
    }))
  }

  const removeCondition = (idx: number) => {
    setFormData(prev => ({
      ...prev,
      conditions: prev.conditions.filter((_, i) => i !== idx),
    }))
  }

  const updateCondition = (idx: number, key: keyof PolicyCondition, value: unknown) => {
    setFormData(prev => ({
      ...prev,
      conditions: prev.conditions.map((c, i) => i === idx ? { ...c, [key]: value } : c),
    }))
  }

  const addAction = () => {
    setFormData(prev => ({
      ...prev,
      actions: [...prev.actions, { type: 'send_warning' }],
    }))
  }

  const removeAction = (idx: number) => {
    setFormData(prev => ({
      ...prev,
      actions: prev.actions.filter((_, i) => i !== idx),
    }))
  }

  const updateAction = (idx: number, key: string, value: unknown) => {
    setFormData(prev => ({
      ...prev,
      actions: prev.actions.map((a, i) => i === idx ? { ...a, [key]: value } : a),
    }))
  }

  const isMutating = createMutation.isPending || updateMutation.isPending || deleteMutation.isPending

  const parseConditionValue = (val: string): unknown => {
    if (val === 'true') return true
    if (val === 'false') return false
    const num = Number(val)
    if (!isNaN(num) && val.trim() !== '') return num
    return val
  }

  const renderForm = () => (
    <form onSubmit={handleSubmit} className="bg-gray-50 border border-gray-200 rounded-lg p-6 space-y-4">
      <h4 className="text-sm font-semibold text-gray-900">{editingId ? 'Edit Policy Rule' : 'New Policy Rule'}</h4>

      {/* Rule type as cards */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">What type of rule is this?</label>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
          {RULE_TYPES.map(t => (
            <button
              key={t.value}
              type="button"
              onClick={() => setFormData(p => ({ ...p, rule_type: t.value }))}
              className={`text-left p-2.5 rounded-lg border-2 transition-all ${
                formData.rule_type === t.value
                  ? 'border-purple-500 bg-purple-50 ring-1 ring-purple-500'
                  : 'border-gray-200 bg-white hover:border-gray-300'
              }`}
            >
              <span className={`text-xs font-semibold ${formData.rule_type === t.value ? 'text-purple-900' : 'text-gray-700'}`}>
                {t.label}
              </span>
              <p className="text-[10px] text-gray-500 mt-0.5 leading-tight">{t.description}</p>
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Rule Name</label>
          <input type="text" required value={formData.name}
            onChange={(e) => setFormData(p => ({ ...p, name: e.target.value }))}
            placeholder="e.g. Regular Weekday Overtime"
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none" />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Priority</label>
          <input type="number" value={formData.priority}
            onChange={(e) => setFormData(p => ({ ...p, priority: parseInt(e.target.value, 10) || 0 }))}
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none" />
          <p className="mt-1 text-xs text-gray-500">Lower number = evaluated first. Rules with the same type are checked in priority order; the first match wins.</p>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Description</label>
          <input type="text" value={formData.description}
            onChange={(e) => setFormData(p => ({ ...p, description: e.target.value }))}
            placeholder="Optional - explain what this rule does"
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none" />
        </div>
      </div>

      {/* Conditions */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <label className="block text-sm font-semibold text-gray-700">Conditions</label>
            <div className="inline-flex rounded-md border border-gray-200 overflow-hidden text-xs">
              <button type="button"
                onClick={() => setFormData(p => ({ ...p, matchMode: 'all' }))}
                className={`px-2 py-0.5 ${formData.matchMode === 'all' ? 'bg-purple-600 text-white' : 'bg-white text-gray-600'}`}>
                ALL (AND)
              </button>
              <button type="button"
                onClick={() => setFormData(p => ({ ...p, matchMode: 'any' }))}
                className={`px-2 py-0.5 ${formData.matchMode === 'any' ? 'bg-purple-600 text-white' : 'bg-white text-gray-600'}`}>
                ANY (OR)
              </button>
            </div>
          </div>
          <button type="button" onClick={addCondition}
            className="text-xs text-purple-600 hover:text-purple-700 font-medium">+ Add Condition</button>
        </div>
        <div className="space-y-2">
          {formData.conditions.map((cond, idx) => {
            const fieldDef = CONDITION_FIELDS.find(f => f.value === cond.field)
            // Build employee type options dynamically
            const valueOptions = fieldDef?.value === 'employee_type'
              ? (employeeTypes ?? []).map(et => ({ value: et.code, label: et.name }))
              : fieldDef?.options
            return (
              <div key={idx} className="flex items-center gap-2 bg-white rounded-md border border-gray-200 p-2">
                {idx > 0 && <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider mr-1">{formData.matchMode === 'any' ? 'OR' : 'AND'}</span>}
                <select value={cond.field} onChange={(e) => {
                  updateCondition(idx, 'field', e.target.value)
                  // Reset value when field changes
                  const newFieldDef = CONDITION_FIELDS.find(f => f.value === e.target.value)
                  if (newFieldDef?.type === 'boolean') {
                    updateCondition(idx, 'value', true)
                    updateCondition(idx, 'operator', 'eq')
                  } else {
                    updateCondition(idx, 'value', '')
                  }
                }}
                  className="rounded-md border border-gray-300 px-2 py-1.5 text-xs flex-1">
                  <option value="">Select field...</option>
                  {CONDITION_FIELDS.map(f => <option key={f.value} value={f.value}>{f.label}</option>)}
                </select>
                <select value={cond.operator} onChange={(e) => updateCondition(idx, 'operator', e.target.value)}
                  className="rounded-md border border-gray-300 px-2 py-1.5 text-xs w-28">
                  {OPERATORS.map(o => <option key={o.value} value={o.value}>{o.label} ({o.symbol})</option>)}
                </select>
                {/* Smart value input based on field type */}
                {fieldDef?.type === 'boolean' ? (
                  <select value={String(cond.value ?? 'true')}
                    onChange={(e) => updateCondition(idx, 'value', e.target.value === 'true')}
                    className="rounded-md border border-gray-300 px-2 py-1.5 text-xs w-24">
                    <option value="true">Yes</option>
                    <option value="false">No</option>
                  </select>
                ) : fieldDef?.type === 'select' || (fieldDef?.value === 'employee_type') ? (
                  <select value={String(cond.value ?? '')}
                    onChange={(e) => updateCondition(idx, 'value', parseConditionValue(e.target.value))}
                    className="rounded-md border border-gray-300 px-2 py-1.5 text-xs flex-1">
                    <option value="">Select...</option>
                    {(valueOptions ?? []).map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                  </select>
                ) : (
                  <input type={fieldDef?.type === 'number' ? 'number' : 'text'} value={String(cond.value ?? '')}
                    onChange={(e) => updateCondition(idx, 'value', parseConditionValue(e.target.value))}
                    placeholder={fieldDef?.type === 'number' ? '0' : 'Value'}
                    className="rounded-md border border-gray-300 px-2 py-1.5 text-xs flex-1" />
                )}
                {formData.conditions.length > 1 && (
                  <button type="button" onClick={() => removeCondition(idx)}
                    className="text-red-400 hover:text-red-600 p-1" title="Remove condition">
                    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                )}
              </div>
            )
          })}
        </div>
      </div>

      {/* Actions */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <label className="block text-sm font-semibold text-gray-700">Then do this</label>
          <button type="button" onClick={addAction}
            className="text-xs text-purple-600 hover:text-purple-700 font-medium">+ Add Action</button>
        </div>
        <div className="space-y-2">
          {formData.actions.map((action, idx) => {
            const { relevant, other } = getRelevantActionTypes(formData.rule_type)
            return (
              <div key={idx} className="bg-white rounded-md border border-gray-200 p-2 space-y-2">
                <div className="flex items-center gap-2">
                  <select value={action.type} onChange={(e) => updateAction(idx, 'type', e.target.value)}
                    className="rounded-md border border-gray-300 px-2 py-1.5 text-xs flex-1">
                    {relevant.length > 0 && (
                      <optgroup label="Recommended">
                        {relevant.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
                      </optgroup>
                    )}
                    {other.length > 0 && (
                      <optgroup label="Other actions">
                        {other.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
                      </optgroup>
                    )}
                  </select>
                  {formData.actions.length > 1 && (
                    <button type="button" onClick={() => removeAction(idx)}
                      className="text-red-400 hover:text-red-600 p-1" title="Remove action">
                      <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                      </svg>
                    </button>
                  )}
                </div>
                {/* Action-specific fields */}
                {action.type === 'apply_ot_category' && (
                  <div>
                    <label className="block text-[11px] font-medium text-gray-500 mb-1">Overtime Category</label>
                    <select value={action.category_code ?? ''}
                      onChange={(e) => updateAction(idx, 'category_code', e.target.value)}
                      className="rounded-md border border-gray-300 px-2 py-1.5 text-xs w-full">
                      <option value="">Select category...</option>
                      {activeOtCategories.map(c => (
                        <option key={c.code} value={c.code}>{c.name} ({Math.round(c.multiplier_rate * 100)}%)</option>
                      ))}
                    </select>
                    {!action.category_code && <p className="text-[10px] text-amber-600 mt-1">Please select a category for this rule to work.</p>}
                  </div>
                )}
                {action.type === 'leave_deduction' && (
                  <div>
                    <label className="block text-[11px] font-medium text-gray-500 mb-1">Round to nearest (hours)</label>
                    <input type="number" value={action.round_to_hours ?? ''}
                      onChange={(e) => updateAction(idx, 'round_to_hours', parseInt(e.target.value, 10) || undefined)}
                      placeholder="e.g. 1 = round up to 1 hour"
                      className="rounded-md border border-gray-300 px-2 py-1.5 text-xs w-40" />
                  </div>
                )}
                {action.type === 'apply_night_diff' && (
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="block text-[11px] font-medium text-gray-500 mb-1">Night Window</label>
                      <div className="flex items-center gap-2">
                        <input type="number" value={action.start_hour ?? 22}
                          onChange={(e) => updateAction(idx, 'start_hour', parseInt(e.target.value, 10))}
                          className="rounded-md border border-gray-300 px-2 py-1.5 text-xs w-16" min={0} max={23} />
                        <span className="text-xs text-gray-400">:00 to</span>
                        <input type="number" value={action.end_hour ?? 6}
                          onChange={(e) => updateAction(idx, 'end_hour', parseInt(e.target.value, 10))}
                          className="rounded-md border border-gray-300 px-2 py-1.5 text-xs w-16" min={0} max={23} />
                        <span className="text-xs text-gray-400">:00</span>
                      </div>
                      <p className="text-[10px] text-gray-400 mt-1">e.g. 22:00 to 6:00 = 10PM - 6AM</p>
                    </div>
                    <div>
                      <label className="block text-[11px] font-medium text-gray-500 mb-1">OT Category</label>
                      <select value={action.category_code ?? ''}
                        onChange={(e) => updateAction(idx, 'category_code', e.target.value)}
                        className="rounded-md border border-gray-300 px-2 py-1.5 text-xs w-full">
                        <option value="">Select category...</option>
                        {activeOtCategories.map(c => (
                          <option key={c.code} value={c.code}>{c.name} ({Math.round(c.multiplier_rate * 100)}%)</option>
                        ))}
                      </select>
                      <label className="flex items-center gap-1 text-xs text-gray-600 mt-1.5">
                        <input type="checkbox" checked={!!action.convert_to_leave}
                          onChange={(e) => updateAction(idx, 'convert_to_leave', e.target.checked)}
                          className="h-3 w-3 rounded border-gray-300 text-purple-600" />
                        Also convert to leave credits
                      </label>
                    </div>
                  </div>
                )}
                {action.type === 'apply_holiday_pay' && (
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="block text-[11px] font-medium text-gray-500 mb-1">OT Category</label>
                      <select value={action.category_code ?? ''}
                        onChange={(e) => updateAction(idx, 'category_code', e.target.value)}
                        className="rounded-md border border-gray-300 px-2 py-1.5 text-xs w-full">
                        <option value="">Select category...</option>
                        {activeOtCategories.map(c => (
                          <option key={c.code} value={c.code}>{c.name} ({Math.round(c.multiplier_rate * 100)}%)</option>
                        ))}
                      </select>
                    </div>
                    <div className="flex items-end pb-1">
                      <label className="flex items-center gap-1 text-xs text-gray-600">
                        <input type="checkbox" checked={!!action.convert_to_leave}
                          onChange={(e) => updateAction(idx, 'convert_to_leave', e.target.checked)}
                          className="h-3 w-3 rounded border-gray-300 text-purple-600" />
                        Also convert to leave credits
                      </label>
                    </div>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>

      {/* Scope & scheduling */}
      <div>
        <label className="block text-sm font-semibold text-gray-700 mb-2">Scope &amp; scheduling <span className="font-normal text-gray-400">(optional)</span></label>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <label className="block text-[11px] font-medium text-gray-500 mb-1">Effective from</label>
            <input type="date" value={formData.effective_from}
              onChange={(e) => setFormData(p => ({ ...p, effective_from: e.target.value }))}
              className="w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm" />
          </div>
          <div>
            <label className="block text-[11px] font-medium text-gray-500 mb-1">Effective until</label>
            <input type="date" value={formData.effective_until}
              min={formData.effective_from || undefined}
              onChange={(e) => setFormData(p => ({ ...p, effective_until: e.target.value }))}
              className="w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm" />
          </div>
        </div>
        <p className="mt-1 text-[11px] text-gray-400">
          Leave the dates blank for an always-on rule. Org-node targeting is available via the API.
        </p>
      </div>

      {/* Rule Preview */}
      {formData.conditions[0]?.field && formData.actions[0]?.type && (
        <div className="bg-purple-50 border border-purple-200 rounded-md p-3">
          <p className="text-xs font-medium text-purple-800 mb-1">Rule preview</p>
          <p className="text-sm text-purple-900">
            {summarizeRule(
              { id: 0, name: formData.name, description: '', rule_type: formData.rule_type, priority: formData.priority, is_active: formData.is_active, conditions: formData.conditions, actions: formData.actions } as PolicyRule,
              otCategories ?? []
            )}
          </p>
        </div>
      )}

      <div className="flex items-center gap-2">
        <input type="checkbox" id="is_active" checked={formData.is_active}
          onChange={(e) => setFormData(p => ({ ...p, is_active: e.target.checked }))}
          className="h-4 w-4 rounded border-gray-300 text-purple-600 focus:ring-purple-500" />
        <label htmlFor="is_active" className="text-sm text-gray-700">Active</label>
      </div>

      <div className="flex items-center gap-3 pt-2">
        <button type="submit" disabled={isMutating}
          className="inline-flex items-center rounded-md bg-purple-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors">
          {isMutating ? 'Saving...' : editingId ? 'Update' : 'Create'}
        </button>
        <button type="button" onClick={resetForm}
          className="inline-flex items-center rounded-md bg-white px-4 py-2 text-sm font-semibold text-gray-700 shadow-sm ring-1 ring-inset ring-gray-300 hover:bg-gray-50 transition-colors">
          Cancel
        </button>
      </div>
    </form>
  )

  return (
    <div className="space-y-8">
      <PolicySimulator />

      <div className="bg-white shadow-sm ring-1 ring-gray-900/5 rounded-xl">
        <div className="border-b border-gray-200 px-6 py-4 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Policy Rules</h2>
            <p className="mt-1 text-sm text-gray-500">
              Configure condition-based rules for overtime, tardiness, and leave automation.
            </p>
          </div>
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-2 text-sm text-gray-600">
              <input type="checkbox" checked={showInactive} onChange={(e) => setShowInactive(e.target.checked)}
                className="h-4 w-4 rounded border-gray-300 text-purple-600 focus:ring-purple-500" />
              Show inactive
            </label>
            {!showForm && editingId === null && (
              <button type="button" onClick={() => { setShowForm(true); setEditingId(null); setFormData(EMPTY_FORM) }}
                className="inline-flex items-center gap-1.5 rounded-md bg-purple-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-purple-700 transition-colors">
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
                </svg>
                Add Rule
              </button>
            )}
          </div>
        </div>

        <div className="px-6 py-6 space-y-6">
          {(showForm || editingId !== null) && renderForm()}

          {isLoading ? (
            <div className="flex items-center gap-3 text-sm text-gray-500">
              <svg className="h-5 w-5 animate-spin text-purple-600" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              Loading...
            </div>
          ) : rules && rules.length > 0 ? (
            <div className="space-y-2">
              {rules.map((rule) => (
                <div key={rule.id} className={`group border rounded-lg overflow-hidden transition-all hover:shadow-sm ${rule.is_active ? 'border-gray-200' : 'border-gray-200 opacity-60'}`}>
                  <div className="flex items-start justify-between px-4 py-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap mb-1">
                        <span className="text-sm font-semibold text-gray-900">{rule.name}</span>
                        <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${RULE_TYPE_BADGE[rule.rule_type] ?? 'bg-gray-100 text-gray-800'}`}>
                          {rule.rule_type.replace('_', ' ')}
                        </span>
                        <span className="inline-flex items-center rounded-full bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-500">
                          Priority {rule.priority}
                        </span>
                        {!rule.is_active && (
                          <span className="inline-flex items-center rounded-full bg-red-100 text-red-800 px-2 py-0.5 text-xs font-medium">Inactive</span>
                        )}
                      </div>
                      {rule.description && <p className="text-xs text-gray-500 mb-1.5">{rule.description}</p>}
                      <p className="text-sm text-gray-700 leading-relaxed">
                        {summarizeRule(rule, otCategories ?? [])}
                      </p>
                    </div>
                    <div className="flex-shrink-0 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity ml-3">
                      <button type="button" onClick={() => handleEdit(rule)}
                        className="inline-flex items-center rounded-md p-1.5 text-gray-400 hover:text-purple-600 hover:bg-purple-50 transition-colors" title="Edit">
                        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125M18 14v4.75A2.25 2.25 0 0115.75 21H5.25A2.25 2.25 0 013 18.75V8.25A2.25 2.25 0 015.25 6H10" />
                        </svg>
                      </button>
                      {deleteConfirmId === rule.id ? (
                        <div className="flex items-center gap-1">
                          <button type="button" onClick={() => deleteMutation.mutate(rule.id)} disabled={deleteMutation.isPending}
                            className="inline-flex items-center rounded-md bg-red-600 px-2 py-1 text-xs font-medium text-white hover:bg-red-700 disabled:opacity-50 transition-colors">Confirm</button>
                          <button type="button" onClick={() => setDeleteConfirmId(null)}
                            className="inline-flex items-center rounded-md bg-gray-100 px-2 py-1 text-xs font-medium text-gray-600 hover:bg-gray-200 transition-colors">Cancel</button>
                        </div>
                      ) : (
                        <button type="button" onClick={() => setDeleteConfirmId(rule.id)}
                          className="inline-flex items-center rounded-md p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 transition-colors" title="Delete">
                          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
                          </svg>
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-center py-12">
              <svg className="mx-auto h-12 w-12 text-gray-300" fill="none" viewBox="0 0 24 24" strokeWidth={1} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.324.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.431l-1.003.827c-.293.24-.438.613-.431.992a6.759 6.759 0 010 .255c-.007.378.138.75.43.99l1.005.828c.424.35.534.954.26 1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.57 6.57 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.28c-.09.543-.56.941-1.11.941h-2.594c-.55 0-1.02-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 1.125 0 01.26-1.431l1.004-.827c.292-.24.437-.613.43-.992a6.932 6.932 0 010-.255c.007-.378-.138-.75-.43-.99l-1.004-.828a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.087.22-.128.332-.183.582-.495.644-.869l.214-1.281z" />
                <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
              </svg>
              <h3 className="mt-2 text-sm font-semibold text-gray-900">No policy rules</h3>
              <p className="mt-1 text-sm text-gray-500">Create rules to automate overtime, tardiness, and leave handling.</p>
            </div>
          )}
        </div>
      </div>

      <div className="rounded-lg border border-blue-200 bg-blue-50 overflow-hidden">
        <button
          type="button"
          onClick={() => setShowHelp(!showHelp)}
          className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-blue-100/50 transition-colors"
        >
          <div className="flex items-center gap-2">
            <svg className="h-4 w-4 text-blue-600" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M11.25 11.25l.041-.02a.75.75 0 011.063.852l-.708 2.836a.75.75 0 001.063.853l.041-.021M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9-3.75h.008v.008H12V8.25z" />
            </svg>
            <span className="text-sm font-semibold text-blue-800">How Policy Rules Work</span>
          </div>
          <svg className={`h-4 w-4 text-blue-600 transition-transform ${showHelp ? 'rotate-180' : ''}`} fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
          </svg>
        </button>
        {showHelp && (
          <div className="px-4 pb-4">
            <ul className="text-xs text-blue-700 space-y-1 list-disc list-inside">
              <li>Rules are evaluated when attendance is recorded, in <strong>priority order</strong> (lowest number first).</li>
              <li>All conditions must match (<strong>AND logic</strong>) for a rule to fire.</li>
              <li>For each rule type (overtime, tardiness, etc.), only the <strong>first matching rule</strong> is applied.</li>
              <li>Actions are executed automatically: creating OT logs, tardiness records, or leave adjustments.</li>
              <li><strong>Night Differential:</strong> Computes hours worked during the configured night window (e.g., 22:00-06:00) and creates a pay log.</li>
              <li><strong>Holiday Shift:</strong> Applies holiday pay multiplier when an employee works on a marked holiday.</li>
            </ul>
          </div>
        )}
      </div>
    </div>
  )
}
