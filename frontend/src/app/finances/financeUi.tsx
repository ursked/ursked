'use client'

import { useState, type ReactNode } from 'react'
import Link from 'next/link'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from '@/lib/api'
import { useToast } from '@/components/ui/Toast'

// Shared bits for the Finances tabs.
//
// Every tab used to treat a failed load as an empty list, so someone without
// salary access was told "No payroll periods yet. Create one to get started."
// and did exactly that, creating duplicate periods. A 403 now says what is
// missing and how to get it.

export function isForbidden(err: unknown): boolean {
  return err instanceof ApiError && err.status === 403
}

function needsSalaryAccess(err: unknown): boolean {
  if (!(err instanceof ApiError)) return false
  return err.status === 403 && /salary access|enrollment/i.test(err.message)
}

/** The message to show instead of a list that failed to load. */
export function LoadProblem({ error, what }: { error: unknown; what: string }) {
  if (needsSalaryAccess(error)) {
    return (
      <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
        <p className="font-medium">You need salary access to see {what}.</p>
        <p className="mt-1">
          Salary figures are shown only to people with an approved salary-viewer enrollment, whatever their role.{' '}
          <Link href="/salary-access" className="font-semibold text-brand-700 underline">
            Request salary access
          </Link>
        </p>
      </div>
    )
  }
  if (isForbidden(error)) {
    return (
      <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
        You do not have permission to see {what}. Ask an administrator to give your role access on the Permissions screen.
      </div>
    )
  }
  return (
    <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">
      Could not load {what}: {error instanceof Error ? error.message : 'something went wrong'}. Try again in a moment.
    </div>
  )
}

// ── Salary figures ────────────────────────────────────────────────────
//
// Finances has two audiences. Anyone whose role has finances:view sees the
// structure (deduction types, payout schedules, grade names, the period
// calendar). Figures (rates, salaries, bonuses, payroll results) are shown
// only to someone another person has approved for salary access, whatever
// their role: an administrator included, on the owner's decision. These
// mirror the API's require_salary_access(), so a non-viewer gets a way to ask
// instead of a screen full of failed requests.

/** The caller's own salary access, from the same query every tab shares. */
export function useSalaryAccess() {
  const q = useQuery({ queryKey: ['my-salary-status'], queryFn: () => api.getMySalaryStatus() })
  return {
    loading: q.isLoading,
    isViewer: q.data?.is_viewer ?? false,
    isApprover: q.data?.is_approver ?? false,
    pendingViewerId: (q.data?.pending_requests ?? []).find((r) => r.kind === 'viewer')?.id ?? null,
    canSelfApprove: q.data?.can_self_approve ?? false,
  }
}

/** When nobody else could approve the caller's salary access (a new install,
 *  or a company whose only approver is its administrator), they may approve
 *  it themselves with a written reason. Files the request first if there is
 *  none, then approves it. The API records it as self-approved and tells every
 *  administrator and every approver appointed later. */
export function SelfApprove({ pendingId, compact = false }: { pendingId: number | null; compact?: boolean }) {
  const { showToast } = useToast()
  const queryClient = useQueryClient()
  const [reason, setReason] = useState('')
  const ok = reason.trim().length >= 10

  const mut = useMutation({
    mutationFn: async () => {
      const id = pendingId ?? (await api.createSalaryRequest({ kind: 'viewer', reason: reason.trim() })).id
      return api.approveSalaryRequest(id, reason.trim())
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['my-salary-status'] })
      queryClient.invalidateQueries({ queryKey: ['salary-requests'] })
      queryClient.invalidateQueries({ queryKey: ['salary-enrollments'] })
      queryClient.invalidateQueries({ queryKey: ['salary-grant-history'] })
      showToast('You now have salary access. Every administrator has been told.', 'success')
    },
    onError: (e: Error) => {
      queryClient.invalidateQueries({ queryKey: ['my-salary-status'] })
      showToast(e.message, 'error')
    },
  })

  return (
    <div className={`rounded-md border border-amber-200 bg-amber-50 text-left ${compact ? 'mt-2 w-full p-3' : 'mt-4 p-4'}`}>
      <p className="text-sm font-medium text-amber-900">Nobody else can approve this yet</p>
      <p className="mt-1 text-xs text-amber-800">
        You are the only approver who could decide it. You may approve your own access: write why.
        It is recorded as self-approved, every administrator is told, and anyone who becomes an
        approver later is told and can revoke it.
      </p>
      <label htmlFor="self-approve-reason" className="sr-only">Why you are approving your own access</label>
      <textarea
        id="self-approve-reason"
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        rows={2}
        placeholder="e.g. I am the owner and run payroll myself; there is no one else yet."
        className="mt-2 w-full rounded-md border border-amber-300 bg-white px-3 py-2 text-sm"
      />
      <button
        onClick={() => mut.mutate()}
        disabled={!ok || mut.isPending}
        className="mt-2 w-full rounded-md bg-amber-600 px-4 py-2 text-sm font-semibold text-white hover:bg-amber-700 disabled:opacity-50"
      >
        Approve my own salary access
      </button>
      {!ok && reason.length > 0 && <p className="mt-1 text-xs text-amber-800">At least 10 characters.</p>}
    </div>
  )
}

