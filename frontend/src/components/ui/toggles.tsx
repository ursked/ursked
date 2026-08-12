'use client'

import * as React from 'react'
import { Check } from 'lucide-react'
import { cn } from '@/lib/utils'

export const Checkbox = React.forwardRef<
  HTMLInputElement,
  React.InputHTMLAttributes<HTMLInputElement>
>(({ className, ...props }, ref) => (
  <input
    ref={ref}
    type="checkbox"
    className={cn(
      'h-4 w-4 rounded border-gray-300 text-purple-600 focus:ring-purple-500',
      className
    )}
    {...props}
  />
))
Checkbox.displayName = 'Checkbox'

interface SwitchProps {
  checked: boolean
  onChange: (checked: boolean) => void
  disabled?: boolean
  id?: string
}

export function Switch({ checked, onChange, disabled, id }: SwitchProps) {
  return (
    <button
      type="button"
      id={id}
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        'relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-purple-500 disabled:opacity-50',
        checked ? 'bg-purple-600' : 'bg-gray-300'
      )}
    >
      <span
        className={cn(
          'inline-block h-5 w-5 transform rounded-full bg-white shadow transition-transform',
          checked ? 'translate-x-5' : 'translate-x-0.5'
        )}
      />
    </button>
  )
}

interface SegmentedOption<T extends string> {
  value: T
  label: string
  description?: string
}

interface SegmentedControlProps<T extends string> {
  value: T
  onChange: (value: T) => void
  options: SegmentedOption<T>[]
  className?: string
}

/** Three-state (or N-state) segmented control, used for the enforcement
 * block/warn/off selectors. */
export function SegmentedControl<T extends string>({
  value,
  onChange,
  options,
  className,
}: SegmentedControlProps<T>) {
  return (
    <div className={cn('inline-flex rounded-lg border border-gray-300 bg-gray-50 p-0.5', className)}>
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          title={opt.description}
          onClick={() => onChange(opt.value)}
          className={cn(
            'rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
            value === opt.value
              ? 'bg-white text-purple-700 shadow-sm'
              : 'text-gray-500 hover:text-gray-700'
          )}
        >
          {opt.label}
        </button>
      ))}
    </div>
  )
}

export { Check }
