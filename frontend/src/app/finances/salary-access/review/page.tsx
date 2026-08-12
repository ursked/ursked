'use client'

import { Suspense, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { useQuery, useMutation } from '@tanstack/react-query'
import DashboardLayout from '@/components/layout/DashboardLayout'
import { api } from '@/lib/api'
import { useAuth } from '@/contexts/AuthContext'
import { useToast } from '@/components/ui/Toast'

/** Deep-link landing for the "approve salary request" email. The token only
 *  identifies the request (read-only); the approve/decline decision is made
 *  through the authenticated endpoints, so an approver must be signed in. */
function ReviewContent() {
  const router = useRouter()
  const params = useSearchParams()
  const token = params.get('token') ?? ''
  const { user, isLoading: authLoading } = useAuth()
  const { showToast } = useToast()
  const [note, setNote] = useState('')

  const reqQ = useQuery({
    queryKey: ['salary-request-by-token', token],
    queryFn: () => api.getSalaryRequestByToken(token),
    enabled: !!token,
    retry: false,
  })

  const statusQ = useQuery({
    queryKey: ['my-salary-status'],
    queryFn: () => api.getMySalaryStatus(),
    enabled: !!user,
  })

  const approveMut = useMutation({
    mutationFn: (id: number) => api.approveSalaryRequest(id, note || undefined),
    onSuccess: () => { showToast('Request approved', 'success'); router.push('/finances?tab=salary-access') },
    onError: (e: Error) => showToast(e.message, 'error'),
  })
  const declineMut = useMutation({
    mutationFn: (id: number) => api.declineSalaryRequest(id, note || undefined),
    onSuccess: () => { showToast('Request declined', 'success'); router.push('/finances?tab=salary-access') },
    onError: (e: Error) => showToast(e.message, 'error'),
  })

  const busy = approveMut.isPending || declineMut.isPending

  let body: React.ReactNode
  if (!token) {
    body = <Message text="Missing or invalid link." />
  } else if (authLoading || reqQ.isLoading) {
    body = <Message text="Loading…" />
  } else if (reqQ.isError || !reqQ.data) {
    body = <Message text="This request was not found, has already been decided, or the link has expired." />
  } else if (statusQ.data && !statusQ.data.is_approver) {
    body = <Message text="You are not a salary enrollment approver, so you cannot decide this request." />
  } else {
    const r = reqQ.data
    const own = r.user_id === user?.id
    body = (
      <div className="rounded-lg border border-gray-200 bg-white p-5">
        <h2 className="text-base font-semibold text-gray-900">Salary access request</h2>
        <dl className="mt-3 space-y-1 text-sm">
          <Row label="User" value={r.user_name} />
          <Row label="Requested" value={r.kind} />
          {r.reason ? <Row label="Reason" value={r.reason} /> : null}
        </dl>
        {own ? (
          <p className="mt-4 text-sm text-amber-600">
            This is your own request — another approver must decide it.
          </p>
        ) : (
          <>
            <textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="Note (optional)"
              className="mt-4 w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm"
              rows={2}
            />
            <div className="mt-3 flex gap-2">
              <button
                onClick={() => approveMut.mutate(r.id)}
                disabled={busy}
                className="rounded-md bg-green-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
              >
                Approve
              </button>
              <button
                onClick={() => declineMut.mutate(r.id)}
                disabled={busy}
                className="rounded-md bg-gray-200 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-300 disabled:opacity-50"
              >
                Decline
              </button>
            </div>
          </>
        )}
      </div>
    )
  }

  return (
    <DashboardLayout>
      <div className="mx-auto max-w-lg space-y-4">
        <h1 className="text-xl font-bold text-gray-900">Review Salary Access Request</h1>
        {body}
      </div>
    </DashboardLayout>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-2">
      <dt className="w-24 shrink-0 text-gray-500">{label}</dt>
      <dd className="capitalize text-gray-900">{value}</dd>
    </div>
  )
}

function Message({ text }: { text: string }) {
  return <div className="rounded-lg border border-gray-200 bg-white p-5 text-sm text-gray-600">{text}</div>
}

export default function ReviewPage() {
  return (
    <Suspense fallback={null}>
      <ReviewContent />
    </Suspense>
  )
}
