'use client'

import { useState, useRef, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { useToast } from '@/components/ui/Toast'
import type { NotificationRow } from '@/types'

/** Header notification bell. Polls the feed, shows an unread badge, and renders
 *  actionable salary-enrollment requests with inline Approve / Decline. */
export function NotificationsBell() {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const router = useRouter()
  const qc = useQueryClient()
  const { showToast } = useToast()

  const q = useQuery({
    queryKey: ['notifications'],
    queryFn: () => api.getNotifications(),
    refetchInterval: 30_000,
  })

  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [])

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['notifications'] })
    qc.invalidateQueries({ queryKey: ['salary-requests', 'pending'] })
    qc.invalidateQueries({ queryKey: ['salary-enrollments'] })
  }

  const approveMut = useMutation({
    mutationFn: (refId: number) => api.approveSalaryRequest(refId),
    onSuccess: () => { invalidate(); showToast('Request approved', 'success') },
    onError: (e: Error) => showToast(e.message, 'error'),
  })
  const declineMut = useMutation({
    mutationFn: (refId: number) => api.declineSalaryRequest(refId),
    onSuccess: () => { invalidate(); showToast('Request declined', 'success') },
    onError: (e: Error) => showToast(e.message, 'error'),
  })
  const readMut = useMutation({
    mutationFn: (id: number) => api.markNotificationRead(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['notifications'] }),
  })
  const readAllMut = useMutation({
    mutationFn: () => api.markAllNotificationsRead(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['notifications'] }),
  })

  const items = q.data?.items ?? []
  const unread = q.data?.unread_count ?? 0

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="relative text-gray-500 hover:text-gray-700 transition-colors"
        aria-label="Notifications"
      >
        <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
        </svg>
        {unread > 0 && (
          <span className="absolute -top-1 -right-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-red-500 px-1 text-[10px] font-semibold text-white">
            {unread > 9 ? '9+' : unread}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 mt-2 w-80 rounded-lg border border-gray-200 bg-white shadow-lg z-50">
          <div className="flex items-center justify-between border-b border-gray-100 px-4 py-2">
            <span className="text-sm font-semibold text-gray-900">Notifications</span>
            {unread > 0 && (
              <button
                onClick={() => readAllMut.mutate()}
                className="text-xs text-purple-600 hover:text-purple-700"
              >
                Mark all read
              </button>
            )}
          </div>
          <div className="max-h-96 overflow-y-auto">
            {items.length === 0 ? (
              <p className="px-4 py-6 text-center text-xs text-gray-400">No notifications.</p>
            ) : (
              items.map((n) => (
                <NotificationItem
                  key={n.id}
                  n={n}
                  onApprove={() => n.action_ref_id && approveMut.mutate(n.action_ref_id)}
                  onDecline={() => n.action_ref_id && declineMut.mutate(n.action_ref_id)}
                  onRead={() => readMut.mutate(n.id)}
                  onOpen={() => { setOpen(false); router.push('/finances?tab=salary-access') }}
                  busy={approveMut.isPending || declineMut.isPending}
                />
              ))
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function NotificationItem({
  n, onApprove, onDecline, onRead, onOpen, busy,
}: {
  n: NotificationRow
  onApprove: () => void
  onDecline: () => void
  onRead: () => void
  onOpen: () => void
  busy: boolean
}) {
  const actionable = n.action_type === 'approve_salary_request' && !n.is_actioned
  return (
    <div className={`border-b border-gray-50 px-4 py-3 ${n.is_read ? 'bg-white' : 'bg-purple-50/40'}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-medium text-gray-900">{n.title}</p>
          {n.body ? <p className="mt-0.5 text-xs text-gray-500">{n.body}</p> : null}
        </div>
        {!n.is_read && (
          <button onClick={onRead} className="shrink-0 text-[10px] text-gray-400 hover:text-gray-600">
            mark read
          </button>
        )}
      </div>
      {actionable && (
        <div className="mt-2 flex gap-2">
          <button
            onClick={onApprove}
            disabled={busy}
            className="rounded bg-green-600 px-2 py-1 text-xs font-medium text-white hover:bg-green-700 disabled:opacity-50"
          >
            Approve
          </button>
          <button
            onClick={onDecline}
            disabled={busy}
            className="rounded bg-gray-200 px-2 py-1 text-xs font-medium text-gray-700 hover:bg-gray-300 disabled:opacity-50"
          >
            Decline
          </button>
          <button onClick={onOpen} className="rounded px-2 py-1 text-xs text-purple-600 hover:text-purple-700">
            Open
          </button>
        </div>
      )}
    </div>
  )
}
