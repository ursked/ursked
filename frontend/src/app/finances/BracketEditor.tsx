'use client'

import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { DeductionBracket, DeductionType } from '@/types'
import { useToast } from '@/components/ui/Toast'
import { useCurrency } from '@/lib/currency'

// The table behind a tiered deduction (statutory contributions, income tax).
// The API has existed for a long time; with no screen for it, every tiered
// deduction had no brackets and computed to 0 on every payslip.

interface Row {
  from: string
  to: string
  base: string
  ratePct: string
  basis: 'excess' | 'full'
}

const EMPTY_ROW: Row = { from: '', to: '', base: '0', ratePct: '0', basis: 'excess' }

function toRow(b: DeductionBracket): Row {
  return {
    from: String(b.over_amount ?? 0),
    to: b.up_to_amount == null ? '' : String(b.up_to_amount),
    base: String(b.base_amount ?? 0),
    ratePct: String(Math.round((b.rate ?? 0) * 100 * 10000) / 10000),
    basis: b.rate_basis === 'full' ? 'full' : 'excess',
  }
}

function num(v: string): number | null {
  if (v.trim() === '') return null
  const n = Number(v)
  return Number.isFinite(n) ? n : NaN
}

/** Same rules as the server: ascending, no gaps, no overlaps, only the last row open-ended. */
function validate(rows: Row[]): { brackets: DeductionBracket[]; errors: string[] } {
  const errors: string[] = []
  const parsed = rows.map((r, i) => {
    const from = num(r.from)
    const to = num(r.to)
    const base = num(r.base) ?? 0
    const rate = num(r.ratePct) ?? 0
    const n = i + 1
    if (from === null || Number.isNaN(from)) errors.push(`Row ${n}: enter a "From" amount.`)
    if (to !== null && Number.isNaN(to)) errors.push(`Row ${n}: "To" must be a number or left blank.`)
    if (Number.isNaN(base) || Number.isNaN(rate)) errors.push(`Row ${n}: fixed amount and rate must be numbers.`)
    if ((from ?? 0) < 0 || base < 0 || rate < 0) errors.push(`Row ${n}: amounts and rates cannot be negative.`)
    return {
      over_amount: from ?? 0,
      up_to_amount: to,
      base_amount: base,
      rate: rate / 100,
      rate_basis: r.basis,
    } as DeductionBracket
  })
  const sorted = [...parsed].sort((a, b) => a.over_amount - b.over_amount)
  sorted.forEach((b, i) => {
    const n = i + 1
    if (b.up_to_amount != null && b.up_to_amount <= b.over_amount) errors.push(`Row ${n}: "To" must be more than "From".`)
    if (b.up_to_amount == null && i !== sorted.length - 1) errors.push(`Row ${n}: only the last row can have no upper limit.`)
    if (i > 0) {
      const prev = sorted[i - 1].up_to_amount
      if (prev != null && b.over_amount < prev) errors.push(`Rows ${n - 1} and ${n} overlap.`)
      if (prev != null && b.over_amount > prev) errors.push(`Gap between rows ${n - 1} and ${n}: nothing covers ${prev} to ${b.over_amount}. Start row ${n} at ${prev}.`)
    }
  })
  return { brackets: sorted, errors: Array.from(new Set(errors)) }
}

function preview(brackets: DeductionBracket[], basis: number): number | null {
  const b = brackets.find((x) => basis >= x.over_amount && (x.up_to_amount == null || basis < x.up_to_amount))
  if (!b) return null
  const portion = b.rate_basis === 'full' ? basis : Math.max(0, basis - b.over_amount)
  return Math.round((b.base_amount + b.rate * portion) * 100) / 100
}

