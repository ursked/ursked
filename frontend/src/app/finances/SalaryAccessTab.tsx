'use client'

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { useAuth } from '@/contexts/AuthContext'
import { useToast } from '@/components/ui/Toast'
import type { SalaryEnrollmentRow, SalaryRequestRow } from '@/types'

/** Salary Access enrollment console. Salary visibility is a per-user enrollment
 *  (viewer / approver), independent of role — even a tenant_admin must be an
 *  approved viewer to see salary. A viewer request is approved by a DIFFERENT
 *  approver (no self-approval), and the last approver cannot be removed. */
export default function SalaryAccessTab() {
  const { user } = useAuth()
  const { showToast } = useToast()
  const qc = useQueryClient()
  const myId = user?.id

  const statusQ = useQuery({ queryKey: ['my-salary-status'], queryFn: () => api.getMySalaryStatus() })
  const isApprover = statusQ.data?.is_approver ?? false

  const enrollmentsQ = useQuery({
    queryKey: ['salary-enrollments'],
    queryFn: () => api.getSalaryEnrollments(),
    enabled: isApprover,
  })
  const requestsQ = useQuery({
    queryKey: ['salary-requests', 'pending'],
    queryFn: () => api.getSalaryRequests('pending'),
    enabled: isApprover,
  })

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['salary-enrollments'] })
    qc.invalidateQueries({ queryKey: ['salary-requests', 'pending'] })
    qc.invalidateQueries({ queryKey: ['my-salary-status'] })
    qc.invalidateQueries({ queryKey: ['notifications'] })
  }

  const approveMut = useMutation({
    mutationFn: (id: number) => api.approveSalaryRequest(id),
    onSuccess: () => { invalidate(); showToast('Request approved', 'success') },
    onError: (e: Error) => showToast(e.message, 'error'),
  })
  const declineMut = useMutation({
    mutationFn: (id: number) => api.declineSalaryRequest(id),
    onSuccess: () => { invalidate(); showToast('Request declined', 'success') },
    onError: (e: Error) => showToast(e.message, 'error'),
  })
  const revokeMut = useMutation({
    mutationFn: (v: { userId: number; kind: string }) => api.revokeSalaryEnrollment(v.userId, v.kind),
    onSuccess: () => { invalidate(); showToast('Access revoked', 'success') },
    onError: (e: Error) => showToast(e.message, 'error'),
  })

  const viewers = (enrollmentsQ.data ?? []).filter((e) => e.kind === 'viewer')
  const approvers = (enrollmentsQ.data ?? []).filter((e) => e.kind === 'approver')

  return (
    <div className="space-y-6">
      <div className="rounded-lg border border-gray-200 bg-white p-4">
        <h3 className="text-sm font-semibold text-gray-900">Salary Access</h3>
        <p className="mt-0.5 text-xs text-gray-500">
          Salary visibility is granted per user — being an admin, HR or Finance is not enough.
          A request must be approved by a different approver, and the last approver can&apos;t be removed.
        </p>
        <MyStatus />
      </div>

      {isApprover && (
        <>
          <RequestsCard
            requests={requestsQ.data ?? []}
            myId={myId}
            loading={requestsQ.isLoading}
            onApprove={(id) => approveMut.mutate(id)}
            onDecline={(id) => declineMut.mutate(id)}
            busy={approveMut.isPending || declineMut.isPending}
          />
          <EnrollmentCard
            title="Salary Viewers"
            subtitle="Users who can see salary and payroll figures."
            rows={viewers}
            approverCount={approvers.length}
            loading={enrollmentsQ.isLoading}
            onRevoke={(userId, kind) => revokeMut.mutate({ userId, kind })}
            busy={revokeMut.isPending}
          />
          <EnrollmentCard
            title="Enrollment Approvers"
            subtitle="Users who can approve or decline access requests."
            rows={approvers}
            approverCount={approvers.length}
            loading={enrollmentsQ.isLoading}
            onRevoke={(userId, kind) => revokeMut.mutate({ userId, kind })}
            busy={revokeMut.isPending}
          />
        </>
      )}
    </div>
  )
}

