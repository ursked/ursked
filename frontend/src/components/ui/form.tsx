'use client'

import * as React from 'react'
import { cn } from '@/lib/utils'

interface FieldProps {
  label?: string
  htmlFor?: string
  help?: string
  error?: string
  required?: boolean
  children: React.ReactNode
  className?: string
}

/** A labelled form control with help text and validation error. Works with
 * plain inputs or react-hook-form registered fields. */
export function FormField({
  label,
  htmlFor,
  help,
  error,
  required,
  children,
  className,
}: FieldProps) {
  return (
    <div className={cn('space-y-1.5', className)}>
      {label && (
        <label htmlFor={htmlFor} className="block text-sm font-medium text-gray-700">
          {label}
          {required && <span className="ml-0.5 text-red-500">*</span>}
        </label>
      )}
      {children}
      {help && !error && <p className="text-xs text-gray-500">{help}</p>}
      {error && <p className="text-xs text-red-600">{error}</p>}
    </div>
  )
}
