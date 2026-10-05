'use client'

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { PayRules } from '@/types'
import { useToast } from '@/components/ui/Toast'
import { usePermissions } from '@/contexts/PermissionsContext'
import { LoadProblem } from './financeUi'

// Working days per month and the night and holiday premiums. They used to sit
// in Settings -> General, where editing settings meant changing what everyone
// is paid. They are finance configuration: finances:view reads them and
// finances:edit saves them, the same gates as GET/PUT /payroll/pay-rules.
// They are structure, not anyone's pay, so no salary access is needed.

type NumberKey = Exclude<keyof PayRules, 'night_shift_start' | 'night_shift_end'>

/** The form as typed. Numbers stay strings until saved so "1." and an emptied
 *  field can be reported instead of silently becoming 1 or 0. */
type Draft = Record<NumberKey, string> & { night_shift_start: string; night_shift_end: string }

const NUMBER_FIELDS: { key: NumberKey; label: string; help: string; min: number; max: number; step: number; whole?: boolean }[] = [
  {
    key: 'working_days_per_month',
    label: 'Working days per month',
    help: 'Divides a monthly salary grade to derive the daily rate, which in turn derives the hourly rate.',
    min: 1, max: 31, step: 1, whole: true,
  },
  {
    key: 'night_diff_multiplier',
    label: 'Night differential multiplier',
    help: '1.0 means no premium. 1.10 pays a 10% premium on hours inside the night window.',
    min: 1, max: 10, step: 0.01,
  },
  {
    key: 'holiday_worked_multiplier',
    label: 'Regular holiday multiplier',
    help: 'Applied to hours worked on a regular holiday. 2.0 pays double.',
    min: 1, max: 10, step: 0.01,
  },
  {
    key: 'special_holiday_worked_multiplier',
    label: 'Special holiday multiplier',
    help: 'Applied to hours worked on a special (non-regular) holiday.',
    min: 1, max: 10, step: 0.01,
  },
]

/** Backend sends "HH:MM:SS"; <input type="time"> wants "HH:MM". */
const toTimeInput = (v?: string | null) => (v ? v.slice(0, 5) : '')

function toDraft(r: PayRules): Draft {
  return {
    working_days_per_month: String(r.working_days_per_month),
    night_diff_multiplier: String(r.night_diff_multiplier),
    holiday_worked_multiplier: String(r.holiday_worked_multiplier),
    special_holiday_worked_multiplier: String(r.special_holiday_worked_multiplier),
    night_shift_start: toTimeInput(r.night_shift_start),
    night_shift_end: toTimeInput(r.night_shift_end),
  }
}

function validate(d: Draft): string[] {
  const errors: string[] = []
  for (const f of NUMBER_FIELDS) {
    const raw = d[f.key].trim()
    const n = Number(raw)
    if (raw === '' || Number.isNaN(n)) {
      errors.push(`${f.label} is not set.`)
    } else if (n < f.min || n > f.max || (f.whole && !Number.isInteger(n))) {
      errors.push(`${f.label} must be ${f.whole ? 'a whole number ' : ''}from ${f.min} to ${f.max}.`)
    }
  }
  return errors
}

