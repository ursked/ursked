'use client'

import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, AlertTriangle, Info } from 'lucide-react'
import DashboardLayout from '@/components/layout/DashboardLayout'
import { api } from '@/lib/api'
import type {
  LeaveBalance,
  LeaveTypeConfig,
  LeaveApplication,
  PaginatedResponse,
} from '@/types'
import { useToast } from '@/components/ui/Toast'
import {
  Button,
  Card,
  CardBody,
  Badge,
  Modal,
  Input,
  Select,
  FormField,
  EmptyState,
} from '@/components/ui'

function useDebounced<T>(value: T, ms: number) {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return v
}

const STATUS_TONE: Record<string, 'yellow' | 'green' | 'red' | 'gray'> = {
  pending: 'yellow',
  approved: 'green',
  rejected: 'red',
  cancelled: 'gray',
}

export default function MyLeavePage() {
  const qc = useQueryClient()
  const { showToast } = useToast()
  const [formOpen, setFormOpen] = useState(false)

  const { data: balance } = useQuery<LeaveBalance>({
    queryKey: ['my-leave-balance'],
    queryFn: () => api.getMyLeaveBalance(),
  })
  const { data: apps } = useQuery<PaginatedResponse<LeaveApplication>>({
    queryKey: ['my-leave-apps'],
    queryFn: () =>
      api.getLeaveApplications({ scope: 'mine' }) as Promise<PaginatedResponse<LeaveApplication>>,
  })

  const cancel = useMutation({
    mutationFn: (id: number) => api.cancelLeaveApplication(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['my-leave-apps'] })
      qc.invalidateQueries({ queryKey: ['my-leave-balance'] })
      showToast('Request cancelled', 'success')
    },
  })

  return (
    <DashboardLayout>
      <div className="mx-auto max-w-2xl space-y-5 pb-20">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-bold text-gray-900">My Leave</h1>
          <Button size="sm" onClick={() => setFormOpen(true)}>
            <Plus className="h-4 w-4" /> File
          </Button>
        </div>

        {/* Balance cards */}
        <div className="grid grid-cols-2 gap-3">
          {(balance?.balances ?? []).map((b) => (
            <Card key={b.leave_type}>
              <CardBody className="p-4">
                <div className="text-2xl font-bold text-purple-700">
                  {b.available_days}
                </div>
                <div className="truncate text-sm font-medium text-gray-700">
                  {b.leave_type_name}
                </div>
                <div className="mt-1 text-xs text-gray-500">
                  {b.used_days} used · {b.pending_days} pending
                </div>
              </CardBody>
            </Card>
          ))}
        </div>

        {/* Applications */}
        <div className="space-y-2">
          <h2 className="text-sm font-semibold text-gray-700">Recent requests</h2>
          {(apps?.items ?? []).length === 0 ? (
            <EmptyState
              icon={Plus}
              title="No leave requests yet"
              description="File your first request with the button above."
            />
          ) : (
            (apps?.items ?? []).map((a) => (
              <Card key={a.id}>
                <CardBody className="flex items-center justify-between p-4">
                  <div>
                    <div className="text-sm font-medium text-gray-900">{a.leave_type}</div>
                    <div className="text-xs text-gray-500">
                      {a.start_date} → {a.end_date} · {a.days_requested}d
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge tone={STATUS_TONE[a.status] ?? 'gray'}>{a.status}</Badge>
                    {a.status === 'pending' && (
                      <Button variant="ghost" size="sm" onClick={() => cancel.mutate(a.id)}>
                        Cancel
                      </Button>
                    )}
                  </div>
                </CardBody>
              </Card>
            ))
          )}
        </div>
      </div>

      <FileLeaveModal open={formOpen} onOpenChange={setFormOpen} />
    </DashboardLayout>
  )
}

function FileLeaveModal({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
}) {
  const qc = useQueryClient()
  const { showToast } = useToast()
  const [form, setForm] = useState({
    leave_type: '',
    start_date: '',
    end_date: '',
    reason: '',
  })

  const { data: leaveTypes } = useQuery<LeaveTypeConfig[]>({
    queryKey: ['leave-types'],
    queryFn: () => api.getLeaveTypes(),
  })

  const debouncedForm = useDebounced(form, 400)
  const { data: precheck } = useQuery({
    queryKey: ['leave-precheck', debouncedForm],
    queryFn: () =>
      api.precheckLeave({
        leave_type: debouncedForm.leave_type,
        start_date: debouncedForm.start_date,
        end_date: debouncedForm.end_date,
      }),
    enabled:
      !!debouncedForm.leave_type &&
      !!debouncedForm.start_date &&
      !!debouncedForm.end_date &&
      debouncedForm.end_date >= debouncedForm.start_date,
  })

  const submit = useMutation({
    mutationFn: () => api.createLeaveApplication(form),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['my-leave-apps'] })
      qc.invalidateQueries({ queryKey: ['my-leave-balance'] })
      showToast('Leave request filed', 'success')
      onOpenChange(false)
      setForm({ leave_type: '', start_date: '', end_date: '', reason: '' })
    },
    onError: (e: unknown) => {
      // Surface structured block violations from the backend.
      const msg = (e as Error)?.message ?? 'Could not file request'
      showToast(msg, 'error')
    },
  })

  const blocked = precheck ? !precheck.allowed : false

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title="File leave request"
      footer={
        <>
          <Button variant="secondary" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            onClick={() => submit.mutate()}
            loading={submit.isPending}
            disabled={blocked || !form.leave_type || !form.start_date || !form.end_date || !form.reason}
          >
            Submit
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <FormField label="Leave type" required>
          <Select
            value={form.leave_type}
            onChange={(e) => setForm({ ...form, leave_type: e.target.value })}
          >
            <option value="">Select…</option>
            {(leaveTypes ?? [])
              .filter((lt) => lt.is_active)
              .map((lt) => (
                <option key={lt.code} value={lt.code}>
                  {lt.name}
                </option>
              ))}
          </Select>
        </FormField>
        <div className="grid grid-cols-2 gap-3">
          <FormField label="From" required>
            <Input
              type="date"
              value={form.start_date}
              onChange={(e) => setForm({ ...form, start_date: e.target.value })}
            />
          </FormField>
          <FormField label="To" required>
            <Input
              type="date"
              value={form.end_date}
              onChange={(e) => setForm({ ...form, end_date: e.target.value })}
            />
          </FormField>
        </div>
        <FormField label="Reason" required>
          <Input
            value={form.reason}
            onChange={(e) => setForm({ ...form, reason: e.target.value })}
            placeholder="Brief reason"
          />
        </FormField>

        {/* Live enforcement feedback from the precheck endpoint */}
        {precheck && precheck.violations.length > 0 && (
          <div className="space-y-1 rounded-lg bg-red-50 p-3">
            {precheck.violations.map((v, i) => (
              <div key={i} className="flex gap-2 text-sm text-red-700">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                <span>{v.message}</span>
              </div>
            ))}
          </div>
        )}
        {precheck && precheck.warnings.length > 0 && (
          <div className="space-y-1 rounded-lg bg-yellow-50 p-3">
            {precheck.warnings.map((v, i) => (
              <div key={i} className="flex gap-2 text-sm text-yellow-800">
                <Info className="mt-0.5 h-4 w-4 shrink-0" />
                <span>{v.message}</span>
              </div>
            ))}
          </div>
        )}
        {precheck && (
          <p className="text-xs text-gray-500">
            {precheck.days_requested} business day(s) requested.
          </p>
        )}
      </div>
    </Modal>
  )
}
