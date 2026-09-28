'use client'

import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { cn } from '@/lib/utils'
import type { UserLookup } from '@/types'

// One employee picker for the whole app. Five screens used to load
// `GET /users?per_page=100` into a <select>, which the backend caps at 100, so
// in a company of 101 people the 101st could never be chosen as an approver,
// unit member, visibility grantee or attendance subject — and nothing said so.
// This searches as you type instead, so there is no ceiling.

type Common = {
  id?: string
  label?: string
  placeholder?: string
  disabled?: boolean
  includeInactive?: boolean
  excludeIds?: number[]
  className?: string
  invalid?: boolean
}

type SingleProps = Common & {
  multiple?: false
  value: number | null
  onChange: (id: number | null, user: UserLookup | null) => void
}

type MultiProps = Common & {
  multiple: true
  value: number[]
  onChange: (ids: number[], users: UserLookup[]) => void
}

export type UserPickerProps = SingleProps | MultiProps

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = React.useState(value)
  React.useEffect(() => {
    const t = setTimeout(() => setV(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return v
}

export function UserPicker(props: UserPickerProps) {
  const { label, placeholder = 'Search by name, email or employee no.', disabled, includeInactive, excludeIds, className, invalid } = props
  const autoId = React.useId()
  const inputId = props.id || `user-picker-${autoId}`
  const listId = `${inputId}-list`

  const selectedIds: number[] = props.multiple ? props.value : props.value != null ? [props.value] : []

  const [query, setQuery] = React.useState('')
  const [open, setOpen] = React.useState(false)
  const [active, setActive] = React.useState(0)
  const debounced = useDebounced(query, 250)
  const wrapRef = React.useRef<HTMLDivElement>(null)

  // Resolve names for ids we were handed but have not seen in a search yet.
  const { data: selectedUsers = [] } = useQuery({
    queryKey: ['user-lookup', 'ids', [...selectedIds].sort().join(','), !!includeInactive],
    queryFn: () => api.lookupUsers({ ids: selectedIds, includeInactive: true }),
    enabled: selectedIds.length > 0,
    staleTime: 60_000,
  })

  const { data: results = [], isFetching, isError } = useQuery({
    queryKey: ['user-lookup', 'q', debounced, !!includeInactive],
    queryFn: () => api.lookupUsers({ q: debounced, includeInactive, limit: 50 }),
    enabled: open && !disabled,
    staleTime: 30_000,
  })

  const excluded = React.useMemo(() => new Set([...(excludeIds || []), ...(props.multiple ? selectedIds : [])]), [excludeIds, props.multiple, selectedIds])
  const options = results.filter((u) => !excluded.has(u.id))

  React.useEffect(() => setActive(0), [debounced, open])

  React.useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])

  const byId = React.useMemo(() => {
    const m = new Map<number, UserLookup>()
    for (const u of selectedUsers) m.set(u.id, u)
    for (const u of results) m.set(u.id, u)
    return m
  }, [selectedUsers, results])

  const choose = (u: UserLookup) => {
    if (props.multiple) {
      const ids = [...props.value, u.id]
      props.onChange(ids, ids.map((i) => byId.get(i)).filter(Boolean) as UserLookup[])
      setQuery('')
    } else {
      props.onChange(u.id, u)
      setQuery('')
      setOpen(false)
    }
  }

  const remove = (id: number) => {
    if (props.multiple) {
      const ids = props.value.filter((i) => i !== id)
      props.onChange(ids, ids.map((i) => byId.get(i)).filter(Boolean) as UserLookup[])
    } else {
      props.onChange(null, null)
    }
  }

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setOpen(true)
      setActive((a) => Math.min(a + 1, Math.max(options.length - 1, 0)))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive((a) => Math.max(a - 1, 0))
    } else if (e.key === 'Enter') {
      if (open && options[active]) {
        e.preventDefault()
        choose(options[active])
      }
    } else if (e.key === 'Escape') {
      setOpen(false)
    } else if (e.key === 'Backspace' && !query && props.multiple && props.value.length) {
      remove(props.value[props.value.length - 1])
    }
  }

  const single = !props.multiple && props.value != null ? byId.get(props.value) : undefined

  return (
    <div ref={wrapRef} className={cn('relative w-full', className)}>
      {label && (
        <label htmlFor={inputId} className="mb-1 block text-sm font-medium text-gray-700">
          {label}
        </label>
      )}

      {props.multiple && props.value.length > 0 && (
        <ul className="mb-2 flex flex-wrap gap-1.5" aria-label="Selected employees">
          {props.value.map((id) => {
            const u = byId.get(id)
            return (
              <li key={id} className="inline-flex items-center gap-1 rounded-full bg-purple-50 py-1 pl-3 pr-1 text-sm text-purple-900">
                <span className="max-w-[14rem] truncate">{u ? u.name : `#${id}`}</span>
                <button
                  type="button"
                  disabled={disabled}
                  onClick={() => remove(id)}
                  className="inline-flex h-7 w-7 items-center justify-center rounded-full hover:bg-purple-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-purple-500"
                  aria-label={`Remove ${u ? u.name : 'employee'}`}
                >
                  ×
                </button>
              </li>
            )
          })}
        </ul>
      )}

      {!props.multiple && single && !open ? (
        <div
          className={cn(
            'flex min-h-10 w-full items-center justify-between gap-2 rounded-lg border bg-white px-3 py-2 text-sm',
            invalid ? 'border-red-400' : 'border-gray-300',
            disabled && 'bg-gray-50'
          )}
        >
          <button
            type="button"
            id={inputId}
            disabled={disabled}
            onClick={() => setOpen(true)}
            className="min-w-0 flex-1 truncate text-left focus-visible:outline-none"
          >
            <span className="font-medium text-gray-900">{single.name}</span>
            {!single.is_active && <span className="ml-2 text-xs text-gray-500">(inactive)</span>}
            <span className="ml-2 text-xs text-gray-500">{single.email}</span>
          </button>
          {!disabled && (
            <button
              type="button"
              onClick={() => remove(single.id)}
              className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-gray-500 hover:bg-gray-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-purple-500"
              aria-label="Clear selection"
            >
              ×
            </button>
          )}
        </div>
      ) : (
        <input
          id={inputId}
          type="text"
          role="combobox"
          aria-expanded={open}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={open && options[active] ? `${listId}-${options[active].id}` : undefined}
          autoComplete="off"
          disabled={disabled}
          value={query}
          placeholder={placeholder}
          onFocus={() => setOpen(true)}
          onChange={(e) => {
            setQuery(e.target.value)
            setOpen(true)
          }}
          onKeyDown={onKeyDown}
          className={cn(
            'flex h-10 w-full rounded-lg border bg-white px-3 py-2 text-sm placeholder:text-gray-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-purple-500 disabled:cursor-not-allowed disabled:bg-gray-50',
            invalid ? 'border-red-400' : 'border-gray-300'
          )}
        />
      )}

      {open && !disabled && (
        <ul
          id={listId}
          role="listbox"
          className="absolute left-0 right-0 z-50 mt-1 max-h-72 overflow-y-auto rounded-lg border border-gray-200 bg-white py-1 shadow-lg"
        >
          {isError && <li className="px-3 py-2 text-sm text-red-700">Could not search employees.</li>}
          {!isError && isFetching && options.length === 0 && (
            <li className="px-3 py-2 text-sm text-gray-500">Searching…</li>
          )}
          {!isError && !isFetching && options.length === 0 && (
            <li className="px-3 py-2 text-sm text-gray-500">{debounced ? 'No employees match.' : 'Type to search.'}</li>
          )}
          {options.map((u, i) => (
            <li
              key={u.id}
              id={`${listId}-${u.id}`}
              role="option"
              aria-selected={i === active}
              onMouseDown={(e) => {
                e.preventDefault()
                choose(u)
              }}
              onMouseEnter={() => setActive(i)}
              className={cn(
                'flex min-h-[44px] cursor-pointer flex-col justify-center px-3 py-1.5 text-sm',
                i === active ? 'bg-purple-50' : 'bg-white'
              )}
            >
              <span className="font-medium text-gray-900">
                {u.name}
                {!u.is_active && <span className="ml-2 text-xs font-normal text-gray-500">(inactive)</span>}
              </span>
              <span className="truncate text-xs text-gray-600">
                {[u.email, u.personnel_number].filter(Boolean).join(' · ')}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
