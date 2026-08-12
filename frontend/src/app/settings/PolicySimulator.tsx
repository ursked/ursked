'use client'

import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { PolicySimulateResult } from '@/types'
import { useToast } from '@/components/ui/Toast'

const ACTION_LABEL: Record<string, string> = {
  apply_ot_category: 'Apply OT Category',
  salary_deduction: 'Salary Deduction',
  leave_deduction: 'Leave Deduction',
  send_warning: 'Send Warning',
  mark_excused: 'Mark Excused',
  apply_night_diff: 'Night Differential',
  apply_holiday_pay: 'Holiday Pay',
}

/** Dry-run panel: replays the ACTIVE policy rules over a date range and shows the
 *  effects they WOULD apply, writing nothing. Lets an admin sanity-check a rule
 *  change against real attendance before it touches payroll. */
export default function PolicySimulator() {
  const { showToast } = useToast()
  const today = new Date()
  const firstOfMonth = new Date(today.getFullYear(), today.getMonth(), 1)
  const [startDate, setStartDate] = useState(firstOfMonth.toISOString().slice(0, 10))
  const [endDate, setEndDate] = useState(today.toISOString().slice(0, 10))
  const [result, setResult] = useState<PolicySimulateResult | null>(null)

  const runMutation = useMutation({
    mutationFn: () => api.simulatePolicyRules({ start_date: startDate, end_date: endDate }),
    onSuccess: (data) => setResult(data),
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  return (
    <div className="rounded-lg border border-gray-200 bg-white">
      <div className="border-b border-gray-100 px-4 py-3">
        <h3 className="text-sm font-semibold text-gray-900">Rule Simulator (dry-run)</h3>
        <p className="mt-0.5 text-xs text-gray-500">
          See what the active rules would do to attendance in a date range — nothing is saved.
        </p>
      </div>
      <div className="flex flex-wrap items-end gap-3 px-4 py-3">
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">From</label>
          <input
            type="date"
            value={startDate}
            onChange={(e) => { setStartDate(e.target.value); setResult(null) }}
            className="rounded-md border border-gray-300 px-2 py-1.5 text-sm"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">To</label>
          <input
            type="date"
            value={endDate}
            min={startDate}
            onChange={(e) => { setEndDate(e.target.value); setResult(null) }}
            className="rounded-md border border-gray-300 px-2 py-1.5 text-sm"
          />
        </div>
        <button
          onClick={() => runMutation.mutate()}
          disabled={runMutation.isPending || !startDate || !endDate}
          className="rounded-md bg-purple-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
        >
          {runMutation.isPending ? 'Simulating…' : 'Run simulation'}
        </button>
      </div>

      {result && (
        <div className="border-t border-gray-100 px-4 py-3">
          <p className="text-xs text-gray-600 mb-2">
            Evaluated <span className="font-semibold">{result.records_evaluated}</span> attendance record(s) ·
            {' '}<span className="font-semibold">{result.effects.length}</span> effect(s) would be applied.
          </p>
          {result.effects.length === 0 ? (
            <p className="text-xs text-gray-400">No rules would fire for this range.</p>
          ) : (
            <div className="max-h-72 overflow-y-auto rounded-md border border-gray-100">
              <table className="w-full text-xs">
                <thead className="bg-gray-50 text-gray-500">
                  <tr>
                    <th className="px-2 py-1.5 text-left font-medium">Date</th>
                    <th className="px-2 py-1.5 text-left font-medium">Employee</th>
                    <th className="px-2 py-1.5 text-left font-medium">Rule</th>
                    <th className="px-2 py-1.5 text-left font-medium">Would do</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {result.effects.map((e, i) => (
                    <tr key={i}>
                      <td className="px-2 py-1.5 text-gray-700">{e.date}</td>
                      <td className="px-2 py-1.5 text-gray-700">{e.employee_name ?? `#${e.employee_id}`}</td>
                      <td className="px-2 py-1.5 text-gray-500">{e.rule_name}</td>
                      <td className="px-2 py-1.5">
                        <span className="inline-block rounded bg-purple-50 px-1.5 py-0.5 text-purple-700">
                          {ACTION_LABEL[e.action] ?? e.action}
                        </span>
                        {e.detail ? <span className="ml-2 text-gray-400">{e.detail}</span> : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
