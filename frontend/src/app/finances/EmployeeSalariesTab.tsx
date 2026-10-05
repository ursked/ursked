'use client'

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { CurrentSalaryRow, SalaryGrade } from '@/types'
import { useToast } from '@/components/ui/Toast'
import { usePermissions } from '@/contexts/PermissionsContext'
import { LoadProblem } from './financeUi'

function today(): string {
  return new Date().toISOString().slice(0, 10)
}

export default function EmployeeSalariesTab() {
  const queryClient = useQueryClient()
  const { showToast } = useToast()
  const { hasPermission } = usePermissions()
  const canEdit = hasPermission('finances', 'edit')

  const [assignFor, setAssignFor] = useState<CurrentSalaryRow | null>(null)
  const [raiseFor, setRaiseFor] = useState<CurrentSalaryRow | null>(null)

  // Only ever mounted for a salary viewer: the Finances page wraps this tab in
  // FiguresOnly, which shows non-viewers the request prompt instead.
  const { data: rows, isLoading, error } = useQuery<CurrentSalaryRow[]>({
    queryKey: ['current-salaries'],
    queryFn: () => api.getCurrentSalaries(),
  })
  const { data: grades } = useQuery<SalaryGrade[]>({
    queryKey: ['salary-grades'],
    queryFn: () => api.getSalaryGrades(),
  })

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['current-salaries'] })

  const withGrade = rows?.filter((r) => r.salary_grade_id) ?? []
  const withoutGrade = rows?.filter((r) => !r.salary_grade_id) ?? []

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-gray-900">Employee Salaries</h2>
          <p className="text-sm text-gray-500">
            Assign a salary grade to each employee and apply raises. Payroll uses the
            salary in effect as of the run’s end date.
          </p>
        </div>
        {withoutGrade.length > 0 && (
          <span className="rounded-full bg-amber-100 px-3 py-1 text-xs font-medium text-amber-800">
            {withoutGrade.length} without a salary
          </span>
        )}
      </div>

      {isLoading ? (
        <p className="text-sm text-gray-500">Loading…</p>
      ) : error ? (
        <LoadProblem error={error} what="employee salaries" />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="min-w-full divide-y divide-gray-200 text-sm">
            <thead className="bg-gray-50 text-left text-xs font-medium uppercase text-gray-500">
              <tr>
                <th className="px-4 py-2">Employee</th>
                <th className="px-4 py-2">Type</th>
                <th className="px-4 py-2">Grade</th>
                <th className="px-4 py-2">Monthly</th>
                <th className="px-4 py-2">Effective</th>
                <th className="px-4 py-2 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {(rows ?? []).map((r) => (
                <tr key={r.employee_id} className={r.salary_grade_id ? '' : 'bg-amber-50/40'}>
                  <td className="px-4 py-2">
                    <div className="font-medium text-gray-900">{r.employee_name}</div>
                    <div className="text-xs text-gray-500">{r.email}</div>
                  </td>
                  <td className="px-4 py-2 text-gray-600">{r.employee_type ?? '—'}</td>
                  <td className="px-4 py-2 text-gray-600">
                    {r.salary_grade_code ? `${r.salary_grade_code} · ${r.salary_grade_name}` : <span className="text-amber-700">Not assigned</span>}
                  </td>
                  <td className="px-4 py-2 text-gray-900">
                    {r.monthly_rate != null ? `₱${r.monthly_rate.toLocaleString()}` : '—'}
                  </td>
                  <td className="px-4 py-2 text-gray-500">{r.effective_date ?? '—'}</td>
                  <td className="px-4 py-2 text-right space-x-2">
                    {canEdit && <button
                      onClick={() => setAssignFor(r)}
                      className="rounded-md bg-brand-600 px-3 py-1 text-xs font-semibold text-white hover:bg-brand-700"
                    >
                      {r.salary_grade_id ? 'Change' : 'Assign'}
                    </button>}
                    {canEdit && r.salary_grade_id ? (
                      <button
                        onClick={() => setRaiseFor(r)}
                        className="rounded-md border border-gray-300 px-3 py-1 text-xs font-semibold text-gray-700 hover:bg-gray-50"
                      >
                        Raise
                      </button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {assignFor && (
        <AssignModal
          row={assignFor}
          grades={grades ?? []}
          onClose={() => setAssignFor(null)}
          onDone={() => {
            setAssignFor(null)
            refresh()
            showToast('Salary assigned', 'success')
          }}
        />
      )}
      {raiseFor && (
        <RaiseModal
          row={raiseFor}
          grades={grades ?? []}
          onClose={() => setRaiseFor(null)}
          onDone={() => {
            setRaiseFor(null)
            refresh()
            showToast('Raise applied', 'success')
          }}
        />
      )}
    </div>
  )
}

function AssignModal({ row, grades, onClose, onDone }: {
  row: CurrentSalaryRow; grades: SalaryGrade[]; onClose: () => void; onDone: () => void
}) {
  const { showToast } = useToast()
  const [gradeId, setGradeId] = useState<number | ''>(row.salary_grade_id ?? '')
  const [effective, setEffective] = useState(today())
  const [override, setOverride] = useState<string>('')

  const mut = useMutation({
    mutationFn: () => api.assignSalary({
      employee_id: row.employee_id,
      salary_grade_id: Number(gradeId),
      effective_date: effective,
      monthly_rate_override: override ? Number(override) : undefined,
    }),
    onSuccess: onDone,
    onError: (e: Error) => showToast(e.message, 'error'),
  })

  return (
    <Modal title={`Assign salary — ${row.employee_name}`} onClose={onClose}>
      <Field label="Salary grade">
        <select className="input" value={gradeId} onChange={(e) => setGradeId(e.target.value ? Number(e.target.value) : '')}>
          <option value="">Select grade</option>
          {grades.map((g) => (
            <option key={g.id} value={g.id}>{g.code} — {g.name} (₱{(g.monthly_rate ?? 0).toLocaleString()})</option>
          ))}
        </select>
      </Field>
      <Field label="Effective date">
        <input type="date" className="input" value={effective} onChange={(e) => setEffective(e.target.value)} />
      </Field>
      {row.effective_date === effective && (
        <p className="text-xs text-amber-700">
          This replaces the assignment already starting on {effective}. The change is recorded in the audit log.
        </p>
      )}
      <Field label="Monthly override (optional)">
        <input type="number" className="input" placeholder="Leave blank to use grade rate" value={override} onChange={(e) => setOverride(e.target.value)} />
      </Field>
      <Actions onClose={onClose} disabled={!gradeId || mut.isPending} onSubmit={() => mut.mutate()} label="Assign" />
    </Modal>
  )
}

function RaiseModal({ row, grades, onClose, onDone }: {
  row: CurrentSalaryRow; grades: SalaryGrade[]; onClose: () => void; onDone: () => void
}) {
  const { showToast } = useToast()
  const [mode, setMode] = useState<'percent' | 'fixed' | 'grade'>('percent')
  const [value, setValue] = useState('')
  const [newGrade, setNewGrade] = useState<number | ''>('')
  const [effective, setEffective] = useState(today())
  const [reason, setReason] = useState('')

  const mut = useMutation({
    mutationFn: () => api.giveRaise({
      employee_ids: [row.employee_id],
      mode,
      value: value ? Number(value) : 0,
      effective_date: effective,
      new_grade_id: mode === 'grade' ? Number(newGrade) : undefined,
      reason: reason || undefined,
    }),
    onSuccess: (res) => {
      const r = res[0]
      if (r?.status === 'skipped') { showToast(`Skipped: ${r.reason}`, 'error'); return }
      onDone()
    },
    onError: (e: Error) => showToast(e.message, 'error'),
  })

  return (
    <Modal title={`Give raise — ${row.employee_name}`} onClose={onClose}>
      <p className="text-xs text-gray-500">
        Current: {row.salary_grade_code ?? '—'} · ₱{row.monthly_rate?.toLocaleString() ?? '—'}
      </p>
      <Field label="Raise type">
        <select className="input" value={mode} onChange={(e) => setMode(e.target.value as 'percent' | 'fixed' | 'grade')}>
          <option value="percent">Percentage (%)</option>
          <option value="fixed">Fixed amount (₱)</option>
          <option value="grade">Move to grade</option>
        </select>
      </Field>
      {mode !== 'grade' ? (
        <Field label={mode === 'percent' ? 'Percent increase' : 'Amount increase (₱)'}>
          <input type="number" className="input" value={value} onChange={(e) => setValue(e.target.value)} />
        </Field>
      ) : (
        <Field label="New grade">
          <select className="input" value={newGrade} onChange={(e) => setNewGrade(e.target.value ? Number(e.target.value) : '')}>
            <option value="">Select grade</option>
            {grades.map((g) => (
              <option key={g.id} value={g.id}>{g.code} — {g.name} (₱{(g.monthly_rate ?? 0).toLocaleString()})</option>
            ))}
          </select>
        </Field>
      )}
      <Field label="Effective date">
        <input type="date" className="input" value={effective} onChange={(e) => setEffective(e.target.value)} />
      </Field>
      <Field label="Reason (optional)">
        <input className="input" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Annual merit increase" />
      </Field>
      <Actions
        onClose={onClose}
        disabled={mut.isPending || (mode === 'grade' ? !newGrade : !value)}
        onSubmit={() => mut.mutate()}
        label="Apply raise"
      />
    </Modal>
  )
}

// ── small shared bits ─────────────────────────────────────────────
function Modal({ title, children, onClose }: { title: string; children: React.ReactNode; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div className="w-full max-w-md rounded-xl bg-white p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <h3 className="mb-4 text-lg font-semibold text-gray-900">{title}</h3>
        <div className="space-y-3">{children}</div>
      </div>
    </div>
  )
}
function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium text-gray-700">{label}</span>
      {children}
    </label>
  )
}
function Actions({ onClose, onSubmit, disabled, label }: { onClose: () => void; onSubmit: () => void; disabled: boolean; label: string }) {
  return (
    <div className="mt-4 flex justify-end gap-2">
      <button onClick={onClose} className="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50">Cancel</button>
      <button onClick={onSubmit} disabled={disabled} className="rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-50">{label}</button>
    </div>
  )
}