export default function BracketEditor({ deduction, canEdit, onClose }: {
  deduction: DeductionType
  canEdit: boolean
  onClose: () => void
}) {
  const qc = useQueryClient()
  const { showToast } = useToast()
  const { format } = useCurrency()
  const [rows, setRows] = useState<Row[] | null>(null)
  const [sample, setSample] = useState('20000')

  const { data, isLoading, error } = useQuery<DeductionBracket[]>({
    queryKey: ['deduction-brackets', deduction.id],
    queryFn: () => api.getDeductionBrackets(deduction.id),
  })

  useEffect(() => {
    if (!data) return
    let alive = true
    // Deferred so the state update is not synchronous in the effect body.
    void Promise.resolve().then(() => {
      if (alive) setRows(data.length ? data.map(toRow) : [{ ...EMPTY_ROW, from: '0' }])
    })
    return () => {
      alive = false
    }
  }, [data])

  const checked = useMemo(() => validate(rows ?? []), [rows])
  const sampleValue = Number(sample)
  const sampleResult = Number.isFinite(sampleValue) && !checked.errors.length ? preview(checked.brackets, sampleValue) : null

  const save = useMutation({
    mutationFn: () => api.replaceDeductionBrackets(deduction.id, checked.brackets),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['deduction-brackets', deduction.id] })
      showToast('Brackets saved. Compute payroll again to apply them.', 'success')
      onClose()
    },
    onError: (e: Error) => showToast(e.message, 'error'),
  })

  const setRow = (i: number, patch: Partial<Row>) =>
    setRows((rs) => (rs ?? []).map((r, idx) => (idx === i ? { ...r, ...patch } : r)))

  const addRow = () =>
    setRows((rs) => {
      const list = rs ?? []
      const last = list[list.length - 1]
      // A new band starts where the last one ends, so no gap is created.
      const start = last && last.to.trim() !== '' ? last.to : ''
      return [...list, { ...EMPTY_ROW, from: start }]
    })

  const basisLabel = deduction.calculation_basis === 'base' ? 'base pay' : 'gross pay'

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="bracket-title"
        className="max-h-[90vh] w-full max-w-4xl overflow-y-auto rounded-xl bg-white p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 id="bracket-title" className="text-lg font-semibold text-gray-900">Brackets: {deduction.name}</h3>
        <p className="mt-1 text-sm text-gray-600">
          Each row covers {basisLabel} from &quot;From&quot; up to (not including) &quot;To&quot;. The deduction is the fixed amount
          plus the rate, applied either to the amount above &quot;From&quot; or to the whole {basisLabel}. Leave &quot;To&quot; blank on
          the last row for no upper limit.
        </p>

        {isLoading || rows === null ? (
          error ? <p className="mt-4 text-sm text-red-700">Could not load the brackets: {(error as Error).message}</p>
            : <p className="mt-4 text-sm text-gray-500">Loading…</p>
        ) : (
          <>
            <div className="mt-4 overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead className="text-left text-xs font-medium uppercase text-gray-500">
                  <tr>
                    <th className="px-2 py-2">From</th>
                    <th className="px-2 py-2">To</th>
                    <th className="px-2 py-2">Fixed amount</th>
                    <th className="px-2 py-2">Rate (%)</th>
                    <th className="px-2 py-2">Rate applies to</th>
                    <th className="px-2 py-2"><span className="sr-only">Remove</span></th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r, i) => (
                    <tr key={i} className="border-t border-gray-100">
                      <td className="px-2 py-1.5">
                        <input aria-label={`Row ${i + 1} from`} type="number" min="0" step="0.01" className="input w-28" disabled={!canEdit}
                          value={r.from} onChange={(e) => setRow(i, { from: e.target.value })} />
                      </td>
                      <td className="px-2 py-1.5">
                        <input aria-label={`Row ${i + 1} to`} type="number" min="0" step="0.01" className="input w-28" disabled={!canEdit}
                          placeholder="No limit" value={r.to} onChange={(e) => setRow(i, { to: e.target.value })} />
                      </td>
                      <td className="px-2 py-1.5">
                        <input aria-label={`Row ${i + 1} fixed amount`} type="number" min="0" step="0.01" className="input w-28" disabled={!canEdit}
                          value={r.base} onChange={(e) => setRow(i, { base: e.target.value })} />
                      </td>
                      <td className="px-2 py-1.5">
                        <input aria-label={`Row ${i + 1} rate percent`} type="number" min="0" step="0.001" className="input w-24" disabled={!canEdit}
                          value={r.ratePct} onChange={(e) => setRow(i, { ratePct: e.target.value })} />
                      </td>
                      <td className="px-2 py-1.5">
                        <select aria-label={`Row ${i + 1} rate applies to`} className="input" disabled={!canEdit}
                          value={r.basis} onChange={(e) => setRow(i, { basis: e.target.value as Row['basis'] })}>
                          <option value="excess">Amount above From</option>
                          <option value="full">Whole {basisLabel}</option>
                        </select>
                      </td>
                      <td className="px-2 py-1.5 text-right">
                        {canEdit && rows.length > 1 && (
                          <button type="button" onClick={() => setRows(rows.filter((_, idx) => idx !== i))}
                            className="rounded-md px-2 py-1 text-xs font-medium text-red-600 hover:bg-red-50">
                            Remove
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {canEdit && (
              <button type="button" onClick={addRow}
                className="mt-2 rounded-md border border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50">
                + Add row
              </button>
            )}

            {checked.errors.length > 0 && (
              <ul className="mt-3 list-disc space-y-0.5 rounded-md bg-red-50 py-2 pl-8 pr-3 text-sm text-red-800" role="alert">
                {checked.errors.map((e) => <li key={e}>{e}</li>)}
              </ul>
            )}

            <div className="mt-4 flex flex-wrap items-center gap-2 rounded-lg border border-dashed border-gray-300 p-3 text-sm">
              <label htmlFor="bracket-sample" className="text-gray-700">Try it: {basisLabel} of</label>
              <input id="bracket-sample" type="number" className="input w-32" value={sample} onChange={(e) => setSample(e.target.value)} />
              <span className="font-medium text-gray-900">
                {checked.errors.length ? 'fix the rows first' : sampleResult == null ? 'no row covers this amount' : `deducts ${format(sampleResult)}`}
              </span>
            </div>
          </>
        )}

        <div className="mt-5 flex justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50">
            {canEdit ? 'Cancel' : 'Close'}
          </button>
          {canEdit && (
            <button type="button" onClick={() => save.mutate()}
              disabled={save.isPending || rows === null || checked.errors.length > 0}
              className="rounded-md bg-purple-600 px-4 py-2 text-sm font-semibold text-white hover:bg-purple-700 disabled:opacity-50">
              {save.isPending ? 'Saving…' : 'Save brackets'}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
