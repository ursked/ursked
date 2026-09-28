'use client'

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Copy, Pencil, Power, AlertTriangle, Star } from 'lucide-react'
import { api } from '@/lib/api'
import type { LeavePolicy } from '@/types'
import { useToast } from '@/components/ui/Toast'
import {
  Button,
  Card,
  CardBody,
  Badge,
  EmptyState,
  ConfirmDialog,
} from '@/components/ui'
import { POOL_TYPE, ACCRUAL_METHOD, APPROVAL_MODE, ENFORCEMENT_RULES } from '@/lib/copy/policies'
import { usePermissions } from '@/contexts/PermissionsContext'
import PolicyWizard from './PolicyWizard'
import LeaveTypesSection from './LeaveTypesSection'

function completenessWarnings(p: LeavePolicy): string[] {
  const c = p.completeness
  if (!c) return []
  const out: string[] = []
  if (!c.has_entitlements) {
    out.push('No leave types have credits yet — employees on this policy get no leave.')
  }
  if (c.uncovered_leave_types.length) {
    out.push(`These types have 0 credits: ${c.uncovered_leave_types.join(', ')}.`)
  }
  if (!c.has_employment_types && !p.is_default) {
    out.push('No employment types selected and not the default — this policy may never apply.')
  }
  if (!c.enforcement_configured) {
    out.push('No filing rules set: limits are not enforced (employees are still warned about overlaps and overdrawn balances).')
  }
  return out
}

