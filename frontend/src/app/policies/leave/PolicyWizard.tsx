'use client'

import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { z } from 'zod'
import { api } from '@/lib/api'
import type {
  EmployeeTypeConfig,
  EnforcementMode,
  EnforcementRule,
  LeavePolicy,
  LeaveTypeConfig,
} from '@/types'
import { useToast } from '@/components/ui/Toast'
import {
  Button,
  Input,
  FormField,
  Modal,
  Switch,
  SegmentedControl,
  Badge,
  WizardProgress,
  useWizard,
} from '@/components/ui'
import {
  ACCRUAL_METHOD,
  APPROVAL_MODE,
  ENFORCEMENT_MODE_COPY,
  ENFORCEMENT_RULES,
  POOL_TYPE,
} from '@/lib/copy/policies'

interface EntitlementDraft {
  leave_type_id: number
  leave_type_code: string
  leave_type_name: string
  enabled: boolean
  annual_credits: number
  carry_over_enabled: boolean
  max_carry_over_days: number
  carry_over_expiry_months: number
  cash_convertible: boolean
  cash_conversion_rate: number
  requires_documentation: boolean
  min_notice_days: number
  max_consecutive_days: number | null
}

interface WizardState {
  name: string
  description: string
  pool_type: 'per_type' | 'shared'
  accrual_method: 'annual' | 'monthly'
  is_default: boolean
  employment_types: string[]
  approval_mode: 'auto' | 'manual' | 'hybrid'
  enforcement: Partial<Record<EnforcementRule, EnforcementMode>>
  entitlements: EntitlementDraft[]
  // shared-pool fields
  shared_annual_credits: number
  shared_carry_over_enabled: boolean
  shared_max_carry_over_days: number
  shared_carry_over_expiry_months: number
  shared_cash_convertible: boolean
  shared_cash_conversion_rate: number
  shared_max_consecutive_days: number | null
}

const STEPS = [
  { key: 'coverage', title: 'Coverage' },
  { key: 'credits', title: 'Leave & Credits' },
  { key: 'carryover', title: 'Carry-over & Cash' },
  { key: 'approvals', title: 'Approvals & Rules' },
]

const coverageSchema = z.object({
  name: z.string().min(1, 'Give the policy a name'),
  pool_type: z.enum(['per_type', 'shared']),
  accrual_method: z.enum(['annual', 'monthly']),
})

function blankEntitlement(lt: LeaveTypeConfig): EntitlementDraft {
  return {
    leave_type_id: lt.id,
    leave_type_code: lt.code,
    leave_type_name: lt.name,
    enabled: false,
    annual_credits: 0,
    carry_over_enabled: false,
    max_carry_over_days: 0,
    carry_over_expiry_months: 0,
    cash_convertible: false,
    cash_conversion_rate: 1,
    requires_documentation: false,
    min_notice_days: 0,
    max_consecutive_days: null,
  }
}

