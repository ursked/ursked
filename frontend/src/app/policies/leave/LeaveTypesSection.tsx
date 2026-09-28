'use client'

// Leave types (Vacation, Sick, ...). The only screen that could create or edit
// them was settings/LeavePoliciesTab.tsx, which nothing mounted after the
// policies moved here, so custom leave types could only be made through the API.

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Pencil, Power } from 'lucide-react'
import { api } from '@/lib/api'
import type { LeaveTypeConfig } from '@/types'
import { useToast } from '@/components/ui/Toast'
import { Button, Card, CardBody, CardHeader, CardTitle, Badge, Input, FormField } from '@/components/ui'
import { usePermissions } from '@/contexts/PermissionsContext'

// Must match the backend (LeaveTypeCreate.code): starts with a letter, then
// lowercase letters, digits or underscores.
const CODE_PATTERN = /^[a-z][a-z0-9_]*$/

function codeFromName(name: string): string {
  const c = name.toLowerCase().trim().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '')
  return /^[a-z]/.test(c) ? c.slice(0, 50) : c ? `leave_${c}`.slice(0, 50) : ''
}

interface Draft {
  id: number | null
  code: string
  codeTouched: boolean
  name: string
  description: string
  export_code: string
}

const EMPTY: Draft = { id: null, code: '', codeTouched: false, name: '', description: '', export_code: '' }

export default function LeaveTypesSection() {
  const qc = useQueryClient()
  const { showToast } = useToast()
  const { hasPermission } = usePermissions()
  const canEdit = hasPermission('leave', 'edit')
  const canDelete = hasPermission('leave', 'delete')
  const [draft, setDraft] = useState<Draft | null>(null)

  const { data: types } = useQuery<LeaveTypeConfig[]>({
    queryKey: ['leave-types', 'all'],
    queryFn: () => api.getLeaveTypes(),
  })

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['leave-types'] })
    qc.invalidateQueries({ queryKey: ['leave-policies'] })
  }

  const save = useMutation({
    mutationFn: async (d: Draft) => {
      if (d.id) {
        await api.updateLeaveType(d.id, { name: d.name.trim(), description: d.description.trim() || undefined })
      } else {
        await api.createLeaveType({ code: d.code, name: d.name.trim(), description: d.description.trim() || undefined })
      }
    },
    onSuccess: (_r, d) => {
      refresh()
      setDraft(null)
      showToast(d.id ? 'Leave type updated' : 'Leave type created', 'success')
    },
    onError: (e: Error) => showToast(e.message, 'error'),
  })

  const deactivate = useMutation({
    mutationFn: (id: number) => api.deleteLeaveType(id),
    onSuccess: () => {
      refresh()
      showToast('Leave type switched off. Past leave keeps it.', 'success')
    },
    onError: (e: Error) => showToast(e.message, 'error'),
  })

  const codeError = draft && !draft.id && draft.code && !CODE_PATTERN.test(draft.code)
    ? 'Start with a letter; use only lowercase letters, numbers and underscores.'
    : undefined

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <div>
            <CardTitle>Leave types</CardTitle>
            <p className="mt-1 text-sm text-gray-500">The kinds of leave employees can file. Policies decide how many days each type gets.</p>
          </div>
          {canEdit && !draft && (
            <Button size="sm" onClick={() => setDraft({ ...EMPTY })}>
              <Plus className="h-4 w-4" /> New leave type
            </Button>
          )}
        </div>
      </CardHeader>
      <CardBody className="space-y-4">
        {draft && (
          <form
            className="grid gap-3 rounded-lg border border-gray-200 bg-gray-50 p-4 sm:grid-cols-2"
            onSubmit={(e) => {
              e.preventDefault()
              if (!draft.name.trim() || (!draft.id && (!draft.code || codeError))) return
              save.mutate(draft)
            }}
          >
            <FormField label="Name" required htmlFor="lt-name">
              <Input id="lt-name" value={draft.name} placeholder="e.g. Compensatory Off"
                onChange={(e) => setDraft({ ...draft, name: e.target.value, code: draft.codeTouched || draft.id ? draft.code : codeFromName(e.target.value) })} />
            </FormField>
            <FormField label="Code" required={!draft.id} htmlFor="lt-code" error={codeError}
              help={draft.id ? 'The code cannot change once leave has been filed with it.' : 'Used in reports and exports.'}>
              <Input id="lt-code" value={draft.code} disabled={!!draft.id} invalid={!!codeError} maxLength={50}
                onChange={(e) => setDraft({ ...draft, code: e.target.value.toLowerCase(), codeTouched: true })} />
            </FormField>
            <FormField label="Description" htmlFor="lt-desc" className="sm:col-span-2">
              <Input id="lt-desc" value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} />
            </FormField>
            <div className="flex gap-2 sm:col-span-2">
              <Button type="submit" size="sm" loading={save.isPending}
                disabled={!draft.name.trim() || (!draft.id && (!draft.code || !!codeError))}>
                {draft.id ? 'Save' : 'Create'}
              </Button>
              <Button type="button" size="sm" variant="secondary" onClick={() => setDraft(null)}>Cancel</Button>
            </div>
          </form>
        )}

        <ul className="divide-y divide-gray-100">
          {(types ?? []).map((t) => (
            <li key={t.id} className="flex items-center justify-between gap-3 py-2">
              <div className="min-w-0">
                <span className="text-sm font-medium text-gray-900">{t.name}</span>
                <span className="ml-2 text-xs text-gray-500">{t.code}</span>
                {t.is_system && <Badge tone="gray" className="ml-2">Built in</Badge>}
                {t.description && <p className="text-xs text-gray-500 truncate">{t.description}</p>}
              </div>
              <div className="flex gap-1">
                {canEdit && (
                  <Button variant="ghost" size="sm" onClick={() => setDraft({ ...EMPTY, id: t.id, code: t.code, name: t.name, description: t.description ?? '' })}>
                    <Pencil className="h-3.5 w-3.5" /> Edit
                  </Button>
                )}
                {canDelete && (
                  <Button variant="ghost" size="sm" loading={deactivate.isPending && deactivate.variables === t.id}
                    onClick={() => deactivate.mutate(t.id)}>
                    <Power className="h-3.5 w-3.5" /> Switch off
                  </Button>
                )}
              </div>
            </li>
          ))}
        </ul>
      </CardBody>
    </Card>
  )
}
