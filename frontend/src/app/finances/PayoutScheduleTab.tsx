'use client'

import { useEffect, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { PayoutSchedule, CutoffRule } from '@/types'
import { useToast } from '@/components/ui/Toast'
import { usePermissions } from '@/contexts/PermissionsContext'
import { LoadProblem } from './financeUi'

type Frequency = PayoutSchedule['frequency']

// Each preset carries its own frequency. The screen used to save every
// schedule as semi-monthly, so a "Monthly, paid 30th" schedule was stored
// as semi-monthly.
const PRESETS: Record<string, { label: string; frequency: Frequency; cutoffs: CutoffRule[] }> = {
  semi_5_20: {
    label: 'Semi-monthly · paid 20th & 5th',
    frequency: 'semi_monthly',
    cutoffs: [
      { cutoff_start_day: 1, cutoff_end_day: 15, payout_day: 20, payout_month_offset: 0 },
      { cutoff_start_day: 16, cutoff_end_day: 31, payout_day: 5, payout_month_offset: 1 },
    ],
  },
  semi_15_30: {
    label: 'Semi-monthly · paid 15th & 30th (next month)',
    frequency: 'semi_monthly',
    cutoffs: [
      { cutoff_start_day: 1, cutoff_end_day: 15, payout_day: 15, payout_month_offset: 1 },
      { cutoff_start_day: 16, cutoff_end_day: 31, payout_day: 30, payout_month_offset: 1 },
    ],
  },
  monthly_30: {
    label: 'Monthly · paid 30th',
    frequency: 'monthly',
    cutoffs: [{ cutoff_start_day: 1, cutoff_end_day: 31, payout_day: 30, payout_month_offset: 0 }],
  },
}

const FREQUENCY_LABEL: Record<Frequency, string> = {
  semi_monthly: 'Semi-monthly',
  monthly: 'Monthly',
  weekly: 'Weekly',
  bi_weekly: 'Every two weeks',
}

/** A cutoff being edited. A field someone emptied is null ("not set"), not 0:
 *  Number('') is 0, which silently saved a payout on day 0. */
type CutoffDraft = { [K in keyof CutoffRule]: number | null }

const FIELD_LABEL: Record<keyof CutoffRule, string> = {
  cutoff_start_day: 'Cutoff start day',
  cutoff_end_day: 'Cutoff end day',
  payout_day: 'Payout day',
  payout_month_offset: 'Month offset',
}

function validate(cutoffs: CutoffDraft[]): string[] {
  const errors: string[] = []
  cutoffs.forEach((c, i) => {
    const n = i + 1
    for (const key of Object.keys(FIELD_LABEL) as (keyof CutoffRule)[]) {
      const v = c[key]
      if (v == null) {
        errors.push(`Cutoff ${n}: ${FIELD_LABEL[key]} is not set.`)
        continue
      }
      const [lo, hi] = key === 'payout_month_offset' ? [0, 12] : [1, 31]
      if (!Number.isInteger(v) || v < lo || v > hi) errors.push(`Cutoff ${n}: ${FIELD_LABEL[key]} must be a whole number from ${lo} to ${hi}.`)
    }
    if (c.cutoff_start_day != null && c.cutoff_end_day != null && c.cutoff_end_day < c.cutoff_start_day) {
      errors.push(`Cutoff ${n}: the end day is before the start day.`)
    }
  })
  return errors
}

export default function PayoutScheduleTab() {
  const queryClient = useQueryClient()
  const { showToast } = useToast()
  const { hasPermission } = usePermissions()
  const canCreate = hasPermission('finances', 'create')
  const canEdit = hasPermission('finances', 'edit')
  const canDelete = hasPermission('finances', 'delete')

  const { data: active, isLoading, error } = useQuery<PayoutSchedule | null>({
    queryKey: ['payout-schedule-active'],
    queryFn: () => api.getActivePayoutSchedule(),
  })
  const { data: all } = useQuery<PayoutSchedule[]>({
    queryKey: ['payout-schedules'],
    queryFn: () => api.getPayoutSchedules(),
  })

  const [name, setName] = useState('Company payout schedule')
  const [frequency, setFrequency] = useState<Frequency>('semi_monthly')
  const [adjust, setAdjust] = useState<'none' | 'prev_business_day' | 'next_business_day'>('none')
  const [cutoffs, setCutoffs] = useState<CutoffDraft[]>(PRESETS.semi_5_20.cutoffs)
  const [previewDate, setPreviewDate] = useState('2026-01-10')
  const [previewResult, setPreviewResult] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<number | null>(null)

  useEffect(() => {
    if (!active) return
    let alive = true
    // Defer so state updates do not run synchronously in the effect body
    // (react-hooks/set-state-in-effect).
    void Promise.resolve().then(() => {
      if (!alive) return
      setName(active.name)
      setFrequency(active.frequency)
      setAdjust(active.payout_day_adjust)
      setCutoffs(active.cutoffs)
    })
    return () => {
      alive = false
    }
  }, [active])

  const errors = validate(cutoffs)
  const mayWrite = active ? canEdit : canCreate

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['payout-schedule-active'] })
    queryClient.invalidateQueries({ queryKey: ['payout-schedules'] })
  }

  const saveMut = useMutation({
    mutationFn: async () => {
      if (errors.length) throw new Error(errors[0])
      const payload = { name, frequency, cutoffs: cutoffs as CutoffRule[], payout_day_adjust: adjust, is_active: true }
      if (active) return api.updatePayoutSchedule(active.id, payload)
      return api.createPayoutSchedule(payload)
    },
    onSuccess: () => {
      invalidate()
      showToast('Payout schedule saved', 'success')
    },
    onError: (e: Error) => showToast(e.message, 'error'),
  })

  const deleteMut = useMutation({
    mutationFn: (id: number) => api.deletePayoutSchedule(id),
    onSuccess: () => {
      setConfirmDelete(null)
      invalidate()
      showToast('Payout schedule deleted', 'success')
    },
    onError: (e: Error) => {
      setConfirmDelete(null)
      showToast(e.message, 'error')
    },
  })

  const runPreview = async () => {
    try {
      // Save first so the preview reflects the current cutoffs, then resolve.
      if (mayWrite) await saveMut.mutateAsync()
      const res = await api.previewPayoutDate(previewDate)
      setPreviewResult(res.payout_date)
    } catch (e) {
      showToast((e as Error).message, 'error')
    }
  }

  const setCutoff = (i: number, patch: Partial<CutoffDraft>) => {
    setCutoffs((cs) => cs.map((c, idx) => (idx === i ? { ...c, ...patch } : c)))
  }

  if (isLoading) return <p className="text-sm text-gray-500">Loading…</p>
  if (error) return <LoadProblem error={error} what="the payout schedule" />

  return (
    <div className="max-w-3xl space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-gray-900">Payout Schedule</h2>
        <p className="text-sm text-gray-500">
          Define how cutoff windows map to payout dates. Earnings (holiday pay, overtime,
          leave-to-cash, bonuses, incentives, allowances) are earned in a cutoff window
          but paid on the resolved payout date — which can fall in a later run.
        </p>
      </div>

      <fieldset disabled={!mayWrite} className="space-y-6">
        <div>
          <label htmlFor="ps-name" className="mb-1 block text-sm font-medium text-gray-700">Schedule name</label>
          <input id="ps-name" className="input" value={name} onChange={(e) => setName(e.target.value)} />
        </div>

        <div>
          <span className="mb-2 block text-sm font-medium text-gray-700">Start from a preset</span>
          <div className="flex flex-wrap gap-2">
            {Object.entries(PRESETS).map(([k, p]) => (
              <button
                key={k}
                type="button"
                onClick={() => { setCutoffs(p.cutoffs); setFrequency(p.frequency) }}
                className="rounded-full border border-gray-300 px-3 py-1 text-xs font-medium text-gray-700 hover:border-purple-400 hover:bg-purple-50"
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label htmlFor="ps-frequency" className="mb-1 block text-sm font-medium text-gray-700">How often you pay</label>
          <select id="ps-frequency" className="input max-w-xs" value={frequency} onChange={(e) => setFrequency(e.target.value as Frequency)}>
            {(Object.keys(FREQUENCY_LABEL) as Frequency[]).map((f) => <option key={f} value={f}>{FREQUENCY_LABEL[f]}</option>)}
          </select>
        </div>

        <div className="space-y-3">
          <span className="block text-sm font-medium text-gray-700">Cutoff windows</span>
          {cutoffs.map((c, i) => (
            <div key={i} className="grid grid-cols-2 gap-3 rounded-lg border border-gray-200 p-3 sm:grid-cols-4">
              {(Object.keys(FIELD_LABEL) as (keyof CutoffRule)[]).map((key) => (
                <NumField key={key} label={FIELD_LABEL[key]} value={c[key]} onChange={(v) => setCutoff(i, { [key]: v })} />
              ))}
            </div>
          ))}
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setCutoffs((cs) => [...cs, { cutoff_start_day: 1, cutoff_end_day: 15, payout_day: 15, payout_month_offset: 0 }])}
              className="rounded-md border border-gray-300 px-3 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50"
            >
              + Add cutoff
            </button>
            {cutoffs.length > 1 && (
              <button
                type="button"
                onClick={() => setCutoffs((cs) => cs.slice(0, -1))}
                className="rounded-md border border-gray-300 px-3 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50"
              >
                Remove last
              </button>
            )}
          </div>
          {errors.length > 0 && (
            <ul className="list-disc space-y-0.5 rounded-md bg-red-50 py-2 pl-8 pr-3 text-sm text-red-800" role="alert">
              {errors.map((e) => <li key={e}>{e}</li>)}
            </ul>
          )}
        </div>

        <div>
          <label htmlFor="ps-adjust" className="mb-1 block text-sm font-medium text-gray-700">If payout lands on a weekend/holiday</label>
          <select id="ps-adjust" className="input max-w-xs" value={adjust} onChange={(e) => setAdjust(e.target.value as typeof adjust)}>
            <option value="none">Keep the date</option>
            <option value="prev_business_day">Move to previous business day</option>
            <option value="next_business_day">Move to next business day</option>
          </select>
        </div>

        {mayWrite && (
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => saveMut.mutate()}
              disabled={saveMut.isPending || errors.length > 0}
              className="rounded-md bg-purple-600 px-4 py-2 text-sm font-semibold text-white hover:bg-purple-700 disabled:opacity-50"
            >
              {active ? 'Save schedule' : 'Create schedule'}
            </button>
          </div>
        )}
      </fieldset>

      <div className="rounded-lg border border-dashed border-gray-300 p-4">
        <span className="block text-sm font-medium text-gray-700">Preview: when is work paid?</span>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <label htmlFor="ps-preview" className="text-sm text-gray-600">Work earned on</label>
          <input id="ps-preview" type="date" className="input max-w-[10rem]" value={previewDate} onChange={(e) => setPreviewDate(e.target.value)} />
          <button type="button" onClick={runPreview} disabled={errors.length > 0} className="rounded-md border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50">
            Resolve
          </button>
          {previewResult && (
            <span className="text-sm font-semibold text-purple-700">→ paid on {previewResult}</span>
          )}
        </div>
      </div>

      {(all ?? []).length > 0 && (
        <div className="rounded-lg border border-gray-200">
          <div className="border-b border-gray-100 px-4 py-3">
            <h3 className="text-sm font-semibold text-gray-900">All payout schedules</h3>
            <p className="text-xs text-gray-500">Only one is active. A schedule a payroll period used cannot be deleted.</p>
          </div>
          <ul className="divide-y divide-gray-100">
            {(all ?? []).map((s) => (
              <li key={s.id} className="flex items-center justify-between px-4 py-2 text-sm">
                <span>
                  <span className="font-medium text-gray-900">{s.name}</span>
                  <span className="ml-2 text-gray-500">{FREQUENCY_LABEL[s.frequency] ?? s.frequency}</span>
                  {s.is_active && <span className="ml-2 rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-800">Active</span>}
                </span>
                {canDelete && (confirmDelete === s.id ? (
                  <span className="space-x-2">
                    <button type="button" onClick={() => deleteMut.mutate(s.id)} disabled={deleteMut.isPending} className="text-sm font-medium text-red-600 hover:text-red-800 disabled:opacity-50">
                      Confirm delete
                    </button>
                    <button type="button" onClick={() => setConfirmDelete(null)} className="text-sm text-gray-500 hover:text-gray-700">Cancel</button>
                  </span>
                ) : (
                  <button type="button" onClick={() => setConfirmDelete(s.id)} className="text-sm text-red-600 hover:text-red-800">Delete</button>
                ))}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

function NumField({ label, value, onChange }: { label: string; value: number | null; onChange: (v: number | null) => void }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-gray-600">{label}</span>
      <input
        type="number"
        className="input"
        value={value ?? ''}
        placeholder="Not set"
        aria-invalid={value == null}
        onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))}
      />
    </label>
  )
}
