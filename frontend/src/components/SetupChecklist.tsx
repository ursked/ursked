'use client'

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import Link from 'next/link'
import { Check, ChevronRight, X } from 'lucide-react'
import { api } from '@/lib/api'
import type { SetupStatus, UserPreferences } from '@/types'
import { Card, CardBody, Button } from '@/components/ui'

const DISMISS_KEY = 'setup_checklist_dismissed'

export default function SetupChecklist() {
  const qc = useQueryClient()

  const { data: prefs } = useQuery<UserPreferences>({
    queryKey: ['user-preferences'],
    queryFn: () => api.getUserPreferences(),
  })

  const { data: status } = useQuery<SetupStatus>({
    queryKey: ['setup-status'],
    // /settings/setup-status exists in every edition (the card used to call an
    // Enterprise-only route and showed an error on Community dashboards).
    queryFn: () => api.getSetupStatus(),
    // Administrators and HR only; a 403 just means "hide the card".
    retry: false,
  })

  const dismiss = useMutation({
    // A top-level preference key: the preferences PATCH merges known keys
    // and silently dropped the old nested {preferences: {...}} shape, so the
    // card came back on every visit.
    mutationFn: () => api.updateUserPreferences({ [DISMISS_KEY]: true }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['user-preferences'] }),
  })

  if (!status) return null
  const dismissed = Boolean(prefs?.preferences?.[DISMISS_KEY])
  const pct = status.total ? Math.round((status.completed / status.total) * 100) : 0

  // Auto-hide when fully set up, or when the user dismissed it.
  if (dismissed || pct >= 100) return null

  const radius = 20
  const circ = 2 * Math.PI * radius
  const offset = circ - (pct / 100) * circ

  return (
    <Card>
      <CardBody>
        <div className="flex items-start justify-between gap-2">
          <div className="flex min-w-0 items-center gap-4">
            <div className="relative h-14 w-14 shrink-0">
              <svg className="h-14 w-14 -rotate-90" viewBox="0 0 48 48">
                <circle cx="24" cy="24" r={radius} fill="none" stroke="#e5e7eb" strokeWidth="4" />
                <circle
                  cx="24"
                  cy="24"
                  r={radius}
                  fill="none"
                  stroke="#047857"
                  strokeWidth="4"
                  strokeDasharray={circ}
                  strokeDashoffset={offset}
                  strokeLinecap="round"
                />
              </svg>
              <span className="absolute inset-0 flex items-center justify-center text-xs font-semibold text-gray-700">
                {pct}%
              </span>
            </div>
            <div>
              <h3 className="text-base font-semibold text-gray-900">Finish setting up</h3>
              <p className="text-sm text-gray-500">
                {status.completed} of {status.total} steps done. Complete these to get the most out of the app.
              </p>
            </div>
          </div>
          <button
            onClick={() => dismiss.mutate()}
            className="rounded-md p-1 text-gray-400 hover:bg-gray-100"
            aria-label="Dismiss"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <ul className="mt-4 divide-y divide-gray-100">
          {status.steps.map((step) => {
            const mark = (
              <span
                className={
                  'flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs ' +
                  (step.done ? 'bg-green-100 text-green-700' : 'border border-gray-300 text-gray-400')
                }
              >
                {step.done ? <Check className="h-3.5 w-3.5" /> : ''}
              </span>
            )
            const label = (
              <span
                className={
                  'min-w-0 flex-1 text-sm ' +
                  (step.done ? 'text-gray-400 line-through' : 'text-gray-700')
                }
              >
                {step.label}
              </span>
            )
            // Finance's steps (salary grades, deductions) are done from the
            // finance dashboard; nobody here opens Finances, so no link.
            if (step.by === 'finance') {
              return (
                <li key={step.key} className="flex items-center gap-3 py-2.5">
                  {mark}
                  {label}
                  <span className="shrink-0 text-xs text-gray-500">Done by Finance</span>
                </li>
              )
            }
            return (
              <li key={step.key}>
                <Link
                  href={step.link}
                  className="flex items-center gap-3 py-2.5 hover:bg-gray-50 -mx-2 px-2 rounded-md"
                >
                  {mark}
                  {label}
                  {!step.done && <ChevronRight className="h-4 w-4 shrink-0 text-gray-300" />}
                </Link>
              </li>
            )
          })}
        </ul>
      </CardBody>
    </Card>
  )
}