export default function LeavePoliciesV2() {
  const qc = useQueryClient()
  const { showToast } = useToast()
  const [wizardOpen, setWizardOpen] = useState(false)
  const [editing, setEditing] = useState<LeavePolicy | null>(null)
  const [wizardStep, setWizardStep] = useState(0)
  const { hasPermission } = usePermissions()
  const canEdit = hasPermission('leave', 'edit')
  const canDelete = hasPermission('leave', 'delete')
  const [deactivateId, setDeactivateId] = useState<number | null>(null)

  const { data: policies, isLoading } = useQuery<LeavePolicy[]>({
    queryKey: ['leave-policies'],
    queryFn: () => api.getLeavePolicies(),
  })

  const clone = useMutation({
    mutationFn: (id: number) => api.cloneLeavePolicy(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['leave-policies'] })
      showToast('Policy cloned', 'success')
    },
    onError: (e: unknown) => showToast((e as Error)?.message ?? 'Clone failed', 'error'),
  })

  const deactivate = useMutation({
    mutationFn: (id: number) => api.deleteLeavePolicy(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['leave-policies'] })
      showToast('Policy deactivated', 'success')
      setDeactivateId(null)
    },
    onError: (e: unknown) => showToast((e as Error)?.message ?? 'Failed', 'error'),
  })

  const openCreate = () => {
    setEditing(null)
    setWizardStep(0)
    setWizardOpen(true)
  }
  const openEdit = (p: LeavePolicy, step = 0) => {
    setEditing(p)
    setWizardStep(step)
    setWizardOpen(true)
  }

  const active = (policies ?? []).filter((p) => p.is_active)

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-gray-500">
          Leave policies decide how many days each group of employees gets and how requests are approved.
        </p>
        {canEdit && (
          <Button onClick={openCreate}>
            <Plus className="h-4 w-4" /> New policy
          </Button>
        )}
      </div>

      {isLoading ? (
        <div className="text-sm text-gray-400">Loading…</div>
      ) : active.length === 0 ? (
        <EmptyState
          icon={Plus}
          title="No leave policies yet"
          description="Create your first policy to define leave allowances and approval flow."
          action={canEdit ? <Button onClick={openCreate}>Create a policy</Button> : undefined}
        />
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {active.map((p) => {
            const warnings = completenessWarnings(p)
            const entCount =
              p.pool_type === 'shared'
                ? (p.shared_annual_credits ?? 0) > 0
                  ? 1
                  : 0
                : p.entitlements.filter((e) => e.annual_credits > 0).length
            return (
              <Card key={p.id}>
                <CardBody className="space-y-3">
                  <div className="flex items-start justify-between">
                    <div>
                      <div className="flex items-center gap-2">
                        <h3 className="text-base font-semibold text-gray-900">{p.name}</h3>
                        {p.is_default && (
                          <Badge tone="purple">
                            <Star className="mr-1 h-3 w-3" /> Default
                          </Badge>
                        )}
                      </div>
                      {p.description && (
                        <p className="mt-0.5 text-sm text-gray-500">{p.description}</p>
                      )}
                    </div>
                  </div>

                  <div className="flex flex-wrap gap-1.5">
                    <Badge tone="gray">{POOL_TYPE[p.pool_type].label}</Badge>
                    <Badge tone="gray">{ACCRUAL_METHOD[p.accrual_method].label}</Badge>
                    <Badge tone="blue">{APPROVAL_MODE[p.approval_mode].label}</Badge>
                    <Badge tone="blue">
                      {p.required_approval_levels > 1 ? `${p.required_approval_levels} approval levels` : '1 approver'}
                    </Badge>
                    <Badge tone={entCount ? 'green' : 'yellow'}>
                      {entCount} leave type{entCount === 1 ? '' : 's'} funded
                    </Badge>
                  </div>

                  {p.employment_types.length > 0 && (
                    <div className="flex flex-wrap gap-1">
                      {p.employment_types.map((t) => (
                        <span
                          key={t}
                          className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600"
                        >
                          {t}
                        </span>
                      ))}
                    </div>
                  )}

                  {warnings.length > 0 && (
                    <div className="space-y-1 rounded-lg bg-yellow-50 p-2.5">
                      {warnings.map((w, i) => (
                        <div key={i} className="flex gap-2 text-xs text-yellow-800">
                          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                          <span>{w}</span>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Filing rules, visible on the card so they can be found */}
                  <div className="rounded-lg border border-gray-200 px-3 py-2">
                    <div className="text-xs font-medium text-gray-700">Filing rules</div>
                    <ul className="mt-1 grid gap-0.5 text-xs text-gray-600 sm:grid-cols-2">
                      {ENFORCEMENT_RULES.map((r) => {
                        const mode = p.enforcement?.[r.key] ?? 'off'
                        return (
                          <li key={r.key}>
                            {r.label}:{' '}
                            <span className={mode === 'block' ? 'font-medium text-red-700' : mode === 'warn' ? 'font-medium text-amber-700' : 'text-gray-500'}>
                              {mode === 'block' ? 'Block' : mode === 'warn' ? 'Warn' : 'Off'}
                            </span>
                          </li>
                        )
                      })}
                    </ul>
                  </div>

                  <div className="flex flex-wrap gap-2 pt-1">
                    {canEdit && (
                      <>
                        <Button variant="secondary" size="sm" onClick={() => openEdit(p)}>
                          <Pencil className="h-3.5 w-3.5" /> Edit
                        </Button>
                        <Button variant="secondary" size="sm" onClick={() => openEdit(p, 3)}>
                          Approvals &amp; filing rules
                        </Button>
                        <Button
                          variant="secondary"
                          size="sm"
                          loading={clone.isPending}
                          onClick={() => clone.mutate(p.id)}
                        >
                          <Copy className="h-3.5 w-3.5" /> Clone
                        </Button>
                      </>
                    )}
                    {canDelete && (
                      <Button variant="ghost" size="sm" onClick={() => setDeactivateId(p.id)}>
                        <Power className="h-3.5 w-3.5" /> Deactivate
                      </Button>
                    )}
                  </div>
                </CardBody>
              </Card>
            )
          })}
        </div>
      )}

      <LeaveTypesSection />

      <PolicyWizard open={wizardOpen} onOpenChange={setWizardOpen} policy={editing} initialStep={wizardStep} />

      <ConfirmDialog
        open={deactivateId !== null}
        onOpenChange={(o) => !o && setDeactivateId(null)}
        title="Deactivate this policy?"
        description="Employees will fall back to the default policy. You can recreate it later."
        confirmLabel="Deactivate"
        variant="danger"
        loading={deactivate.isPending}
        onConfirm={() => deactivateId && deactivate.mutate(deactivateId)}
      />
    </div>
  )
}