function MyStatus() {
  const { showToast } = useToast()
  const qc = useQueryClient()
  const statusQ = useQuery({ queryKey: ['my-salary-status'], queryFn: () => api.getMySalaryStatus() })
  const [reason, setReason] = useState('')
  const [open, setOpen] = useState(false)

  const requestMut = useMutation({
    mutationFn: (kind: string) => api.createSalaryRequest({ kind, reason: reason || undefined }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['my-salary-status'] })
      qc.invalidateQueries({ queryKey: ['salary-requests', 'pending'] })
      setReason(''); setOpen(false)
      showToast('Request submitted for approval', 'success')
    },
    onError: (e: Error) => showToast(e.message, 'error'),
  })

  const s = statusQ.data
  if (!s) return null

  const pendingViewer = s.pending_kinds.includes('viewer')

  return (
    <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
      <span className={`rounded px-2 py-0.5 font-medium ${s.is_viewer ? 'bg-green-50 text-green-700' : 'bg-gray-100 text-gray-500'}`}>
        {s.is_viewer ? 'You are a Salary Viewer' : 'No salary access'}
      </span>
      {s.is_approver && (
        <span className="rounded bg-purple-50 px-2 py-0.5 font-medium text-purple-700">Approver</span>
      )}
      {!s.is_viewer && !pendingViewer && (
        <button
          onClick={() => setOpen((v) => !v)}
          className="rounded-md bg-purple-600 px-2.5 py-1 font-medium text-white hover:bg-purple-700"
        >
          Request access
        </button>
      )}
      {pendingViewer && <span className="text-amber-600">Request pending approval…</span>}
      {open && (
        <div className="mt-2 flex w-full flex-wrap items-center gap-2">
          <input
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Reason (optional)"
            className="flex-1 rounded-md border border-gray-300 px-2 py-1 text-xs"
          />
          <button
            onClick={() => requestMut.mutate('viewer')}
            disabled={requestMut.isPending}
            className="rounded-md bg-purple-600 px-2.5 py-1 font-medium text-white hover:bg-purple-700 disabled:opacity-50"
          >
            Submit viewer request
          </button>
        </div>
      )}
    </div>
  )
}

function RequestsCard({
  requests, myId, loading, onApprove, onDecline, busy,
}: {
  requests: SalaryRequestRow[]
  myId?: number
  loading: boolean
  onApprove: (id: number) => void
  onDecline: (id: number) => void
  busy: boolean
}) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white">
      <div className="border-b border-gray-100 px-4 py-3">
        <h3 className="text-sm font-semibold text-gray-900">Pending Requests</h3>
        <p className="mt-0.5 text-xs text-gray-500">Approve or decline access requests. You cannot approve your own.</p>
      </div>
      {loading ? (
        <p className="px-4 py-3 text-xs text-gray-400">Loading…</p>
      ) : requests.length === 0 ? (
        <p className="px-4 py-3 text-xs text-gray-400">No pending requests.</p>
      ) : (
        <table className="w-full text-xs">
          <thead className="bg-gray-50 text-gray-500">
            <tr>
              <th className="px-4 py-2 text-left font-medium">User</th>
              <th className="px-4 py-2 text-left font-medium">Kind</th>
              <th className="px-4 py-2 text-left font-medium">Reason</th>
              <th className="px-4 py-2 text-right font-medium">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {requests.map((r) => {
              const own = r.user_id === myId
              return (
                <tr key={r.id}>
                  <td className="px-4 py-2 text-gray-800">{r.user_name}</td>
                  <td className="px-4 py-2 capitalize text-gray-600">{r.kind}</td>
                  <td className="px-4 py-2 text-gray-500">{r.reason || '—'}</td>
                  <td className="px-4 py-2 text-right">
                    {own ? (
                      <span className="text-gray-400">awaiting another approver</span>
                    ) : (
                      <div className="inline-flex gap-2">
                        <button
                          onClick={() => onApprove(r.id)}
                          disabled={busy}
                          className="rounded bg-green-600 px-2 py-1 font-medium text-white hover:bg-green-700 disabled:opacity-50"
                        >
                          Approve
                        </button>
                        <button
                          onClick={() => onDecline(r.id)}
                          disabled={busy}
                          className="rounded bg-gray-200 px-2 py-1 font-medium text-gray-700 hover:bg-gray-300 disabled:opacity-50"
                        >
                          Decline
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </div>
  )
}

function EnrollmentCard({
  title, subtitle, rows, approverCount, loading, onRevoke, busy,
}: {
  title: string
  subtitle: string
  rows: SalaryEnrollmentRow[]
  approverCount: number
  loading: boolean
  onRevoke: (userId: number, kind: string) => void
  busy: boolean
}) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white">
      <div className="border-b border-gray-100 px-4 py-3">
        <h3 className="text-sm font-semibold text-gray-900">{title}</h3>
        <p className="mt-0.5 text-xs text-gray-500">{subtitle}</p>
      </div>
      {loading ? (
        <p className="px-4 py-3 text-xs text-gray-400">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="px-4 py-3 text-xs text-gray-400">None enrolled.</p>
      ) : (
        <table className="w-full text-xs">
          <thead className="bg-gray-50 text-gray-500">
            <tr>
              <th className="px-4 py-2 text-left font-medium">User</th>
              <th className="px-4 py-2 text-right font-medium">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {rows.map((r) => {
              const isLastApprover = r.kind === 'approver' && approverCount <= 1
              return (
                <tr key={r.id}>
                  <td className="px-4 py-2 text-gray-800">{r.user_name}</td>
                  <td className="px-4 py-2 text-right">
                    <button
                      onClick={() => onRevoke(r.user_id, r.kind)}
                      disabled={busy || isLastApprover}
                      title={isLastApprover ? 'Cannot remove the last approver' : undefined}
                      className="rounded bg-red-50 px-2 py-1 font-medium text-red-600 hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      Revoke
                    </button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </div>
  )
}
