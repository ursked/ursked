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
    description: "Requests route up the employee's reporting line automatically.",
  },
  manual: {
    label: 'Use custom rules',
    description: 'Requests route according to the approval rules you define.',
  },
  hybrid: {
    label: 'Custom rules, org chart as fallback',
    description: 'Try your custom rules first; fall back to the org chart if none match.',
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
  auto: 'From org chart',
  manual: 'From a custom rule',
  hybrid: 'From custom rules',
}
