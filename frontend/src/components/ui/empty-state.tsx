'use client'

import * as React from 'react'
import { LucideIcon } from 'lucide-react'
import { cn } from '@/lib/utils'

interface EmptyStateProps {
  icon?: LucideIcon
  title: string
  description?: string
  action?: React.ReactNode
  className?: string
  tone?: 'default' | 'warning'
}

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className,
  tone = 'default',
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center rounded-xl border border-dashed px-6 py-12 text-center',
        tone === 'warning' ? 'border-yellow-300 bg-yellow-50' : 'border-gray-300 bg-gray-50/50',
        className
      )}
    >
      {Icon && (
        <div
          className={cn(
            'mb-3 flex h-12 w-12 items-center justify-center rounded-full',
            tone === 'warning' ? 'bg-yellow-100 text-yellow-600' : 'bg-gray-100 text-gray-400'
          )}
        >
          <Icon className="h-6 w-6" />
        </div>
      )}
      <h3 className="text-sm font-semibold text-gray-900">{title}</h3>
      {description && <p className="mt-1 max-w-sm text-sm text-gray-500">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}