function initialState(
  leaveTypes: LeaveTypeConfig[],
  existing?: LeavePolicy | null
): WizardState {
  if (existing) {
    const byType = new Map(existing.entitlements.map((e) => [e.leave_type_id, e]))
    return {
      name: existing.name,
      description: existing.description ?? '',
      pool_type: existing.pool_type,
      accrual_method: existing.accrual_method,
      is_default: existing.is_default,
      employment_types: existing.employment_types ?? [],
      approval_mode: existing.approval_mode,
      enforcement: existing.enforcement ?? {},
      entitlements: leaveTypes.map((lt) => {
        const e = byType.get(lt.id)
        const base = blankEntitlement(lt)
        if (!e) return base
        return {
          ...base,
          enabled: true,
          annual_credits: e.annual_credits,
          carry_over_enabled: e.carry_over_enabled,
          max_carry_over_days: e.max_carry_over_days,
          carry_over_expiry_months: e.carry_over_expiry_months,
          cash_convertible: e.cash_convertible,
          cash_conversion_rate: e.cash_conversion_rate,
          requires_documentation: e.requires_documentation,
          min_notice_days: e.min_notice_days,
          max_consecutive_days: e.max_consecutive_days ?? null,
        }
      }),
      shared_annual_credits: existing.shared_annual_credits ?? 0,
      shared_carry_over_enabled: existing.shared_carry_over_enabled,
      shared_max_carry_over_days: existing.shared_max_carry_over_days,
      shared_carry_over_expiry_months: existing.shared_carry_over_expiry_months,
      shared_cash_convertible: existing.shared_cash_convertible,
      shared_cash_conversion_rate: existing.shared_cash_conversion_rate,
      shared_max_consecutive_days: existing.shared_max_consecutive_days ?? null,
    }
  }
  return {
    name: '',
    description: '',
    pool_type: 'per_type',
    accrual_method: 'annual',
    is_default: false,
    employment_types: [],
    approval_mode: 'auto',
    // Default new policies to warn — safer than silent, less strict than block.
    enforcement: {
      insufficient_balance: 'warn',
      min_notice_days: 'warn',
      max_consecutive_days: 'off',
      overlapping_application: 'warn',
      requires_documentation: 'warn',
    },
    entitlements: leaveTypes.map(blankEntitlement),
    shared_annual_credits: 15,
    shared_carry_over_enabled: false,
    shared_max_carry_over_days: 0,
    shared_carry_over_expiry_months: 0,
    shared_cash_convertible: false,
    shared_cash_conversion_rate: 1,
    shared_max_consecutive_days: null,
  }
}

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  policy?: LeavePolicy | null // null/undefined = create
}