export default function PayRulesTab() {
  const queryClient = useQueryClient()
  const { showToast } = useToast()
  const { hasPermission } = usePermissions()
  const canEdit = hasPermission('finances', 'edit')

  const { data: rules, isLoading, error } = useQuery<PayRules>({
    queryKey: ['pay-rules'],
    queryFn: () => api.getPayRules(),
  })

  const [draft, setDraft] = useState<Draft | null>(null)
  // When the saved rules change (they loaded, or a save came back), show them.
  // Done while rendering rather than in an effect, which would render the stale
  // draft first (react-hooks/set-state-in-effect).
  const [shown, setShown] = useState<PayRules | undefined>(undefined)
  if (rules !== shown) {
    setShown(rules)
    setDraft(rules ? toDraft(rules) : null)
  }

  const errors = draft ? validate(draft) : []

  const saveMut = useMutation({
    mutationFn: async () => {
      if (!draft) throw new Error('The pay rules have not loaded yet.')
      if (errors.length) throw new Error(errors[0])
      return api.updatePayRules({
        working_days_per_month: Number(draft.working_days_per_month),
        night_diff_multiplier: Number(draft.night_diff_multiplier),
        holiday_worked_multiplier: Number(draft.holiday_worked_multiplier),
        special_holiday_worked_multiplier: Number(draft.special_holiday_worked_multiplier),
        night_shift_start: draft.night_shift_start || null,
        night_shift_end: draft.night_shift_end || null,
      })
    },
    onSuccess: (saved) => {
      queryClient.setQueryData(['pay-rules'], saved)
      // Settings still returns these fields; keep its cached copy in step.
      queryClient.invalidateQueries({ queryKey: ['app-settings'] })
      showToast('Pay rules saved', 'success')
    },
    onError: (e: Error) => showToast(e.message, 'error'),
  })

  if (isLoading) return <p className="text-sm text-gray-500">Loading…</p>
  if (error) return <LoadProblem error={error} what="the pay rules" />
  if (!draft) return null

  const dirty = !!rules && JSON.stringify(toDraft(rules)) !== JSON.stringify(draft)
  const set = (patch: Partial<Draft>) => setDraft((d) => (d ? { ...d, ...patch } : d))
  const numberField = (key: NumberKey) => {
    const f = NUMBER_FIELDS.find((x) => x.key === key)!
    return (
      <div>
        <label htmlFor={`pay-rule-${key}`} className="mb-1 block text-sm font-medium text-gray-700">{f.label}</label>
        <input
          id={`pay-rule-${key}`}
          type="number"
          min={f.min}
          max={f.max}
          step={f.step}
          value={draft[key]}
          onChange={(e) => set({ [key]: e.target.value } as Partial<Draft>)}
          className="block w-40 rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-brand-500 focus:ring-brand-500 focus:outline-none disabled:bg-gray-50 disabled:text-gray-700"
        />
        <p className="mt-1 text-xs text-gray-500">{f.help}</p>
      </div>
    )
  }

  return (
    <div className="max-w-3xl space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-gray-900">Pay rules</h2>
        <p className="text-sm text-gray-500">
          The rates payroll uses to work out everyone&apos;s pay. The values the app ships with are
          Philippine statutory defaults. Check them against the rules that apply to your company, such as
          local law and any collective agreement, and change them to match.
        </p>
      </div>

      {!canEdit && (
        <p className="rounded-md border border-gray-200 bg-gray-50 px-4 py-3 text-sm text-gray-600">
          You can see these rules. Changing them needs permission to edit Finances; ask an administrator
          if you should have it.
        </p>
      )}

      <form
        onSubmit={(e) => {
          e.preventDefault()
          saveMut.mutate()
        }}
      >
        <fieldset disabled={!canEdit || saveMut.isPending} className="space-y-6">
          {numberField('working_days_per_month')}

          <div className="space-y-4 border-t border-gray-200 pt-5">
            <h3 className="text-sm font-semibold text-gray-900">Night differential</h3>
            {numberField('night_diff_multiplier')}
            <div className="flex flex-wrap items-end gap-4">
              <div>
                <label htmlFor="pay-rule-night-start" className="mb-1 block text-sm font-medium text-gray-700">Night window starts</label>
                <input
                  id="pay-rule-night-start"
                  type="time"
                  value={draft.night_shift_start}
                  onChange={(e) => set({ night_shift_start: e.target.value })}
                  className="block w-40 rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-brand-500 focus:ring-brand-500 focus:outline-none disabled:bg-gray-50 disabled:text-gray-700"
                />
              </div>
              <div>
                <label htmlFor="pay-rule-night-end" className="mb-1 block text-sm font-medium text-gray-700">Night window ends</label>
                <input
                  id="pay-rule-night-end"
                  type="time"
                  value={draft.night_shift_end}
                  onChange={(e) => set({ night_shift_end: e.target.value })}
                  className="block w-40 rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-brand-500 focus:ring-brand-500 focus:outline-none disabled:bg-gray-50 disabled:text-gray-700"
                />
              </div>
            </div>
            {(!draft.night_shift_start || !draft.night_shift_end) && (
              <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3">
                <p className="text-xs text-amber-800">
                  No night window is set, so the night differential is never applied no
                  matter what multiplier is configured. Set both a start and an end time
                  to enable it. The window may cross midnight (e.g. 22:00 to 06:00).
                </p>
              </div>
            )}
          </div>

          <div className="space-y-4 border-t border-gray-200 pt-5">
            <h3 className="text-sm font-semibold text-gray-900">Holiday premiums</h3>
            {numberField('holiday_worked_multiplier')}
            {numberField('special_holiday_worked_multiplier')}
          </div>

          <div className="rounded-lg border border-blue-200 bg-blue-50 p-4">
            <p className="text-xs text-blue-800">
              Premiums are paid as <span className="font-medium">hours &times; hourly rate &times; (multiplier &minus; 1)</span> on
              top of base pay, so a multiplier of 1.0 means no premium. Changes apply to
              payroll computed from now on; they do not retroactively alter payroll
              periods that have already been generated.
            </p>
          </div>

          {canEdit && errors.length > 0 && (
            <ul className="list-disc space-y-0.5 rounded-md bg-red-50 py-2 pl-8 pr-3 text-sm text-red-800" role="alert">
              {errors.map((e) => <li key={e}>{e}</li>)}
            </ul>
          )}

          {canEdit && (
            <div className="flex items-center gap-3">
              <button
                type="submit"
                disabled={!dirty || errors.length > 0 || saveMut.isPending}
                className="rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {saveMut.isPending ? 'Saving…' : 'Save pay rules'}
              </button>
              {dirty && (
                <button
                  type="button"
                  onClick={() => rules && setDraft(toDraft(rules))}
                  className="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
                >
                  Discard changes
                </button>
              )}
            </div>
          )}
        </fieldset>
      </form>
    </div>
  )
}
