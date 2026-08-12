'use client'

import * as React from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'
import { cn } from '@/lib/utils'

export interface Column<T> {
  key: string
  header: string
  render?: (row: T) => React.ReactNode
  sortable?: boolean
  sortValue?: (row: T) => string | number
  className?: string
  /** Hide this column below md and show it as a labeled line in card mode. */
  cardLabel?: string
}

interface DataTableProps<T> {
  columns: Column<T>[]
  rows: T[]
  rowKey: (row: T) => string | number
  onRowClick?: (row: T) => void
  empty?: React.ReactNode
  /** Render each row as a card below this breakpoint (mobile). */
  cardBreakpoint?: boolean
  className?: string
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  onRowClick,
  empty,
  cardBreakpoint = false,
  className,
}: DataTableProps<T>) {
  const [sortKey, setSortKey] = React.useState<string | null>(null)
  const [sortDir, setSortDir] = React.useState<'asc' | 'desc'>('asc')

  const sorted = React.useMemo(() => {
    if (!sortKey) return rows
    const col = columns.find((c) => c.key === sortKey)
    if (!col?.sortValue) return rows
    const dir = sortDir === 'asc' ? 1 : -1
    return [...rows].sort((a, b) => {
      const av = col.sortValue!(a)
      const bv = col.sortValue!(b)
      return av < bv ? -dir : av > bv ? dir : 0
    })
  }, [rows, sortKey, sortDir, columns])

  const toggleSort = (key: string) => {
    if (sortKey === key) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    else {
      setSortKey(key)
      setSortDir('asc')
    }
  }

  if (rows.length === 0 && empty) return <>{empty}</>

  return (
    <div className={className}>
      {/* Table (md and up, or always when cardBreakpoint is off) */}
      <div className={cn('overflow-x-auto', cardBreakpoint && 'hidden md:block')}>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-200 text-left text-xs font-medium uppercase tracking-wide text-gray-500">
              {columns.map((col) => (
                <th key={col.key} className={cn('px-3 py-2.5', col.className)}>
                  {col.sortable ? (
                    <button
                      className="inline-flex items-center gap-1 hover:text-gray-700"
                      onClick={() => toggleSort(col.key)}
                    >
                      {col.header}
                      {sortKey === col.key &&
                        (sortDir === 'asc' ? (
                          <ChevronUp className="h-3 w-3" />
                        ) : (
                          <ChevronDown className="h-3 w-3" />
                        ))}
                    </button>
                  ) : (
                    col.header
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {sorted.map((row) => (
              <tr
                key={rowKey(row)}
                onClick={() => onRowClick?.(row)}
                className={cn(onRowClick && 'cursor-pointer hover:bg-gray-50')}
              >
                {columns.map((col) => (
                  <td key={col.key} className={cn('px-3 py-3 text-gray-700', col.className)}>
                    {col.render ? col.render(row) : (row as Record<string, unknown>)[col.key] as React.ReactNode}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Card list (mobile) */}
      {cardBreakpoint && (
        <div className="space-y-3 md:hidden">
          {sorted.map((row) => (
            <div
              key={rowKey(row)}
              onClick={() => onRowClick?.(row)}
              className={cn(
                'rounded-lg border border-gray-200 bg-white p-4',
                onRowClick && 'cursor-pointer active:bg-gray-50'
              )}
            >
              {columns.map((col) => (
                <div key={col.key} className="flex justify-between gap-3 py-1 text-sm">
                  <span className="text-gray-500">{col.cardLabel ?? col.header}</span>
                  <span className="text-right font-medium text-gray-800">
                    {col.render ? col.render(row) : (row as Record<string, unknown>)[col.key] as React.ReactNode}
                  </span>
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