export default function PolicyWizard({ open, onOpenChange, policy }: Props) {
  const qc = useQueryClient()
  const { showToast } = useToast()
  const wiz = useWizard(STEPS.length)
  const [state, setState] = useState<WizardState | null>(null)
  const [errors, setErrors] = useState<Record<string, string>>({})

  const { data: leaveTypes } = useQuery<LeaveTypeConfig[]>({
    queryKey: ['leave-types'],
    queryFn: () => api.getLeaveTypes(),
  })
  const { data: employeeTypes } = useQuery<EmployeeTypeConfig[]>({
    queryKey: ['employee-types'],
    queryFn: () => api.getEmployeeTypes(),
  })

  const activeLeaveTypes = useMemo(
    () => (leaveTypes ?? []).filter((lt) => lt.is_active),
    [leaveTypes]
  )

  // Initialize state when the modal opens and leave types are available.
  useEffect(() => {
    if (open && activeLeaveTypes.length) {
      setState(initialState(activeLeaveTypes, policy))
      wiz.goTo(0)
      setErrors({})
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, policy, activeLeaveTypes.length])

  const patch = (p: Partial<WizardState>) => setState((s) => (s ? { ...s, ...p } : s))
  const patchEnt = (idx: number, p: Partial<EntitlementDraft>) =>
    setState((s) =>
      s
        ? {
            ...s,
            entitlements: s.entitlements.map((e, i) => (i === idx ? { ...e, ...p } : e)),
          }
        : s
    )

  const buildPayload = (s: WizardState) => {
    const base = {
      name: s.name,
      description: s.description || null,
      pool_type: s.pool_type,
      accrual_method: s.accrual_method,
      is_default: s.is_default,
      employment_types: s.employment_types,
      approval_mode: s.approval_mode,
      enforcement: s.enforcement,
    }
    if (s.pool_type === 'shared') {
      return {
        ...base,
        shared_annual_credits: s.shared_annual_credits,
        shared_carry_over_enabled: s.shared_carry_over_enabled,
        shared_max_carry_over_days: s.shared_max_carry_over_days,
        shared_carry_over_expiry_months: s.shared_carry_over_expiry_months,
        shared_cash_convertible: s.shared_cash_convertible,
        shared_cash_conversion_rate: s.shared_cash_conversion_rate,
        shared_max_consecutive_days: s.shared_max_consecutive_days,
      }
    }
    return {
      ...base,
      entitlements: s.entitlements
        .filter((e) => e.enabled)
        .map((e) => ({
          leave_type_id: e.leave_type_id,
          annual_credits: e.annual_credits,
          carry_over_enabled: e.carry_over_enabled,
          max_carry_over_days: e.max_carry_over_days,
          carry_over_expiry_months: e.carry_over_expiry_months,
          cash_convertible: e.cash_convertible,
          cash_conversion_rate: e.cash_conversion_rate,
          requires_documentation: e.requires_documentation,
          min_notice_days: e.min_notice_days,
          max_consecutive_days: e.max_consecutive_days,
        })),
    }
  }

  const save = useMutation({
    mutationFn: async (s: WizardState) => {
      const payload = buildPayload(s)
      if (policy) {
        await api.updateLeavePolicy(policy.id, payload)
        // Editing entitlements: replace them wholesale for per_type.
        if (s.pool_type === 'per_type') {
          await api.bulkReplacePolicyEntitlements(
            policy.id,
            s.entitlements
              .filter((e) => e.enabled)
              .map((e) => ({
                leave_type_id: e.leave_type_id,
                annual_credits: e.annual_credits,
                carry_over_enabled: e.carry_over_enabled,
                max_carry_over_days: e.max_carry_over_days,
                carry_over_expiry_months: e.carry_over_expiry_months,
                cash_convertible: e.cash_convertible,
                cash_conversion_rate: e.cash_conversion_rate,
                requires_documentation: e.requires_documentation,
                min_notice_days: e.min_notice_days,
                max_consecutive_days: e.max_consecutive_days,
              }))
          )
        }
      } else {
        await api.createLeavePolicy(payload)
      }
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['leave-policies'] })
      showToast(policy ? 'Policy updated' : 'Policy created', 'success')
      onOpenChange(false)
    },
    onError: (e: unknown) => showToast((e as Error)?.message ?? 'Save failed', 'error'),
  })

  if (!state) return null

  const validateStep = (): boolean => {
    if (wiz.current === 0) {
      const r = coverageSchema.safeParse(state)
      if (!r.success) {
        const errs: Record<string, string> = {}
        r.error.issues.forEach((i) => (errs[String(i.path[0])] = i.message))
        setErrors(errs)
        return false
      }
    }
    if (wiz.current === 1 && state.pool_type === 'per_type') {
      if (!state.entitlements.some((e) => e.enabled && e.annual_credits > 0)) {
        setErrors({ entitlements: 'Enable at least one leave type with credits.' })
        return false
      }
    }
    setErrors({})
    return true
  }

  const onNext = () => {
    if (validateStep()) wiz.next()
  }

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title={policy ? `Edit policy: ${policy.name}` : 'New leave policy'}
      size="xl"
      footer={
        <div className="flex w-full items-center justify-between">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <div className="flex gap-2">
            {!wiz.isFirst && (
              <Button variant="secondary" onClick={wiz.back}>
                Back
              </Button>
            )}
            {!wiz.isLast ? (
              <Button onClick={onNext}>Next</Button>
            ) : (
              <Button loading={save.isPending} onClick={() => save.mutate(state)}>
                {policy ? 'Save changes' : 'Create policy'}
              </Button>
            )}
          </div>
        </div>
      }
    >
      <div className="mb-6">
        <WizardProgress steps={STEPS} current={wiz.current} onStepClick={wiz.goTo} maxReached={wiz.maxReached} />
      </div>

      {/* ── Step 1: Coverage ── */}
      {wiz.current === 0 && (
        <div className="space-y-5">
          <FormField label="Policy name" required error={errors.name}>
            <Input
              value={state.name}
              invalid={!!errors.name}
              onChange={(e) => patch({ name: e.target.value })}
              placeholder="e.g. Standard Full-Time"
            />
          </FormField>
          <FormField label="Description" help="Optional. A short note for other admins.">
            <Input
              value={state.description}
              onChange={(e) => patch({ description: e.target.value })}
            />
          </FormField>

          <FormField label="Who does this policy cover?" help="Leave empty to make it the fallback for everyone.">
            <div className="flex flex-wrap gap-2">
              {(employeeTypes ?? [])
                .filter((t) => t.is_active)
                .map((t) => {
                  const on = state.employment_types.includes(t.code)
                  return (
                    <button
                      key={t.code}
                      type="button"
                      onClick={() =>
                        patch({
                          employment_types: on
                            ? state.employment_types.filter((c) => c !== t.code)
                            : [...state.employment_types, t.code],
                        })
                      }
                      className={
                        'rounded-full border px-3 py-1 text-sm ' +
                        (on
                          ? 'border-purple-600 bg-purple-50 text-purple-700'
                          : 'border-gray-300 text-gray-600 hover:bg-gray-50')
                      }
                    >
                      {t.name}
                    </button>
                  )
                })}
            </div>
          </FormField>

          <FormField label="How are balances organized?">
            <div className="grid gap-2 sm:grid-cols-2">
              {(['per_type', 'shared'] as const).map((pt) => (
                <button
                  key={pt}
                  type="button"
                  onClick={() => patch({ pool_type: pt })}
                  className={
                    'rounded-lg border p-3 text-left ' +
                    (state.pool_type === pt
                      ? 'border-purple-600 ring-1 ring-purple-600'
                      : 'border-gray-300 hover:bg-gray-50')
                  }
                >
                  <div className="text-sm font-medium text-gray-900">{POOL_TYPE[pt].label}</div>
                  <div className="mt-1 text-xs text-gray-500">{POOL_TYPE[pt].description}</div>
                </button>
              ))}
            </div>
          </FormField>

          <FormField label="When do credits become available?">
            <div className="grid gap-2 sm:grid-cols-2">
              {(['annual', 'monthly'] as const).map((am) => (
                <button
                  key={am}
                  type="button"
                  onClick={() => patch({ accrual_method: am })}
                  className={
                    'rounded-lg border p-3 text-left ' +
                    (state.accrual_method === am
                      ? 'border-purple-600 ring-1 ring-purple-600'
                      : 'border-gray-300 hover:bg-gray-50')
                  }
                >
                  <div className="text-sm font-medium text-gray-900">{ACCRUAL_METHOD[am].label}</div>
                  <div className="mt-1 text-xs text-gray-500">{ACCRUAL_METHOD[am].description}</div>
                </button>
              ))}
            </div>
          </FormField>

          <label className="flex items-center gap-3">
            <Switch checked={state.is_default} onChange={(v) => patch({ is_default: v })} />
            <span className="text-sm text-gray-700">
              Make this the default policy (used when no other policy matches)
            </span>
          </label>
        </div>
      )}

      {/* ── Step 2: Leave & Credits ── */}
      {wiz.current === 1 && (
        <div className="space-y-4">
          {state.pool_type === 'shared' ? (
            <FormField label="Total shared days per year" error={errors.entitlements}>
              <Input
                type="number"
                min={0}
                value={state.shared_annual_credits}
                onChange={(e) => patch({ shared_annual_credits: Number(e.target.value) })}
              />
            </FormField>
          ) : (
            <>
              {errors.entitlements && (
                <p className="text-sm text-red-600">{errors.entitlements}</p>
              )}
              <p className="text-sm text-gray-500">
                Turn on the leave types this policy grants and set the yearly days.
              </p>
              <div className="divide-y divide-gray-100 rounded-lg border border-gray-200">
                {state.entitlements.map((e, idx) => (
                  <div key={e.leave_type_id} className="flex items-center gap-4 px-4 py-3">
                    <Switch checked={e.enabled} onChange={(v) => patchEnt(idx, { enabled: v })} />
                    <div className="flex-1">
                      <div className="text-sm font-medium text-gray-900">{e.leave_type_name}</div>
                      <div className="text-xs text-gray-400">{e.leave_type_code}</div>
                    </div>
                    {e.enabled && (
                      <div className="flex items-center gap-2">
                        <Input
                          type="number"
                          min={0}
                          className="w-24"
                          value={e.annual_credits}
                          onChange={(ev) =>
                            patchEnt(idx, { annual_credits: Number(ev.target.value) })
                          }
                        />
                        <span className="text-sm text-gray-500">days/yr</span>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      )}

      {/* ── Step 3: Carry-over & Cash ── */}
      {wiz.current === 2 && (
        <div className="space-y-4">
          {state.pool_type === 'shared' ? (
            <SharedCarryOver state={state} patch={patch} />
          ) : (
            <div className="space-y-3">
              {state.entitlements.filter((e) => e.enabled).length === 0 && (
                <p className="text-sm text-gray-500">
                  No leave types enabled — go back to step 2 to add some.
                </p>
              )}
              {state.entitlements.map((e, idx) =>
                e.enabled ? (
                  <div key={e.leave_type_id} className="rounded-lg border border-gray-200 p-4">
                    <div className="mb-3 flex items-center justify-between">
                      <div className="text-sm font-medium text-gray-900">{e.leave_type_name}</div>
                      {e.carry_over_enabled && e.max_carry_over_days > 0 && (
                        <Badge tone="blue">
                          {`Up to ${e.max_carry_over_days} day(s) carry over`}
                          {e.carry_over_expiry_months
                            ? `, expire after ${e.carry_over_expiry_months}mo`
                            : ''}
                        </Badge>
                      )}
                    </div>
                    <div className="grid gap-3 sm:grid-cols-2">
                      <label className="flex items-center gap-2 text-sm">
                        <Switch
                          checked={e.carry_over_enabled}
                          onChange={(v) => patchEnt(idx, { carry_over_enabled: v })}
                        />
                        Allow carry-over to next year
                      </label>
                      {e.carry_over_enabled && (
                        <>
                          <FormField label="Max days carried">
                            <Input
                              type="number"
                              min={0}
                              value={e.max_carry_over_days}
                              onChange={(ev) =>
                                patchEnt(idx, { max_carry_over_days: Number(ev.target.value) })
                              }
                            />
                          </FormField>
                          <FormField label="Carried days expire after (months, 0 = never)">
                            <Input
                              type="number"
                              min={0}
                              value={e.carry_over_expiry_months}
                              onChange={(ev) =>
                                patchEnt(idx, {
                                  carry_over_expiry_months: Number(ev.target.value),
                                })
                              }
                            />
                          </FormField>
                        </>
                      )}
                      <label className="flex items-center gap-2 text-sm">
                        <Switch
                          checked={e.cash_convertible}
                          onChange={(v) => patchEnt(idx, { cash_convertible: v })}
                        />
                        Convert forfeited days to a computed cash line
                      </label>
                      {e.cash_convertible && (
                        <FormField label="Conversion rate (× daily rate)">
                          <Input
                            type="number"
                            min={0}
                            step={0.1}
                            value={e.cash_conversion_rate}
                            onChange={(ev) =>
                              patchEnt(idx, { cash_conversion_rate: Number(ev.target.value) })
                            }
                          />
                        </FormField>
                      )}
                      <FormField label="Requires a document">
                        <Switch
                          checked={e.requires_documentation}
                          onChange={(v) => patchEnt(idx, { requires_documentation: v })}
                        />
                      </FormField>
                      <FormField label="Min notice (days)">
                        <Input
                          type="number"
                          min={0}
                          value={e.min_notice_days}
                          onChange={(ev) =>
                            patchEnt(idx, { min_notice_days: Number(ev.target.value) })
                          }
                        />
                      </FormField>
                      <FormField label="Max consecutive days (blank = no limit)">
                        <Input
                          type="number"
                          min={0}
                          value={e.max_consecutive_days ?? ''}
                          onChange={(ev) =>
                            patchEnt(idx, {
                              max_consecutive_days:
                                ev.target.value === '' ? null : Number(ev.target.value),
                            })
                          }
                        />
                      </FormField>
                    </div>
                  </div>
                ) : null
              )}
            </div>
          )}
        </div>
      )}

      {/* ── Step 4: Approvals & Enforcement ── */}
      {wiz.current === 3 && (
        <div className="space-y-6">
          <FormField label="How should requests be approved?">
            <div className="grid gap-2">
              {(['auto', 'hybrid', 'manual'] as const).map((am) => (
                <button
                  key={am}
                  type="button"
                  onClick={() => patch({ approval_mode: am })}
                  className={
                    'rounded-lg border p-3 text-left ' +
                    (state.approval_mode === am
                      ? 'border-purple-600 ring-1 ring-purple-600'
                      : 'border-gray-300 hover:bg-gray-50')
                  }
                >
                  <div className="text-sm font-medium text-gray-900">{APPROVAL_MODE[am].label}</div>
                  <div className="mt-1 text-xs text-gray-500">{APPROVAL_MODE[am].description}</div>
                </button>
              ))}
            </div>
          </FormField>

          <div>
            <div className="mb-2 text-sm font-medium text-gray-700">When a request breaks a rule…</div>
            <div className="space-y-2">
              {ENFORCEMENT_RULES.map((rule) => (
                <div
                  key={rule.key}
                  className="flex items-center justify-between gap-3 rounded-lg border border-gray-200 px-3 py-2"
                >
                  <div>
                    <div className="text-sm font-medium text-gray-800">{rule.label}</div>
                    <div className="text-xs text-gray-500">{rule.consequence}</div>
                  </div>
                  <SegmentedControl<EnforcementMode>
                    value={(state.enforcement[rule.key] ?? 'off') as EnforcementMode}
                    onChange={(v) =>
                      patch({ enforcement: { ...state.enforcement, [rule.key]: v } })
                    }
                    options={[
                      { value: 'block', label: ENFORCEMENT_MODE_COPY.block.label, description: ENFORCEMENT_MODE_COPY.block.description },
                      { value: 'warn', label: ENFORCEMENT_MODE_COPY.warn.label, description: ENFORCEMENT_MODE_COPY.warn.description },
                      { value: 'off', label: ENFORCEMENT_MODE_COPY.off.label, description: ENFORCEMENT_MODE_COPY.off.description },
                    ]}
                  />
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </Modal>
  )
}

function SharedCarryOver({
  state,
  patch,
}: {
  state: WizardState
  patch: (p: Partial<WizardState>) => void
}) {
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <label className="flex items-center gap-2 text-sm sm:col-span-2">
        <Switch
          checked={state.shared_carry_over_enabled}
          onChange={(v) => patch({ shared_carry_over_enabled: v })}
        />
        Allow carry-over to next year
      </label>
      {state.shared_carry_over_enabled && (
        <>
          <FormField label="Max days carried">
            <Input
              type="number"
              min={0}
              value={state.shared_max_carry_over_days}
              onChange={(e) => patch({ shared_max_carry_over_days: Number(e.target.value) })}
            />
          </FormField>
          <FormField label="Expire after (months, 0 = never)">
            <Input
              type="number"
              min={0}
              value={state.shared_carry_over_expiry_months}
              onChange={(e) =>
                patch({ shared_carry_over_expiry_months: Number(e.target.value) })
              }
            />
          </FormField>
        </>
      )}
      <label className="flex items-center gap-2 text-sm sm:col-span-2">
        <Switch
          checked={state.shared_cash_convertible}
          onChange={(v) => patch({ shared_cash_convertible: v })}
        />
        Convert forfeited days to a computed cash line
      </label>
      {state.shared_cash_convertible && (
        <FormField label="Conversion rate (× daily rate)">
          <Input
            type="number"
            min={0}
            step={0.1}
            value={state.shared_cash_conversion_rate}
            onChange={(e) => patch({ shared_cash_conversion_rate: Number(e.target.value) })}
          />
        </FormField>
      )}
      <FormField label="Max consecutive days (blank = no limit)">
        <Input
          type="number"
          min={0}
          value={state.shared_max_consecutive_days ?? ''}
          onChange={(e) =>
            patch({
              shared_max_consecutive_days:
                e.target.value === '' ? null : Number(e.target.value),
            })
          }
        />
      </FormField>
    </div>
  )
}
