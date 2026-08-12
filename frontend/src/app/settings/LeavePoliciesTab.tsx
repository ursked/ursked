'use client'

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { LeaveTypeConfig, LeavePolicy, LeavePolicyEntitlement, EmployeeTypeConfig } from '@/types'
import { useToast } from '@/components/ui/Toast'

const ACCRUAL_OPTIONS = [
  { value: 'annual', label: 'Annual', description: 'Employees receive their full yearly leave credits on January 1st.' },
  { value: 'monthly', label: 'Monthly', description: 'Credits accrue each month (1/12 of annual total per month).' },
]

const POOL_TYPE_OPTIONS = [
  { value: 'per_type', label: 'Per Type', description: 'Each leave type (vacation, sick, etc.) has its own separate credit balance.' },
  { value: 'shared', label: 'Shared Pool', description: 'A single credit pool shared across all leave types. Simpler but less control.' },
]

// Employment types are now fetched from API

// ── Leave Type Form ─────────────────────────────────────────────────

interface LeaveTypeFormData {
  code: string
  name: string
  description: string
  sort_order: number
}

const EMPTY_TYPE_FORM: LeaveTypeFormData = { code: '', name: '', description: '', sort_order: 0 }

// ── Policy Form ─────────────────────────────────────────────────────

const APPROVAL_MODE_OPTIONS = [
  { value: 'auto', label: 'Auto', description: 'Uses organization hierarchy. The employee\'s manager approves automatically.' },
  { value: 'manual', label: 'Manual', description: 'Uses the Approval Rules you configured. Full control over who approves.' },
  { value: 'hybrid', label: 'Hybrid', description: 'Tries Approval Rules first. Falls back to org hierarchy if no rule matches.' },
]

interface PolicyFormData {
  name: string
  description: string
  accrual_method: string
  pool_type: string
  employment_types: string[]
  is_default: boolean
  approval_mode: string
  required_approval_levels: number
  shared_annual_credits: number
  shared_carry_over_enabled: boolean
  shared_max_carry_over_days: number
  shared_carry_over_expiry_months: number
  shared_cash_convertible: boolean
  shared_cash_conversion_rate: number
}

const EMPTY_POLICY_FORM: PolicyFormData = {
  name: '',
  description: '',
  accrual_method: 'annual',
  pool_type: 'per_type',
  employment_types: [],
  is_default: false,
  approval_mode: 'auto',
  required_approval_levels: 1,
  shared_annual_credits: 0,
  shared_carry_over_enabled: false,
  shared_max_carry_over_days: 0,
  shared_carry_over_expiry_months: 0,
  shared_cash_convertible: false,
  shared_cash_conversion_rate: 1.0,
}

// ── Entitlement Form ────────────────────────────────────────────────

interface EntitlementFormData {
  leave_type_id: number
  annual_credits: number
  carry_over_enabled: boolean
  max_carry_over_days: number
  carry_over_expiry_months: number
  cash_convertible: boolean
  cash_conversion_rate: number
  requires_documentation: boolean
  min_notice_days: number
}

const EMPTY_ENTITLEMENT_FORM: EntitlementFormData = {
  leave_type_id: 0,
  annual_credits: 0,
  carry_over_enabled: false,
  max_carry_over_days: 0,
  carry_over_expiry_months: 0,
  cash_convertible: false,
  cash_conversion_rate: 1.0,
  requires_documentation: false,
  min_notice_days: 0,
}

