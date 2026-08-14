'use client'

import { useEffect, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { PayoutSchedule, CutoffRule } from '@/types'
import { useToast } from '@/components/ui/Toast'

const PRESETS: Record<string, { label: string; cutoffs: CutoffRule[] }> = {
  semi_5_20: {
    label: 'Semi-monthly · paid 20th & 5th',
    cutoffs: [
      { cutoff_start_day: 1, cutoff_end_day: 15, payout_day: 20, payout_month_offset: 0 },
      { cutoff_start_day: 16, cutoff_end_day: 31, payout_day: 5, payout_month_offset: 1 },
    ],
  },
  semi_15_30: {
    label: 'Semi-monthly · paid 15th & 30th (next month)',
    cutoffs: [
      { cutoff_start_day: 1, cutoff_end_day: 15, payout_day: 15, payout_month_offset: 1 },
      { cutoff_start_day: 16, cutoff_end_day: 31, payout_day: 30, payout_month_offset: 1 },
    ],
  },
  monthly_30: {
    label: 'Monthly · paid 30th',
    cutoffs: [{ cutoff_start_day: 1, cutoff_end_day: 31, payout_day: 30, payout_month_offset: 0 }],
  },
}

export default function PayoutScheduleTab() {
  const queryClient = useQueryClient()
  const { showToast } = useToast()

  const { data: active, isLoading } = useQuery<PayoutSchedule | null>({
    queryKey: ['payout-schedule-active'],
    queryFn: () => api.getActivePayoutSchedule(),
  })

  const [name, setName] = useState('Company payout schedule')
  const [adjust, setAdjust] = useState<'none' | 'prev_business_day' | 'next_business_day'>('none')
  const [cutoffs, setCutoffs] = useState<CutoffRule[]>(PRESETS.semi_5_20.cutoffs)
  const [previewDate, setPreviewDate] = useState('2026-01-10')
  const [previewResult, setPreviewResult] = useState<string | null>(null)

  useEffect(() => {
    if (!active) return
    let alive = true
    // Defer so state updates do not run synchronously in the effect body
    // (react-hooks/set-state-in-effect).
    void Promise.resolve().then(() => {
      if (!alive) return
      setName(active.name)
      setAdjust(active.payout_day_adjust)
      setCutoffs(active.cutoffs)
    })
    return () => {
      alive = false
    }
  }, [active])

  const saveMut = useMutation({
    mutationFn: async () => {
      const payload = { name, frequency: 'semi_monthly' as const, cutoffs, payout_day_adjust: adjust, is_active: true }
      if (active) return api.updatePayoutSchedule(active.id, payload)
      return api.createPayoutSchedule(payload)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['payout-schedule-active'] })
      showToast('Payout schedule saved', 'success')
    },
    onError: (e: Error) => showToast(e.message, 'error'),
  })

  const runPreview = async () => {
    try {
      // Save first so the preview reflects the current cutoffs, then resolve.
      await saveMut.mutateAsync()
      const res = await api.previewPayoutDate(previewDate)
      setPreviewResult(res.payout_date)
    } catch (e) {
      showToast((e as Error).message, 'error')
    }
  }

  const setCutoff = (i: number, patch: Partial<CutoffRule>) => {
    setCutoffs((cs) => cs.map((c, idx) => (idx === i ? { ...c, ...patch } : c)))
  }

  if (isLoading) return <p className="text-sm text-gray-500">Loading…</p>

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

      <div>
        <label className="mb-1 block text-sm font-medium text-gray-700">Schedule name</label>
        <input className="input" value={name} onChange={(e) => setName(e.target.value)} />
      </div>

      <div>
        <span className="mb-2 block text-sm font-medium text-gray-700">Start from a preset</span>
        <div className="flex flex-wrap gap-2">
          {Object.entries(PRESETS).map(([k, p]) => (
            <button
              key={k}
              onClick={() => setCutoffs(p.cutoffs)}
              className="rounded-full border border-gray-300 px-3 py-1 text-xs font-medium text-gray-700 hover:border-purple-400 hover:bg-purple-50"
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      <div className="space-y-3">
        <span className="block text-sm font-medium text-gray-700">Cutoff windows</span>
        {cutoffs.map((c, i) => (
          <div key={i} className="grid grid-cols-2 gap-3 rounded-lg border border-gray-200 p-3 sm:grid-cols-4">
            <NumField label="Cutoff start day" value={c.cutoff_start_day} onChange={(v) => setCutoff(i, { cutoff_start_day: v })} />
            <NumField label="Cutoff end day" value={c.cutoff_end_day} onChange={(v) => setCutoff(i, { cutoff_end_day: v })} />
            <NumField label="Payout day" value={c.payout_day} onChange={(v) => setCutoff(i, { payout_day: v })} />
            <NumField label="Month offset" value={c.payout_month_offset} onChange={(v) => setCutoff(i, { payout_month_offset: v })} />
          </div>
        ))}
        <div className="flex gap-2">
          <button
            onClick={() => setCutoffs((cs) => [...cs, { cutoff_start_day: 1, cutoff_end_day: 15, payout_day: 15, payout_month_offset: 0 }])}
            className="rounded-md border border-gray-300 px-3 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50"
          >
            + Add cutoff
          </button>
          {cutoffs.length > 1 && (
            <button
              onClick={() => setCutoffs((cs) => cs.slice(0, -1))}
              className="rounded-md border border-gray-300 px-3 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50"
            >
              Remove last
            </button>
          )}
        </div>
      </div>

      <div>
        <label className="mb-1 block text-sm font-medium text-gray-700">If payout lands on a weekend/holiday</label>
        <select className="input max-w-xs" value={adjust} onChange={(e) => setAdjust(e.target.value as typeof adjust)}>
          <option value="none">Keep the date</option>
          <option value="prev_business_day">Move to previous business day</option>
          <option value="next_business_day">Move to next business day</option>
        </select>
      </div>

      <div className="flex items-center gap-3">
        <button
          onClick={() => saveMut.mutate()}
          disabled={saveMut.isPending}
          className="rounded-md bg-purple-600 px-4 py-2 text-sm font-semibold text-white hover:bg-purple-700 disabled:opacity-50"
        >
          {active ? 'Save schedule' : 'Create schedule'}
        </button>
      </div>

      <div className="rounded-lg border border-dashed border-gray-300 p-4">
        <span className="block text-sm font-medium text-gray-700">Preview: when is work paid?</span>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <span className="text-sm text-gray-600">Work earned on</span>
          <input type="date" className="input max-w-[10rem]" value={previewDate} onChange={(e) => setPreviewDate(e.target.value)} />
          <button onClick={runPreview} className="rounded-md border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50">
            Resolve
          </button>
          {previewResult && (
            <span className="text-sm font-semibold text-purple-700">→ paid on {previewResult}</span>
          )}
        </div>
      </div>
    </div>
  )
}

function NumField({ label, value, onChange }: { label: string; value: number; onChange: (v: number) => void }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-gray-600">{label}</span>
      <input type="number" className="input" value={value} onChange={(e) => onChange(Number(e.target.value))} />
    </label>
  )
}
