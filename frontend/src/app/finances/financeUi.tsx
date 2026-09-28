'use client'

import Link from 'next/link'
import { ApiError } from '@/lib/api'

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
          <Link href="/finances?tab=salary-access" className="font-semibold text-purple-700 underline">
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