export default function LeavePoliciesTab() {
  const queryClient = useQueryClient()
  const { showToast } = useToast()

  // ── Leave Type state ──────────────────────────────────────────────
  const [showTypeForm, setShowTypeForm] = useState(false)
  const [editingTypeId, setEditingTypeId] = useState<number | null>(null)
  const [typeForm, setTypeForm] = useState<LeaveTypeFormData>(EMPTY_TYPE_FORM)
  const [deleteTypeConfirmId, setDeleteTypeConfirmId] = useState<number | null>(null)

  // ── Policy state ──────────────────────────────────────────────────
  const [showPolicyForm, setShowPolicyForm] = useState(false)
  const [editingPolicyId, setEditingPolicyId] = useState<number | null>(null)
  const [policyForm, setPolicyForm] = useState<PolicyFormData>(EMPTY_POLICY_FORM)
  const [expandedPolicyId, setExpandedPolicyId] = useState<number | null>(null)
  const [deletePolicyConfirmId, setDeletePolicyConfirmId] = useState<number | null>(null)

  // ── Entitlement state ─────────────────────────────────────────────
  const [showEntitlementForm, setShowEntitlementForm] = useState(false)
  const [editingEntitlementId, setEditingEntitlementId] = useState<number | null>(null)
  const [entitlementForm, setEntitlementForm] = useState<EntitlementFormData>(EMPTY_ENTITLEMENT_FORM)
  const [entitlementPolicyId, setEntitlementPolicyId] = useState<number | null>(null)
  const [deleteEntConfirmKey, setDeleteEntConfirmKey] = useState<string | null>(null)

  // ── Queries ───────────────────────────────────────────────────────
  const { data: leaveTypes, isLoading: typesLoading } = useQuery<LeaveTypeConfig[]>({
    queryKey: ['leave-types'],
    queryFn: () => api.getLeaveTypes(),
  })

  const { data: policies, isLoading: policiesLoading } = useQuery<LeavePolicy[]>({
    queryKey: ['leave-policies'],
    queryFn: () => api.getLeavePolicies(),
  })

  const { data: employeeTypes } = useQuery<EmployeeTypeConfig[]>({
    queryKey: ['employee-types'],
    queryFn: () => api.getEmployeeTypes(),
  })

  // ── Leave Type mutations ──────────────────────────────────────────
  const createTypeMutation = useMutation({
    mutationFn: (data: LeaveTypeFormData) => api.createLeaveType(data),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['leave-types'] }); resetTypeForm(); showToast('Leave type created', 'success') },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  const updateTypeMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<LeaveTypeFormData> & { is_active?: boolean } }) =>
      api.updateLeaveType(id, data),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['leave-types'] }); resetTypeForm(); showToast('Leave type updated', 'success') },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  const deleteTypeMutation = useMutation({
    mutationFn: (id: number) => api.deleteLeaveType(id),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['leave-types'] }); setDeleteTypeConfirmId(null); showToast('Leave type deactivated', 'success') },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  // ── Policy mutations ──────────────────────────────────────────────
  const createPolicyMutation = useMutation({
    mutationFn: (data: PolicyFormData) => api.createLeavePolicy(data),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['leave-policies'] }); resetPolicyForm(); showToast('Policy created', 'success') },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  const updatePolicyMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<PolicyFormData> }) =>
      api.updateLeavePolicy(id, data),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['leave-policies'] }); resetPolicyForm(); showToast('Policy updated', 'success') },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  const deletePolicyMutation = useMutation({
    mutationFn: (id: number) => api.deleteLeavePolicy(id),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['leave-policies'] }); setDeletePolicyConfirmId(null); showToast('Policy deactivated', 'success') },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  // ── Entitlement mutations ─────────────────────────────────────────
  const addEntitlementMutation = useMutation({
    mutationFn: ({ policyId, data }: { policyId: number; data: EntitlementFormData }) =>
      api.addPolicyEntitlement(policyId, data),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['leave-policies'] }); resetEntitlementForm(); showToast('Entitlement added', 'success') },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  const updateEntitlementMutation = useMutation({
    mutationFn: ({ policyId, entitlementId, data }: { policyId: number; entitlementId: number; data: Partial<EntitlementFormData> }) =>
      api.updatePolicyEntitlement(policyId, entitlementId, data),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['leave-policies'] }); resetEntitlementForm(); showToast('Entitlement updated', 'success') },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  const deleteEntitlementMutation = useMutation({
    mutationFn: ({ policyId, entitlementId }: { policyId: number; entitlementId: number }) =>
      api.deletePolicyEntitlement(policyId, entitlementId),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['leave-policies'] }); showToast('Entitlement removed', 'success') },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  // ── Form helpers ──────────────────────────────────────────────────
  const resetTypeForm = () => { setShowTypeForm(false); setEditingTypeId(null); setTypeForm(EMPTY_TYPE_FORM) }
  const resetPolicyForm = () => { setShowPolicyForm(false); setEditingPolicyId(null); setPolicyForm(EMPTY_POLICY_FORM) }
  const resetEntitlementForm = () => { setShowEntitlementForm(false); setEditingEntitlementId(null); setEntitlementForm(EMPTY_ENTITLEMENT_FORM); setEntitlementPolicyId(null) }

  const handleTypeCodeChange = (value: string) => {
    const sanitized = value.toLowerCase().replace(/[^a-z0-9_]/g, '_')
    setTypeForm((prev) => ({ ...prev, code: sanitized }))
  }

  const handleEditType = (lt: LeaveTypeConfig) => {
    setEditingTypeId(lt.id)
    setShowTypeForm(false)
    setTypeForm({ code: lt.code, name: lt.name, description: lt.description ?? '', sort_order: lt.sort_order })
  }

  const handleTypeSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (editingTypeId !== null) {
      updateTypeMutation.mutate({ id: editingTypeId, data: { name: typeForm.name, description: typeForm.description || undefined, sort_order: typeForm.sort_order } })
    } else {
      createTypeMutation.mutate(typeForm)
    }
  }

  const handleEditPolicy = (p: LeavePolicy) => {
    setEditingPolicyId(p.id)
    setShowPolicyForm(false)
    setPolicyForm({
      name: p.name,
      description: p.description ?? '',
      accrual_method: p.accrual_method,
      pool_type: p.pool_type,
      employment_types: p.employment_types,
      is_default: p.is_default,
      approval_mode: p.approval_mode ?? 'auto',
      required_approval_levels: p.required_approval_levels ?? 1,
      shared_annual_credits: p.shared_annual_credits ?? 0,
      shared_carry_over_enabled: p.shared_carry_over_enabled,
      shared_max_carry_over_days: p.shared_max_carry_over_days,
      shared_carry_over_expiry_months: p.shared_carry_over_expiry_months,
      shared_cash_convertible: p.shared_cash_convertible,
      shared_cash_conversion_rate: p.shared_cash_conversion_rate,
    })
  }

  const handlePolicySubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (editingPolicyId !== null) {
      updatePolicyMutation.mutate({ id: editingPolicyId, data: policyForm })
    } else {
      createPolicyMutation.mutate(policyForm)
    }
  }

  const handleAddEntitlement = (policyId: number) => {
    setEntitlementPolicyId(policyId)
    setShowEntitlementForm(true)
    setEditingEntitlementId(null)
    setEntitlementForm(EMPTY_ENTITLEMENT_FORM)
  }

  const handleEditEntitlement = (policyId: number, ent: LeavePolicyEntitlement) => {
    setEntitlementPolicyId(policyId)
    setEditingEntitlementId(ent.id)
    setShowEntitlementForm(false)
    setEntitlementForm({
      leave_type_id: ent.leave_type_id,
      annual_credits: ent.annual_credits,
      carry_over_enabled: ent.carry_over_enabled,
      max_carry_over_days: ent.max_carry_over_days,
      carry_over_expiry_months: ent.carry_over_expiry_months,
      cash_convertible: ent.cash_convertible,
      cash_conversion_rate: ent.cash_conversion_rate,
      requires_documentation: ent.requires_documentation,
      min_notice_days: ent.min_notice_days,
    })
  }

  const handleEntitlementSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!entitlementPolicyId) return
    if (editingEntitlementId !== null) {
      updateEntitlementMutation.mutate({ policyId: entitlementPolicyId, entitlementId: editingEntitlementId, data: entitlementForm })
    } else {
      addEntitlementMutation.mutate({ policyId: entitlementPolicyId, data: entitlementForm })
    }
  }

  const toggleEmploymentType = (value: string) => {
    setPolicyForm((prev) => ({
      ...prev,
      employment_types: prev.employment_types.includes(value)
        ? prev.employment_types.filter((t) => t !== value)
        : [...prev.employment_types, value],
    }))
  }

  const isTypeMutating = createTypeMutation.isPending || updateTypeMutation.isPending || deleteTypeMutation.isPending
  const isPolicyMutating = createPolicyMutation.isPending || updatePolicyMutation.isPending || deletePolicyMutation.isPending
  const isEntitlementMutating = addEntitlementMutation.isPending || updateEntitlementMutation.isPending || deleteEntitlementMutation.isPending

  // ── Render: Leave Type form ───────────────────────────────────────
  const renderTypeForm = () => (
    <form onSubmit={handleTypeSubmit} className="bg-gray-50 border border-gray-200 rounded-lg p-6 space-y-4">
      <h4 className="text-sm font-semibold text-gray-900">{editingTypeId ? 'Edit Leave Type' : 'New Leave Type'}</h4>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Code</label>
          <input type="text" required value={typeForm.code} onChange={(e) => handleTypeCodeChange(e.target.value)}
            disabled={editingTypeId !== null} placeholder="e.g. comp_off"
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none disabled:opacity-50 disabled:bg-gray-100" />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Name</label>
          <input type="text" required value={typeForm.name} onChange={(e) => setTypeForm((p) => ({ ...p, name: e.target.value }))}
            placeholder="e.g. Compensatory Off"
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none" />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Description</label>
          <input type="text" value={typeForm.description} onChange={(e) => setTypeForm((p) => ({ ...p, description: e.target.value }))}
            placeholder="Optional description"
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none" />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Sort Order</label>
          <input type="number" value={typeForm.sort_order} onChange={(e) => setTypeForm((p) => ({ ...p, sort_order: parseInt(e.target.value, 10) || 0 }))}
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none" />
        </div>
      </div>
      <div className="flex items-center gap-3 pt-2">
        <button type="submit" disabled={isTypeMutating}
          className="inline-flex items-center rounded-md bg-purple-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors">
          {isTypeMutating ? 'Saving...' : editingTypeId ? 'Update' : 'Create'}
        </button>
        <button type="button" onClick={resetTypeForm}
          className="inline-flex items-center rounded-md bg-white px-4 py-2 text-sm font-semibold text-gray-700 shadow-sm ring-1 ring-inset ring-gray-300 hover:bg-gray-50 transition-colors">
          Cancel
        </button>
      </div>
    </form>
  )

  // ── Render: Policy form ───────────────────────────────────────────
  const renderPolicyForm = () => (
    <form onSubmit={handlePolicySubmit} className="bg-gray-50 border border-gray-200 rounded-lg p-6 space-y-4">
      <h4 className="text-sm font-semibold text-gray-900">{editingPolicyId ? 'Edit Policy' : 'New Leave Policy'}</h4>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Policy Name</label>
          <input type="text" required value={policyForm.name} onChange={(e) => setPolicyForm((p) => ({ ...p, name: e.target.value }))}
            placeholder="e.g. Standard" className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none" />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Description</label>
          <input type="text" value={policyForm.description} onChange={(e) => setPolicyForm((p) => ({ ...p, description: e.target.value }))}
            placeholder="Optional" className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none" />
        </div>
      </div>

      {/* Accrual Method - card selection */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">When do employees receive their leave credits?</label>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {ACCRUAL_OPTIONS.map((o) => (
            <button
              key={o.value}
              type="button"
              onClick={() => setPolicyForm((p) => ({ ...p, accrual_method: o.value }))}
              className={`text-left p-3 rounded-lg border-2 transition-all ${
                policyForm.accrual_method === o.value
                  ? 'border-purple-500 bg-purple-50 ring-1 ring-purple-500'
                  : 'border-gray-200 bg-white hover:border-gray-300'
              }`}
            >
              <span className={`text-sm font-medium ${policyForm.accrual_method === o.value ? 'text-purple-900' : 'text-gray-700'}`}>
                {o.label}
              </span>
              <p className="text-xs text-gray-500 mt-0.5">{o.description}</p>
            </button>
          ))}
        </div>
      </div>

      {/* Pool Type - card selection */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">How should leave credits be organized?</label>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {POOL_TYPE_OPTIONS.map((o) => (
            <button
              key={o.value}
              type="button"
              onClick={() => setPolicyForm((p) => ({ ...p, pool_type: o.value }))}
              className={`text-left p-3 rounded-lg border-2 transition-all ${
                policyForm.pool_type === o.value
                  ? 'border-purple-500 bg-purple-50 ring-1 ring-purple-500'
                  : 'border-gray-200 bg-white hover:border-gray-300'
              }`}
            >
              <span className={`text-sm font-medium ${policyForm.pool_type === o.value ? 'text-purple-900' : 'text-gray-700'}`}>
                {o.label}
              </span>
              <p className="text-xs text-gray-500 mt-0.5">{o.description}</p>
            </button>
          ))}
        </div>
      </div>

      {/* Employment types */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">Employment Types</label>
        <div className="flex flex-wrap gap-2">
          {(employeeTypes ?? []).map((et) => (
            <label key={et.code} className="inline-flex items-center gap-2 cursor-pointer">
              <input type="checkbox" checked={policyForm.employment_types.includes(et.code)}
                onChange={() => toggleEmploymentType(et.code)}
                className="rounded border-gray-300 text-purple-600 focus:ring-purple-500" />
              <span className="text-sm text-gray-700">{et.name}</span>
            </label>
          ))}
        </div>
      </div>

      {/* Default checkbox */}
      <label className="inline-flex items-center gap-2 cursor-pointer">
        <input type="checkbox" checked={policyForm.is_default} onChange={(e) => setPolicyForm((p) => ({ ...p, is_default: e.target.checked }))}
          className="rounded border-gray-300 text-purple-600 focus:ring-purple-500" />
        <span className="text-sm text-gray-700">Default policy (fallback when no employment type match)</span>
      </label>

      {/* Approval settings */}
      <div className="border-t border-gray-200 pt-4 space-y-4">
        <h5 className="text-sm font-medium text-gray-700">How should leave requests be approved?</h5>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          {APPROVAL_MODE_OPTIONS.map((o) => (
            <button
              key={o.value}
              type="button"
              onClick={() => setPolicyForm((p) => ({ ...p, approval_mode: o.value }))}
              className={`text-left p-3 rounded-lg border-2 transition-all ${
                policyForm.approval_mode === o.value
                  ? 'border-purple-500 bg-purple-50 ring-1 ring-purple-500'
                  : 'border-gray-200 bg-white hover:border-gray-300'
              }`}
            >
              <span className={`text-sm font-medium ${policyForm.approval_mode === o.value ? 'text-purple-900' : 'text-gray-700'}`}>
                {o.label}
              </span>
              <p className="text-xs text-gray-500 mt-0.5">{o.description}</p>
            </button>
          ))}
        </div>
        <div className="max-w-xs">
          <label className="block text-sm font-medium text-gray-700 mb-1">Required Approval Levels</label>
          <input type="number" min="1" value={policyForm.required_approval_levels}
            onChange={(e) => setPolicyForm((p) => ({ ...p, required_approval_levels: parseInt(e.target.value, 10) || 1 }))}
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none" />
          <p className="mt-1 text-xs text-gray-500">
            How many approvers must sign off before a leave request is fully approved.
            {policyForm.required_approval_levels > 1 && ` Each level approves in sequence (Step 1, then Step 2, etc.).`}
          </p>
        </div>
      </div>

      {/* Shared pool fields */}
      {policyForm.pool_type === 'shared' && (
        <div className="border-t border-gray-200 pt-4 space-y-4">
          <h5 className="text-sm font-medium text-gray-700">Shared Pool Configuration</h5>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Annual Credits</label>
              <input type="number" step="0.5" min="0" value={policyForm.shared_annual_credits}
                onChange={(e) => setPolicyForm((p) => ({ ...p, shared_annual_credits: parseFloat(e.target.value) || 0 }))}
                className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none" />
            </div>
            <div className="flex items-end">
              <label className="inline-flex items-center gap-2 cursor-pointer pb-2">
                <input type="checkbox" checked={policyForm.shared_carry_over_enabled}
                  onChange={(e) => setPolicyForm((p) => ({ ...p, shared_carry_over_enabled: e.target.checked }))}
                  className="rounded border-gray-300 text-purple-600 focus:ring-purple-500" />
                <span className="text-sm text-gray-700">Enable carry-over</span>
              </label>
            </div>
            {policyForm.shared_carry_over_enabled && (
              <>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Max Carry-Over Days</label>
                  <input type="number" step="0.5" min="0" value={policyForm.shared_max_carry_over_days}
                    onChange={(e) => setPolicyForm((p) => ({ ...p, shared_max_carry_over_days: parseFloat(e.target.value) || 0 }))}
                    className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none" />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Carry-over Expiry</label>
                  <input type="number" min="0" value={policyForm.shared_carry_over_expiry_months}
                    onChange={(e) => setPolicyForm((p) => ({ ...p, shared_carry_over_expiry_months: parseInt(e.target.value, 10) || 0 }))}
                    className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none" />
                  <p className="mt-1 text-xs text-gray-500">
                    {policyForm.shared_carry_over_expiry_months > 0
                      ? `Carried-over credits expire after ${policyForm.shared_carry_over_expiry_months} month${policyForm.shared_carry_over_expiry_months !== 1 ? 's' : ''}.`
                      : 'Set to 0 for no expiration. Carried-over credits never expire.'}
                  </p>
                </div>
              </>
            )}
            <div className="flex items-end">
              <label className="inline-flex items-center gap-2 cursor-pointer pb-2">
                <input type="checkbox" checked={policyForm.shared_cash_convertible}
                  onChange={(e) => setPolicyForm((p) => ({ ...p, shared_cash_convertible: e.target.checked }))}
                  className="rounded border-gray-300 text-purple-600 focus:ring-purple-500" />
                <span className="text-sm text-gray-700">Cash convertible</span>
              </label>
            </div>
            {policyForm.shared_cash_convertible && (
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Cash Conversion Rate</label>
                <div className="flex items-center gap-2">
                  <input type="number" step="0.01" min="0" value={policyForm.shared_cash_conversion_rate}
                    onChange={(e) => setPolicyForm((p) => ({ ...p, shared_cash_conversion_rate: parseFloat(e.target.value) || 1.0 }))}
                    className="block w-24 rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none" />
                  <span className="text-sm text-gray-500">x daily rate</span>
                </div>
                <p className="mt-1 text-xs text-gray-500">
                  {policyForm.shared_cash_conversion_rate === 1 ? '1 unused leave day = 1 day of pay.' : `1 unused leave day = ${policyForm.shared_cash_conversion_rate}x of daily pay.`}
                </p>
              </div>
            )}
          </div>
        </div>
      )}

      <div className="flex items-center gap-3 pt-2">
        <button type="submit" disabled={isPolicyMutating}
          className="inline-flex items-center rounded-md bg-purple-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors">
          {isPolicyMutating ? 'Saving...' : editingPolicyId ? 'Update Policy' : 'Create Policy'}
        </button>
        <button type="button" onClick={resetPolicyForm}
          className="inline-flex items-center rounded-md bg-white px-4 py-2 text-sm font-semibold text-gray-700 shadow-sm ring-1 ring-inset ring-gray-300 hover:bg-gray-50 transition-colors">
          Cancel
        </button>
      </div>
    </form>
  )

  // ── Render: Entitlement form ──────────────────────────────────────
  const renderEntitlementForm = () => (
    <form onSubmit={handleEntitlementSubmit} className="bg-blue-50 border border-blue-200 rounded-lg p-4 space-y-3 mt-3">
      <h5 className="text-sm font-semibold text-gray-900">{editingEntitlementId ? 'Edit Entitlement' : 'Add Entitlement'}</h5>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Leave Type</label>
          <select required value={entitlementForm.leave_type_id}
            onChange={(e) => setEntitlementForm((p) => ({ ...p, leave_type_id: parseInt(e.target.value, 10) || 0 }))}
            disabled={editingEntitlementId !== null}
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none disabled:opacity-50 disabled:bg-gray-100">
            <option value={0}>Select leave type</option>
            {leaveTypes?.filter((lt) => lt.is_active).map((lt) => (
              <option key={lt.id} value={lt.id}>{lt.name}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Annual Credits</label>
          <input type="number" step="0.5" min="0" required value={entitlementForm.annual_credits}
            onChange={(e) => setEntitlementForm((p) => ({ ...p, annual_credits: parseFloat(e.target.value) || 0 }))}
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none" />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Min Notice Days</label>
          <input type="number" min="0" value={entitlementForm.min_notice_days}
            onChange={(e) => setEntitlementForm((p) => ({ ...p, min_notice_days: parseInt(e.target.value, 10) || 0 }))}
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none" />
        </div>
      </div>
      <div className="flex flex-wrap gap-4">
        <label className="inline-flex items-center gap-2 cursor-pointer">
          <input type="checkbox" checked={entitlementForm.carry_over_enabled}
            onChange={(e) => setEntitlementForm((p) => ({ ...p, carry_over_enabled: e.target.checked }))}
            className="rounded border-gray-300 text-purple-600 focus:ring-purple-500" />
          <span className="text-sm text-gray-700">Carry-over</span>
        </label>
        {entitlementForm.carry_over_enabled && (
          <>
            <div className="flex items-center gap-1">
              <label className="text-xs text-gray-600">Max days:</label>
              <input type="number" step="0.5" min="0" value={entitlementForm.max_carry_over_days}
                onChange={(e) => setEntitlementForm((p) => ({ ...p, max_carry_over_days: parseFloat(e.target.value) || 0 }))}
                className="w-20 rounded-md border border-gray-300 px-2 py-1 text-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none" />
            </div>
            <div className="flex items-center gap-1">
              <label className="text-xs text-gray-600">Expiry months:</label>
              <input type="number" min="0" value={entitlementForm.carry_over_expiry_months}
                onChange={(e) => setEntitlementForm((p) => ({ ...p, carry_over_expiry_months: parseInt(e.target.value, 10) || 0 }))}
                className="w-20 rounded-md border border-gray-300 px-2 py-1 text-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none" />
            </div>
          </>
        )}
        <label className="inline-flex items-center gap-2 cursor-pointer">
          <input type="checkbox" checked={entitlementForm.cash_convertible}
            onChange={(e) => setEntitlementForm((p) => ({ ...p, cash_convertible: e.target.checked }))}
            className="rounded border-gray-300 text-purple-600 focus:ring-purple-500" />
          <span className="text-sm text-gray-700">Cash convertible</span>
        </label>
        {entitlementForm.cash_convertible && (
          <div className="flex items-center gap-1">
            <label className="text-xs text-gray-600">Rate:</label>
            <input type="number" step="0.01" min="0" value={entitlementForm.cash_conversion_rate}
              onChange={(e) => setEntitlementForm((p) => ({ ...p, cash_conversion_rate: parseFloat(e.target.value) || 1.0 }))}
              className="w-20 rounded-md border border-gray-300 px-2 py-1 text-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none" />
          </div>
        )}
        <label className="inline-flex items-center gap-2 cursor-pointer">
          <input type="checkbox" checked={entitlementForm.requires_documentation}
            onChange={(e) => setEntitlementForm((p) => ({ ...p, requires_documentation: e.target.checked }))}
            className="rounded border-gray-300 text-purple-600 focus:ring-purple-500" />
          <span className="text-sm text-gray-700">Requires documentation</span>
        </label>
      </div>
      <div className="flex items-center gap-3 pt-1">
        <button type="submit" disabled={isEntitlementMutating || entitlementForm.leave_type_id === 0}
          className="inline-flex items-center rounded-md bg-purple-600 px-3 py-1.5 text-sm font-semibold text-white shadow-sm hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors">
          {isEntitlementMutating ? 'Saving...' : editingEntitlementId ? 'Update' : 'Add'}
        </button>
        <button type="button" onClick={resetEntitlementForm}
          className="inline-flex items-center rounded-md bg-white px-3 py-1.5 text-sm font-semibold text-gray-700 shadow-sm ring-1 ring-inset ring-gray-300 hover:bg-gray-50 transition-colors">
          Cancel
        </button>
      </div>
    </form>
  )

  return (
    <div className="space-y-8">
      {/* ── Leave Types Section ───────────────────────────────────── */}
      <div className="bg-white shadow-sm ring-1 ring-gray-900/5 rounded-xl">
        <div className="border-b border-gray-200 px-6 py-4 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Leave Types</h2>
            <p className="mt-1 text-sm text-gray-500">Configure the types of leave available in your organization.</p>
          </div>
          {!showTypeForm && editingTypeId === null && (
            <button type="button" onClick={() => { setShowTypeForm(true); setEditingTypeId(null); setTypeForm(EMPTY_TYPE_FORM) }}
              className="inline-flex items-center gap-1.5 rounded-md bg-purple-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-purple-700 transition-colors">
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
              </svg>
              Add Leave Type
            </button>
          )}
        </div>
        <div className="px-6 py-6 space-y-6">
          {(showTypeForm || editingTypeId !== null) && renderTypeForm()}
          {typesLoading ? (
            <div className="flex items-center gap-3 text-sm text-gray-500">
              <svg className="h-5 w-5 animate-spin text-purple-600" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              Loading...
            </div>
          ) : leaveTypes && leaveTypes.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200">
                <thead>
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Code</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Name</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Status</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Order</th>
                    <th className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-wider text-gray-500">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {leaveTypes.map((lt) => (
                    <tr key={lt.id} className={`transition-colors ${lt.is_active ? 'hover:bg-gray-50' : 'opacity-50'}`}>
                      <td className="px-4 py-3 text-sm font-mono text-gray-900">{lt.code}</td>
                      <td className="px-4 py-3 text-sm text-gray-900">{lt.name}</td>
                      <td className="px-4 py-3">
                        <button
                          type="button"
                          onClick={() => updateTypeMutation.mutate({ id: lt.id, data: { is_active: !lt.is_active } })}
                          className={`relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-purple-500 focus:ring-offset-2 ${lt.is_active ? 'bg-purple-600' : 'bg-gray-200'}`}
                          title={lt.is_active ? 'Click to deactivate' : 'Click to activate'}
                        >
                          <span className={`pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${lt.is_active ? 'translate-x-4' : 'translate-x-0'}`} />
                        </button>
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-600">{lt.sort_order}</td>
                      <td className="px-4 py-3 text-right">
                        <div className="flex items-center justify-end gap-2">
                          <button type="button" onClick={() => handleEditType(lt)}
                            className="inline-flex items-center rounded-md p-1.5 text-gray-400 hover:text-purple-600 hover:bg-purple-50 transition-colors" title="Edit">
                            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                              <path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125M18 14v4.75A2.25 2.25 0 0115.75 21H5.25A2.25 2.25 0 013 18.75V8.25A2.25 2.25 0 015.25 6H10" />
                            </svg>
                          </button>
                          {deleteTypeConfirmId === lt.id ? (
                            <div className="flex items-center gap-1">
                              <button type="button" onClick={() => deleteTypeMutation.mutate(lt.id)} disabled={deleteTypeMutation.isPending}
                                className="inline-flex items-center rounded-md bg-red-600 px-2 py-1 text-xs font-medium text-white hover:bg-red-700 disabled:opacity-50 transition-colors">Confirm</button>
                              <button type="button" onClick={() => setDeleteTypeConfirmId(null)}
                                className="inline-flex items-center rounded-md bg-gray-100 px-2 py-1 text-xs font-medium text-gray-600 hover:bg-gray-200 transition-colors">Cancel</button>
                            </div>
                          ) : (
                            <button type="button" onClick={() => setDeleteTypeConfirmId(lt.id)}
                              className="inline-flex items-center rounded-md p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 transition-colors"
                              title="Delete">
                              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
                              </svg>
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-sm text-gray-500">No leave types configured yet.</p>
          )}
        </div>
      </div>

      {/* ── Leave Policies Section ────────────────────────────────── */}
      <div className="bg-white shadow-sm ring-1 ring-gray-900/5 rounded-xl">
        <div className="border-b border-gray-200 px-6 py-4 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Leave Policies</h2>
            <p className="mt-1 text-sm text-gray-500">Define leave credit policies per employment type.</p>
          </div>
          {!showPolicyForm && editingPolicyId === null && (
            <button type="button" onClick={() => { setShowPolicyForm(true); setEditingPolicyId(null); setPolicyForm(EMPTY_POLICY_FORM) }}
              className="inline-flex items-center gap-1.5 rounded-md bg-purple-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-purple-700 transition-colors">
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
              </svg>
              Add Policy
            </button>
          )}
        </div>
        <div className="px-6 py-6 space-y-6">
          {(showPolicyForm || editingPolicyId !== null) && renderPolicyForm()}
          {policiesLoading ? (
            <div className="flex items-center gap-3 text-sm text-gray-500">
              <svg className="h-5 w-5 animate-spin text-purple-600" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              Loading...
            </div>
          ) : policies && policies.length > 0 ? (
            <div className="space-y-4">
              {policies.map((policy) => (
                <div key={policy.id} className="border border-gray-200 rounded-lg overflow-hidden">
                  {/* Policy header row */}
                  <div className="flex items-center justify-between px-4 py-3 bg-gray-50 cursor-pointer"
                    onClick={() => setExpandedPolicyId(expandedPolicyId === policy.id ? null : policy.id)}>
                    <div className="flex items-center gap-3 flex-wrap">
                      <svg className={`h-4 w-4 text-gray-500 transition-transform ${expandedPolicyId === policy.id ? 'rotate-90' : ''}`}
                        fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
                      </svg>
                      <span className="text-sm font-semibold text-gray-900">{policy.name}</span>
                      <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${policy.accrual_method === 'monthly' ? 'bg-blue-100 text-blue-800' : 'bg-green-100 text-green-800'}`}>
                        {policy.accrual_method}
                      </span>
                      <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${policy.pool_type === 'shared' ? 'bg-amber-100 text-amber-800' : 'bg-indigo-100 text-indigo-800'}`}>
                        {policy.pool_type === 'per_type' ? 'Per Type' : 'Shared Pool'}
                      </span>
                      <span className="inline-flex items-center rounded-full bg-cyan-100 text-cyan-800 px-2 py-0.5 text-xs font-medium">
                        {policy.approval_mode ?? 'auto'} ({policy.required_approval_levels ?? 1} level{(policy.required_approval_levels ?? 1) > 1 ? 's' : ''})
                      </span>
                      {policy.is_default && (
                        <span className="inline-flex items-center rounded-full bg-purple-100 text-purple-800 px-2 py-0.5 text-xs font-medium">Default</span>
                      )}
                      {!policy.is_active && (
                        <span className="inline-flex items-center rounded-full bg-red-100 text-red-800 px-2 py-0.5 text-xs font-medium">Inactive</span>
                      )}
                    </div>
                    <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
                      <button type="button" onClick={() => handleEditPolicy(policy)}
                        className="inline-flex items-center rounded-md p-1.5 text-gray-400 hover:text-purple-600 hover:bg-purple-50 transition-colors" title="Edit">
                        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125M18 14v4.75A2.25 2.25 0 0115.75 21H5.25A2.25 2.25 0 013 18.75V8.25A2.25 2.25 0 015.25 6H10" />
                        </svg>
                      </button>
                      {deletePolicyConfirmId === policy.id ? (
                        <div className="flex items-center gap-1">
                          <button type="button" onClick={() => deletePolicyMutation.mutate(policy.id)} disabled={deletePolicyMutation.isPending}
                            className="inline-flex items-center rounded-md bg-red-600 px-2 py-1 text-xs font-medium text-white hover:bg-red-700 disabled:opacity-50 transition-colors">Confirm</button>
                          <button type="button" onClick={() => setDeletePolicyConfirmId(null)}
                            className="inline-flex items-center rounded-md bg-gray-100 px-2 py-1 text-xs font-medium text-gray-600 hover:bg-gray-200 transition-colors">Cancel</button>
                        </div>
                      ) : (
                        <button type="button" onClick={() => setDeletePolicyConfirmId(policy.id)}
                          className="inline-flex items-center rounded-md p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 transition-colors" title="Deactivate">
                          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
                          </svg>
                        </button>
                      )}
                    </div>
                  </div>

                  {/* Employment types */}
                  {policy.employment_types.length > 0 && (
                    <div className="px-4 py-2 bg-gray-50 border-t border-gray-100">
                      <div className="flex flex-wrap gap-1.5">
                        {policy.employment_types.map((et) => {
                          const etConfig = employeeTypes?.find((t) => t.code === et)
                          return (
                            <span key={et} className="inline-flex items-center rounded-full bg-gray-200 text-gray-700 px-2 py-0.5 text-xs">
                              {etConfig?.name ?? et.replace(/_/g, ' ')}
                            </span>
                          )
                        })}
                      </div>
                    </div>
                  )}

                  {/* Expanded: entitlements */}
                  {expandedPolicyId === policy.id && (
                    <div className="px-4 py-4 border-t border-gray-200">
                      {policy.pool_type === 'per_type' ? (
                        <>
                          <div className="flex items-center justify-between mb-3">
                            <h4 className="text-sm font-semibold text-gray-700">Entitlements</h4>
                            <button type="button" onClick={() => handleAddEntitlement(policy.id)}
                              className="inline-flex items-center gap-1 rounded-md bg-purple-50 text-purple-700 px-3 py-1 text-xs font-medium hover:bg-purple-100 transition-colors">
                              <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
                              </svg>
                              Add
                            </button>
                          </div>
                          {(showEntitlementForm || editingEntitlementId !== null) && entitlementPolicyId === policy.id && renderEntitlementForm()}
                          {policy.entitlements.length > 0 ? (
                            <div className="overflow-x-auto">
                              <table className="min-w-full divide-y divide-gray-200 text-sm">
                                <thead>
                                  <tr>
                                    <th className="px-3 py-2 text-left text-xs font-semibold uppercase text-gray-500">Leave Type</th>
                                    <th className="px-3 py-2 text-left text-xs font-semibold uppercase text-gray-500">Credits</th>
                                    <th className="px-3 py-2 text-left text-xs font-semibold uppercase text-gray-500">Carry-Over</th>
                                    <th className="px-3 py-2 text-left text-xs font-semibold uppercase text-gray-500">Cash Conv.</th>
                                    <th className="px-3 py-2 text-left text-xs font-semibold uppercase text-gray-500">Docs</th>
                                    <th className="px-3 py-2 text-left text-xs font-semibold uppercase text-gray-500">Notice</th>
                                    <th className="px-3 py-2 text-right text-xs font-semibold uppercase text-gray-500">Actions</th>
                                  </tr>
                                </thead>
                                <tbody className="divide-y divide-gray-100">
                                  {policy.entitlements.map((ent) => (
                                    <tr key={ent.id} className="hover:bg-gray-50">
                                      <td className="px-3 py-2 text-gray-900">{ent.leave_type_name || ent.leave_type_code}</td>
                                      <td className="px-3 py-2 text-gray-700 font-medium">{ent.annual_credits}</td>
                                      <td className="px-3 py-2 text-gray-600">
                                        {ent.carry_over_enabled ? `${ent.max_carry_over_days}d` : '--'}
                                        {ent.carry_over_enabled && ent.carry_over_expiry_months > 0 && ` (${ent.carry_over_expiry_months}mo)`}
                                      </td>
                                      <td className="px-3 py-2 text-gray-600">
                                        {ent.cash_convertible ? `${ent.cash_conversion_rate}x` : '--'}
                                      </td>
                                      <td className="px-3 py-2">
                                        {ent.requires_documentation ? (
                                          <span className="inline-flex items-center rounded-full bg-amber-100 text-amber-800 px-2 py-0.5 text-xs font-medium">Yes</span>
                                        ) : <span className="text-gray-400">--</span>}
                                      </td>
                                      <td className="px-3 py-2 text-gray-600">{ent.min_notice_days > 0 ? `${ent.min_notice_days}d` : '--'}</td>
                                      <td className="px-3 py-2 text-right">
                                        <div className="flex items-center justify-end gap-1">
                                          <button type="button" onClick={() => handleEditEntitlement(policy.id, ent)}
                                            className="p-1 text-gray-400 hover:text-purple-600 transition-colors" title="Edit">
                                            <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                                              <path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125M18 14v4.75A2.25 2.25 0 0115.75 21H5.25A2.25 2.25 0 013 18.75V8.25A2.25 2.25 0 015.25 6H10" />
                                            </svg>
                                          </button>
                                          {deleteEntConfirmKey === `${policy.id}-${ent.id}` ? (
                                            <div className="flex items-center gap-1">
                                              <button type="button"
                                                onClick={() => { deleteEntitlementMutation.mutate({ policyId: policy.id, entitlementId: ent.id }); setDeleteEntConfirmKey(null) }}
                                                disabled={deleteEntitlementMutation.isPending}
                                                className="inline-flex items-center rounded-md bg-red-600 px-1.5 py-0.5 text-[10px] font-medium text-white hover:bg-red-700 disabled:opacity-50 transition-colors">
                                                Remove
                                              </button>
                                              <button type="button"
                                                onClick={() => setDeleteEntConfirmKey(null)}
                                                className="inline-flex items-center rounded-md bg-gray-100 px-1.5 py-0.5 text-[10px] font-medium text-gray-600 hover:bg-gray-200 transition-colors">
                                                Cancel
                                              </button>
                                            </div>
                                          ) : (
                                            <button type="button"
                                              onClick={() => setDeleteEntConfirmKey(`${policy.id}-${ent.id}`)}
                                              className="p-1 text-gray-400 hover:text-red-600 transition-colors" title="Remove entitlement">
                                              <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                                                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                                              </svg>
                                            </button>
                                          )}
                                        </div>
                                      </td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          ) : (
                            <p className="text-sm text-gray-500 mt-2">No entitlements configured. Add entitlements to define credits per leave type.</p>
                          )}
                        </>
                      ) : (
                        <div className="text-sm text-gray-600 space-y-1">
                          <p><span className="font-medium">Shared Annual Credits:</span> {policy.shared_annual_credits ?? 0}</p>
                          <p><span className="font-medium">Carry-Over:</span> {policy.shared_carry_over_enabled ? `Up to ${policy.shared_max_carry_over_days} days` : 'Disabled'}</p>
                          {policy.shared_carry_over_enabled && policy.shared_carry_over_expiry_months > 0 && (
                            <p><span className="font-medium">Carry-Over Expiry:</span> {policy.shared_carry_over_expiry_months} months</p>
                          )}
                          <p><span className="font-medium">Cash Convertible:</span> {policy.shared_cash_convertible ? `Yes (${policy.shared_cash_conversion_rate}x)` : 'No'}</p>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-gray-500">No leave policies configured yet.</p>
          )}
        </div>
      </div>
    </div>
  )
}
