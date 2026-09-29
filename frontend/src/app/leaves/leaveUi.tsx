'use client'

// Pieces shared by the leave screens (My Leave, Approvals, Team Overview and
// /my/leave) so a request reads the same wherever it is shown: its status, its
// approval steps, what happened to it, and why the rules objected.

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ApiError, api } from '@/lib/api'
import type {
  ApproverCheck,
  LeaveApplication,
  LeaveApprovalEvent,
  LeaveDayBreakdownItem,
  LeaveRuleViolation,
} from '@/types'

export const STATUS_COLORS: Record<string, string> = {
  pending: 'bg-yellow-100 text-yellow-800',
  approved: 'bg-green-100 text-green-800',
  rejected: 'bg-red-100 text-red-800',
  cancelled: 'bg-gray-100 text-gray-600',
  expired: 'bg-gray-100 text-gray-600',
}

export const STATUS_FILTERS = ['all', 'pending', 'approved', 'rejected', 'cancelled', 'expired'] as const

export function typeLabel(app: Pick<LeaveApplication, 'leave_type' | 'leave_type_name'>): string {
  return app.leave_type_name || app.leave_type.replace(/_/g, ' ')
}

export function daysLabel(app: Pick<LeaveApplication, 'days_requested' | 'half_day'>): string {
  const d = app.days_requested
  const half = app.half_day ? ` (${app.half_day.toUpperCase()})` : ''
  return `${d} day${d === 1 ? '' : 's'}${half}`
}

/** The violation list a 422 from filing carries, so the form can show each as
 * a bullet instead of a paragraph (or, before 2026-09, raw JSON). */
export function errorViolations(err: unknown): LeaveRuleViolation[] {
  if (err instanceof ApiError && err.detail && typeof err.detail === 'object') {
    const v = (err.detail as { violations?: unknown }).violations
    if (Array.isArray(v)) return v as LeaveRuleViolation[]
  }
  return []
}

export function ViolationList({
  items,
  tone,
  title,
}: {
  items: LeaveRuleViolation[] | null | undefined
  tone: 'block' | 'warn'
  title?: string
}) {
  if (!items || items.length === 0) return null
  const box = tone === 'block' ? 'bg-red-50 border-red-200 text-red-800' : 'bg-amber-50 border-amber-200 text-amber-900'
  return (
    <div className={`rounded-lg border px-3 py-2 text-sm ${box}`} role={tone === 'block' ? 'alert' : 'status'}>
      {title && <p className="font-medium mb-1">{title}</p>}
      <ul className="list-disc space-y-0.5 pl-5">
        {items.map((v, i) => (
          <li key={`${v.rule}-${i}`}>{v.message}</li>
        ))}
      </ul>
    </div>
  )
}

const STEP_DOT: Record<string, string> = {
  approved: 'bg-green-500',
  rejected: 'bg-red-500',
  skipped: 'bg-gray-300',
  pending: 'bg-yellow-400',
}

export function StepDots({ app }: { app: LeaveApplication }) {
  const steps = app.approval_steps ?? []
  if (steps.length === 0) return <span className="text-xs text-gray-500">--</span>
  const approved = steps.filter((s) => s.status === 'approved').length
  return (
    <div className="flex items-center gap-1">
      {steps.map((step) => (
        <div
          key={step.id}
          title={`Step ${step.step_order}: ${step.is_self ? 'You (self-approval)' : step.approver_name} - ${step.status}`}
          className={`h-2.5 w-2.5 rounded-full ${STEP_DOT[step.status as string] ?? 'bg-yellow-400'}`}
        />
      ))}
      <span className="ml-1 text-xs text-gray-500">
        {approved}/{steps.length}
      </span>
    </div>
  )
}

const EVENT_LABEL: Record<string, string> = {
  override_approve: 'approved it on the approver’s behalf',
  override_reject: 'rejected it on the approver’s behalf',
  override_revoke: 'reversed the approval',
  reassign: 'reassigned the approver',
  auto_reassign: 'reassigned the approver',
  escalate: 'escalated it',
  self_approve: 'self-approved it (no other approver exists)',
  reminder: 'sent a reminder',
  expire: 'marked it expired',
  steps_reset: 'reset the approvals after a change',
}

function eventText(e: LeaveApprovalEvent): string {
  const who = e.actor_name || 'The system'
  let text = `${who} ${EVENT_LABEL[e.action] ?? e.action.replace(/_/g, ' ')}`
  if (e.to_approver_name) {
    text += e.from_approver_name ? ` from ${e.from_approver_name} to ${e.to_approver_name}` : ` to ${e.to_approver_name}`
  }
  return text
}

export function EventList({ events }: { events?: LeaveApprovalEvent[] }) {
  const shown = (events ?? []).filter((e) => e.action !== 'reminder')
  if (shown.length === 0) return null
  return (
    <div className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-2">
      <p className="text-xs font-semibold text-gray-700 mb-1">History</p>
      <ul className="space-y-1">
        {shown.map((e) => (
          <li key={e.id} className="text-xs text-gray-700">
            <span className="text-gray-500">{e.created_at ? new Date(e.created_at).toLocaleString() : ''} </span>
            {eventText(e)}
            {e.reason ? <span className="text-gray-600">. Reason: {e.reason}</span> : null}
          </li>
        ))}
      </ul>
    </div>
  )
}

export function DayBreakdown({ items, total }: { items: LeaveDayBreakdownItem[]; total?: number }) {
  const [open, setOpen] = useState(items.length <= 7)
  if (items.length === 0) return null
  return (
    <div className="rounded-lg border border-gray-200 px-3 py-2">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between text-left text-sm font-medium text-gray-800"
        aria-expanded={open}
      >
        <span>
          {total !== undefined ? `This request uses ${total} day${total === 1 ? '' : 's'} of leave` : 'Day by day'}
        </span>
        <span className="text-xs text-purple-700">{open ? 'Hide days' : 'Show days'}</span>
      </button>
      {open && (
        <ul className="mt-2 divide-y divide-gray-100">
          {items.map((d) => (
            <li key={d.date} className="flex items-center justify-between py-1 text-xs">
              <span className="text-gray-700">
                {new Date(`${d.date}T00:00:00`).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' })}
                <span className="ml-2 text-gray-500">{d.label}</span>
              </span>
              <span className={d.days ? 'font-medium text-gray-900' : 'text-gray-400'}>
                {d.days ? `${d.days} day` : 'not counted'}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/** "Saving will make X a Leave Approver" / "X is inactive" for a picked user,
 * so the admin knows before saving (the backend does the same check). */
export function useApproverCheck(userId: number | null | undefined) {
  return useQuery<ApproverCheck>({
    queryKey: ['approver-check', userId],
    queryFn: () => api.checkLeaveApprover(userId as number),
    enabled: !!userId,
    staleTime: 30_000,
  })
}

export function ApproverCheckNote({ userId }: { userId: number | null | undefined }) {
  const { data } = useApproverCheck(userId)
  if (!data || !data.message) return null
  const bad = !data.is_active || !data.found
  return (
    <p className={`mt-1 text-xs ${bad ? 'text-red-700' : 'text-amber-800'}`} role={bad ? 'alert' : 'status'}>
      {data.message}
    </p>
  )
}

/** When nobody in the company can approve leave, the approval chain comes back
 *  empty with `nobody_can_approve` and a message saying what to do. Shown in
 *  place of the chain, wherever a chain would be. */
export function NobodyCanApproveNote({ message }: { message?: string | null }) {
  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900" role="status">
      {message || 'Nobody in your company can approve leave yet. An administrator has to give someone the HR or Leave approver role.'}
    </div>
  )
}
