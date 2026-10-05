'use client'

import { useState } from 'react'

/**
 * Numeric setting that commits on blur (or Enter) rather than on every keystroke.
 *
 * These fields feed payroll computation, so keystroke-level saving is wrong twice
 * over: typing "1.25" would PATCH the intermediate values 1 and 1.2, and "1." is
 * not a valid number at all. Hold a local draft, clamp to the field's bounds, and
 * only save when the admin has finished typing and the value actually changed.
 */
export default function NumberSetting({
  id, label, help, value, min, max, step = 1, disabled, onCommit,
}: {
  id: string
  label: string
  help?: string
  value: number | undefined
  min: number
  max: number
  step?: number
  disabled?: boolean
  onCommit: (n: number) => void
}) {
  const [draft, setDraft] = useState(String(value ?? ''))
  // When the saved value changes (it loaded, or a save came back), show it.
  // Done while rendering rather than in an effect: an effect would render the
  // stale draft first and then render again (react-hooks/set-state-in-effect).
  const [shown, setShown] = useState(value)
  if (value !== shown) {
    setShown(value)
    setDraft(String(value ?? ''))
  }

  const commit = () => {
    const n = Number(draft)
    if (draft.trim() === '' || Number.isNaN(n)) {
      setDraft(String(value ?? ''))   // reject junk, restore the saved value
      return
    }
    const clamped = Math.min(max, Math.max(min, n))
    if (clamped !== n) setDraft(String(clamped))
    if (clamped !== value) onCommit(clamped)
  }

  return (
    <div>
      <label htmlFor={id} className="block text-sm font-medium text-gray-700 mb-1">{label}</label>
      <input
        id={id}
        type="number"
        min={min}
        max={max}
        step={step}
        value={draft}
        disabled={disabled}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.blur() }}
        className="block w-40 rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-brand-500 focus:ring-brand-500 focus:outline-none disabled:opacity-50"
      />
      {help && <p className="mt-1 text-xs text-gray-500">{help}</p>}
    </div>
  )
}
