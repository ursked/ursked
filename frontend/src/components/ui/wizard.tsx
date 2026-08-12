'use client'

import * as React from 'react'
import { Check } from 'lucide-react'
import { cn } from '@/lib/utils'

export interface WizardStep {
  key: string
  title: string
  description?: string
}

interface WizardProgressProps {
  steps: WizardStep[]
  current: number // 0-based
  onStepClick?: (index: number) => void
  maxReached?: number
}

export function WizardProgress({
  steps,
  current,
  onStepClick,
  maxReached = current,
}: WizardProgressProps) {
  return (
    <ol className="flex items-center gap-2">
      {steps.map((step, i) => {
        const done = i < current
        const active = i === current
        const clickable = onStepClick && i <= maxReached
        return (
          <React.Fragment key={step.key}>
            <li className="flex items-center gap-2">
              <button
                type="button"
                disabled={!clickable}
                onClick={() => clickable && onStepClick(i)}
                className={cn(
                  'flex h-8 w-8 shrink-0 items-center justify-center rounded-full border text-sm font-medium transition-colors',
                  done && 'border-purple-600 bg-purple-600 text-white',
                  active && 'border-purple-600 bg-white text-purple-700',
                  !done && !active && 'border-gray-300 bg-white text-gray-400',
                  clickable && 'cursor-pointer'
                )}
              >
                {done ? <Check className="h-4 w-4" /> : i + 1}
              </button>
              <div className="hidden sm:block">
                <div
                  className={cn(
                    'text-sm font-medium',
                    active ? 'text-gray-900' : 'text-gray-500'
                  )}
                >
                  {step.title}
                </div>
              </div>
            </li>
            {i < steps.length - 1 && (
              <li className="h-px flex-1 bg-gray-200" aria-hidden />
            )}
          </React.Fragment>
        )
      })}
    </ol>
  )
}

/** Small hook to drive a linear wizard with per-step validation gates. */
export function useWizard(stepCount: number) {
  const [current, setCurrent] = React.useState(0)
  const [maxReached, setMaxReached] = React.useState(0)

  const goTo = React.useCallback((i: number) => {
    if (i < 0 || i >= stepCount) return
    setCurrent(i)
    setMaxReached((m) => Math.max(m, i))
  }, [stepCount])

  const next = React.useCallback(() => goTo(current + 1), [current, goTo])
  const back = React.useCallback(() => goTo(current - 1), [current, goTo])

  return {
    current,
    maxReached,
    goTo,
    next,
    back,
    isFirst: current === 0,
    isLast: current === stepCount - 1,
  }
}
