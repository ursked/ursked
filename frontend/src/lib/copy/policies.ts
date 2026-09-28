/**
 * Plain-language copy for leave-policy configuration. The database uses terse
 * enum codes (per_type, hybrid, cascade…); this dictionary turns them into
 * language an HR admin actually understands. Shared by the wizard and the
 * advanced table view so both stay consistent.
 */
import type { EnforcementRule } from '@/types'

export const POOL_TYPE = {
  per_type: {
    label: 'Separate balance per leave type',
    description: 'Each leave type (Vacation, Sick, …) has its own day count.',
  },
  shared: {
    label: 'One shared balance for everything',
    description: 'A single pool of days is drawn down by any leave type.',
  },
} as const

export const ACCRUAL_METHOD = {
  annual: {
    label: 'All credits available on Jan 1',
    description: 'Employees receive the full yearly allowance at the start of the year.',
  },
  monthly: {
    label: 'Earned monthly',
    description: 'Employees accrue 1/12 of the yearly allowance each month.',
  },
} as const

export const APPROVAL_MODE = {
  auto: {
    label: 'Use the org chart',
    description: "The head of the employee's unit approves, then the head of each unit above, up to the number of levels you set.",
  },
  manual: {
    label: 'Use custom rules',
    description: 'The approval rule that applies to the employee decides who approves, in the order the rule lists them.',
  },
  hybrid: {
    label: 'Custom rules, then the org chart',
    description: "The rule's approvers go first; unit heads from the org chart follow, up to the number of levels you set.",
  },
} as const

export const ENFORCEMENT_RULES: {
  key: EnforcementRule
  label: string
  consequence: string
}[] = [
  {
    key: 'insufficient_balance',
    label: 'Not enough balance',
    consequence: 'Filing more days than available.',
  },
  {
    key: 'min_notice_days',
    label: 'Too little notice',
    consequence: 'Filing with less advance notice than required.',
  },
  {
    key: 'max_consecutive_days',
    label: 'Too many consecutive days',
    consequence: 'A single request longer than the allowed maximum.',
  },
  {
    key: 'overlapping_application',
    label: 'Overlapping request',
    consequence: 'Dates overlap another pending or approved request.',
  },
  {
    key: 'requires_documentation',
    label: 'Missing documentation',
    consequence: 'No supporting document attached where one is required.',
  },
]

export const ENFORCEMENT_MODE_COPY = {
  block: { label: 'Block', description: 'Reject the request outright.' },
  warn: { label: 'Warn', description: 'Allow, but flag it for approvers.' },
  off: { label: 'Off', description: 'Do not check this rule.' },
} as const

export const CHAIN_SOURCE_LABEL: Record<string, string> = {
  auto: 'Unit head (org chart)',
  hybrid_org_chart: 'Unit head (org chart)',
  manual: 'From a custom rule',
  manual_employee: 'Rule for this employee',
  manual_org_node: 'Rule for their unit',
  manual_cascade: 'Rule for a unit above',
  manual_default: 'Default rule',
  hybrid: 'From custom rules',
  fallback_manager: 'Line manager (no other approver)',
  fallback_tenant_admin: 'Administrator (no other approver)',
  fallback_hr: 'HR (no other approver)',
  fallback_leave_editor: 'Leave administrator (no other approver)',
  self_approval: 'Self-approval: nobody else can approve',
}