/** Renders its children for a salary viewer and the request prompt for anyone else. */
export function FiguresOnly({ what, children }: { what: string; children: ReactNode }) {
  const { loading, isViewer, pendingViewerId, canSelfApprove } = useSalaryAccess()
  if (loading) return <p className="py-8 text-center text-sm text-gray-500">Loading…</p>
  if (!isViewer) return <SalaryAccessGate what={what} pendingId={pendingViewerId} canSelfApprove={canSelfApprove} />
  return <>{children}</>
}

/** Shown where figures would be, to someone who is not a salary viewer. Lets
 *  them file a request (or withdraw one) without leaving the page; another
 *  approver must approve it before any figure appears. */
export function SalaryAccessGate({ what, pendingId, canSelfApprove = false }: {
  what: string; pendingId: number | null; canSelfApprove?: boolean
}) {
  const { showToast } = useToast()
  const queryClient = useQueryClient()
  const [reason, setReason] = useState('')
  const hasPending = pendingId != null

  const cancelMut = useMutation({
    mutationFn: () => api.cancelSalaryRequest(pendingId as number),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['my-salary-status'] })
      showToast('Request withdrawn', 'success')
    },
    onError: (e: Error) => showToast(e.message, 'error'),
  })

  const requestMut = useMutation({
    mutationFn: () => api.createSalaryRequest({ kind: 'viewer', reason: reason || undefined }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['my-salary-status'] })
      showToast('Request submitted for approval', 'success')
    },
    onError: (e: Error) => showToast(e.message, 'error'),
  })

  return (
    <div className="mx-auto max-w-lg rounded-lg border border-gray-200 bg-white p-6 text-center">
      <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-amber-100">
        <svg className="h-6 w-6 text-amber-600" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 10-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 002.25-2.25v-6.75a2.25 2.25 0 00-2.25-2.25H6.75a2.25 2.25 0 00-2.25 2.25v6.75a2.25 2.25 0 002.25 2.25z" />
        </svg>
      </div>
      <h3 className="mt-4 text-base font-semibold text-gray-900">You need salary access to see {what}</h3>
      <p className="mt-2 text-sm text-gray-500">
        Salary figures are confidential. They are shown only to people another person has approved for
        salary access, whatever their role, administrators included. Request it below.
      </p>
      {canSelfApprove ? (
        <SelfApprove pendingId={pendingId} />
      ) : hasPending ? (
        <div className="mt-4 space-y-2">
          <p className="text-sm font-medium text-amber-600">Your request is waiting for another approver.</p>
          <button
            onClick={() => cancelMut.mutate()}
            disabled={cancelMut.isPending}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
          >
            Withdraw request
          </button>
        </div>
      ) : (
        <div className="mt-4 space-y-2">
          <label htmlFor="salary-access-reason" className="sr-only">Reason</label>
          <input
            id="salary-access-reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Reason (optional)"
            className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
          />
          <button
            onClick={() => requestMut.mutate()}
            disabled={requestMut.isPending}
            className="w-full rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-50"
          >
            Request salary access
          </button>
        </div>
      )}
    </div>
  )
}
