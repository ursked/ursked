'use client'

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import DashboardLayout from '@/components/layout/DashboardLayout'
import { useAuth } from '@/contexts/AuthContext'
import { api } from '@/lib/api'
import { CustomFieldValue, EmployeeTypeConfig, ScheduleFormatConfig, User } from '@/types'
import { useToast } from '@/components/ui/Toast'
import { CustomFieldInput, formatCustomValue, useEmployeeFieldConfig } from '@/app/employees/customFields'
import { passwordProblem } from '@/app/auth/passwordRule'
import SecuritySection from './SecuritySection'

const inputClass =
  'block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-purple-500 focus:ring-purple-500 focus:outline-none'

export default function ProfilePage() {
  const { user, refreshUser } = useAuth()
  const queryClient = useQueryClient()
  const { showToast } = useToast()

  // The full record, with the custom fields this employee may see (the
  // session's /auth/me copy does not carry them).
  const { data: me } = useQuery<User>({
    queryKey: ['my-profile'],
    queryFn: () => api.getUser(user!.id),
    enabled: !!user,
  })
  const { data: fieldConfig } = useEmployeeFieldConfig()
  const customDefs = fieldConfig?.fields ?? []

  const [editing, setEditing] = useState(false)
  const [form, setForm] = useState({
    first_name: user?.first_name ?? '',
    last_name: user?.last_name ?? '',
    contact_number: user?.contact_number ?? '',
  })
  const [custom, setCustom] = useState<Record<string, CustomFieldValue>>({})

  const [showPasswordForm, setShowPasswordForm] = useState(false)
  const [passwordForm, setPasswordForm] = useState({
    current_password: '',
    new_password: '',
    confirm_password: '',
  })

  const updateMutation = useMutation({
    mutationFn: (data: Record<string, unknown>) => api.updateMyProfile(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['current-user'] })
      queryClient.invalidateQueries({ queryKey: ['my-profile'] })
      refreshUser?.()
      setEditing(false)
      showToast('Profile updated', 'success')
    },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  const { data: employeeTypes } = useQuery<EmployeeTypeConfig[]>({
    queryKey: ['employee-types'],
    queryFn: () => api.getEmployeeTypes(),
  })

  const { data: scheduleFormats } = useQuery<ScheduleFormatConfig[]>({
    queryKey: ['schedule-formats'],
    queryFn: () => api.getScheduleFormats(),
  })

  const passwordMutation = useMutation({
    mutationFn: (data: { current_password: string; new_password: string }) =>
      api.changePassword(data),
    onSuccess: () => {
      setShowPasswordForm(false)
      setPasswordForm({ current_password: '', new_password: '', confirm_password: '' })
      showToast('Password changed', 'success')
    },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  const editableDefs = customDefs.filter((d) => d.visibility === 'employee_edit')
  const myValues = me?.custom_fields ?? {}

  const handleProfileSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!form.first_name.trim() || !form.last_name.trim()) {
      showToast('First and last name cannot be empty', 'error')
      return
    }
    const data: Record<string, unknown> = {
      first_name: form.first_name.trim(),
      last_name: form.last_name.trim(),
      contact_number: form.contact_number.trim() || null,
    }
    const changed: Record<string, CustomFieldValue> = {}
    for (const d of editableDefs) {
      const now = custom[d.key] ?? null
      if (now !== (myValues[d.key] ?? null)) changed[d.key] = now
    }
    if (Object.keys(changed).length) data.custom_fields = changed
    updateMutation.mutate(data)
  }

  const newPasswordProblem = passwordForm.new_password ? passwordProblem(passwordForm.new_password) : null

  const handlePasswordSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (passwordForm.new_password !== passwordForm.confirm_password) {
      showToast('Passwords do not match', 'error')
      return
    }
    // The same rule the server enforces: 8+ characters, upper and lower case, a digit.
    const problem = passwordProblem(passwordForm.new_password)
    if (problem) {
      showToast(`New password: ${problem}`, 'error')
      return
    }
    passwordMutation.mutate({
      current_password: passwordForm.current_password,
      new_password: passwordForm.new_password,
    })
  }

  const startEditing = () => {
    setForm({
      first_name: me?.first_name ?? user?.first_name ?? '',
      last_name: me?.last_name ?? user?.last_name ?? '',
      contact_number: me?.contact_number ?? user?.contact_number ?? '',
    })
    setCustom({ ...myValues })
    setEditing(true)
  }

  if (!user) return null

  const profile = me ?? user
  const roleBadges = user.roles?.map((r) => r.role?.name ?? r.role?.code).filter(Boolean) ?? []

  return (
    <DashboardLayout>
      <div className="max-w-3xl mx-auto space-y-6">
        {/* Page header */}
        <div>
          <h1 className="text-2xl font-bold text-gray-900">My Profile</h1>
          <p className="mt-1 text-sm text-gray-500">View and update your personal information.</p>
        </div>

        {/* Profile card */}
        <div className="bg-white border border-gray-200 rounded-xl shadow-sm">
          <div className="px-6 py-5 border-b border-gray-200 flex items-center justify-between gap-4">
            <div className="flex items-center gap-4 min-w-0">
              <div className="w-14 h-14 rounded-full bg-purple-600 flex items-center justify-center text-white text-xl font-semibold flex-shrink-0">
                {profile.first_name?.[0]}{profile.last_name?.[0]}
              </div>
              <div className="min-w-0">
                <h2 className="text-lg font-semibold text-gray-900 truncate">
                  {profile.first_name} {profile.last_name}
                </h2>
                <p className="text-sm text-gray-500 truncate">{profile.email}</p>
              </div>
            </div>
            {!editing && (
              <button
                type="button"
                onClick={startEditing}
                className="inline-flex items-center gap-1.5 rounded-md bg-purple-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-purple-700 transition-colors"
              >
                Edit
              </button>
            )}
          </div>

          <div className="px-6 py-5">
            {editing ? (
              <form onSubmit={handleProfileSubmit} className="space-y-4">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div>
                    <label htmlFor="p-first" className="block text-sm font-medium text-gray-700 mb-1">First Name</label>
                    <input id="p-first" type="text" required maxLength={100} value={form.first_name}
                      onChange={(e) => setForm((p) => ({ ...p, first_name: e.target.value }))} className={inputClass} />
                  </div>
                  <div>
                    <label htmlFor="p-last" className="block text-sm font-medium text-gray-700 mb-1">Last Name</label>
                    <input id="p-last" type="text" required maxLength={100} value={form.last_name}
                      onChange={(e) => setForm((p) => ({ ...p, last_name: e.target.value }))} className={inputClass} />
                  </div>
                  <div>
                    <label htmlFor="p-contact" className="block text-sm font-medium text-gray-700 mb-1">Contact Number</label>
                    <input id="p-contact" type="text" maxLength={50} value={form.contact_number}
                      onChange={(e) => setForm((p) => ({ ...p, contact_number: e.target.value }))} placeholder="Optional" className={inputClass} />
                  </div>
                  {/* Job title is HR data: shown, not editable. The field used to be
                      editable here and the backend silently dropped it. */}
                  <div>
                    <span className="block text-sm font-medium text-gray-700 mb-1">Job Title</span>
                    <p className="px-3 py-2 text-sm text-gray-700 bg-gray-50 rounded-md border border-gray-200">
                      {profile.job_title || 'Not set'}
                    </p>
                    <p className="mt-1 text-xs text-gray-500">Set by HR. Ask them if it needs changing.</p>
                  </div>
                  {editableDefs.map((d) => (
                    <CustomFieldInput
                      key={d.key}
                      def={d}
                      value={custom[d.key]}
                      onChange={(v) => setCustom((prev) => ({ ...prev, [d.key]: v }))}
                    />
                  ))}
                </div>
                <div className="flex items-center gap-3 pt-2">
                  <button
                    type="submit"
                    disabled={updateMutation.isPending}
                    className="inline-flex items-center rounded-md bg-purple-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                  >
                    {updateMutation.isPending ? 'Saving...' : 'Save Changes'}
                  </button>
                  <button
                    type="button"
                    onClick={() => setEditing(false)}
                    className="inline-flex items-center rounded-md bg-white px-4 py-2 text-sm font-semibold text-gray-700 shadow-sm ring-1 ring-inset ring-gray-300 hover:bg-gray-50 transition-colors"
                  >
                    Cancel
                  </button>
                </div>
              </form>
            ) : (
              <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-4">
                <div>
                  <dt className="text-sm font-medium text-gray-500">Email</dt>
                  <dd className="mt-1 text-sm text-gray-900 break-all">{profile.email}</dd>
                </div>
                <div>
                  <dt className="text-sm font-medium text-gray-500">Username</dt>
                  <dd className="mt-1 text-sm text-gray-900 break-all">{profile.username}</dd>
                </div>
                <div>
                  <dt className="text-sm font-medium text-gray-500">Contact Number</dt>
                  <dd className="mt-1 text-sm text-gray-900">{profile.contact_number || '--'}</dd>
                </div>
                <div>
                  <dt className="text-sm font-medium text-gray-500">Job Title</dt>
                  <dd className="mt-1 text-sm text-gray-900">{profile.job_title || '--'}</dd>
                </div>
                <div>
                  <dt className="text-sm font-medium text-gray-500">Employee Type</dt>
                  <dd className="mt-1 text-sm text-gray-900">{profile.employee_type ? (employeeTypes?.find((t) => t.code === profile.employee_type)?.name ?? profile.employee_type.replace(/_/g, ' ')) : '--'}</dd>
                </div>
                <div>
                  <dt className="text-sm font-medium text-gray-500">Schedule Format</dt>
                  <dd className="mt-1 text-sm text-gray-900">{profile.schedule_format ? (scheduleFormats?.find((f) => f.code === profile.schedule_format)?.name ?? profile.schedule_format.replace(/_/g, ' ')) : '--'}</dd>
                </div>
                <div>
                  <dt className="text-sm font-medium text-gray-500">Hiring Date</dt>
                  <dd className="mt-1 text-sm text-gray-900">{profile.hiring_date || '--'}</dd>
                </div>
                {me?.org_node_name && (
                  <div>
                    <dt className="text-sm font-medium text-gray-500">Organization Unit</dt>
                    <dd className="mt-1 text-sm text-gray-900">{me.org_node_name}</dd>
                  </div>
                )}
                {me?.reports_to_name && (
                  <div>
                    <dt className="text-sm font-medium text-gray-500">Line Manager</dt>
                    <dd className="mt-1 text-sm text-gray-900">{me.reports_to_name}</dd>
                  </div>
                )}
                {customDefs.map((d) => (
                  <div key={d.key}>
                    <dt className="text-sm font-medium text-gray-500">{d.label}</dt>
                    <dd className="mt-1 text-sm text-gray-900">{formatCustomValue(d, myValues[d.key]) || '--'}</dd>
                  </div>
                ))}
                <div className="sm:col-span-2">
                  <dt className="text-sm font-medium text-gray-500">Roles</dt>
                  <dd className="mt-1 flex flex-wrap gap-1.5">
                    {roleBadges.length > 0 ? roleBadges.map((r) => (
                      <span key={r} className="inline-flex items-center rounded-full bg-purple-100 text-purple-800 px-2.5 py-0.5 text-xs font-medium">
                        {r}
                      </span>
                    )) : <span className="text-sm text-gray-500">--</span>}
                  </dd>
                </div>
              </dl>
            )}
          </div>
        </div>

        {/* Change Password */}
        <div className="bg-white border border-gray-200 rounded-xl shadow-sm">
          <div className="px-6 py-5 border-b border-gray-200 flex items-center justify-between gap-4">
            <div>
              <h3 className="text-lg font-semibold text-gray-900">Password</h3>
              <p className="text-sm text-gray-500">Changing it signs you out on every other device.</p>
            </div>
            {!showPasswordForm && (
              <button
                type="button"
                onClick={() => setShowPasswordForm(true)}
                className="inline-flex items-center gap-1.5 rounded-md bg-white px-4 py-2 text-sm font-semibold text-gray-700 shadow-sm ring-1 ring-inset ring-gray-300 hover:bg-gray-50 transition-colors whitespace-nowrap"
              >
                Change Password
              </button>
            )}
          </div>

          {showPasswordForm && (
            <div className="px-6 py-5">
              <form onSubmit={handlePasswordSubmit} className="space-y-4 max-w-md">
                <div>
                  <label htmlFor="pw-current" className="block text-sm font-medium text-gray-700 mb-1">Current Password</label>
                  <input id="pw-current" type="password" required autoComplete="current-password" value={passwordForm.current_password}
                    onChange={(e) => setPasswordForm((p) => ({ ...p, current_password: e.target.value }))} className={inputClass} />
                </div>
                <div>
                  <label htmlFor="pw-new" className="block text-sm font-medium text-gray-700 mb-1">New Password</label>
                  <input id="pw-new" type="password" required autoComplete="new-password" aria-describedby="pw-new-help" value={passwordForm.new_password}
                    onChange={(e) => setPasswordForm((p) => ({ ...p, new_password: e.target.value }))} className={inputClass} />
                  <p id="pw-new-help" className={`mt-1 text-xs ${newPasswordProblem ? 'text-red-700' : 'text-gray-500'}`}>
                    {newPasswordProblem ?? 'At least 8 characters with an uppercase letter, a lowercase letter and a digit.'}
                  </p>
                </div>
                <div>
                  <label htmlFor="pw-confirm" className="block text-sm font-medium text-gray-700 mb-1">Confirm New Password</label>
                  <input id="pw-confirm" type="password" required autoComplete="new-password" value={passwordForm.confirm_password}
                    onChange={(e) => setPasswordForm((p) => ({ ...p, confirm_password: e.target.value }))} className={inputClass} />
                </div>
                <div className="flex items-center gap-3 pt-2">
                  <button
                    type="submit"
                    disabled={passwordMutation.isPending}
                    className="inline-flex items-center rounded-md bg-purple-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                  >
                    {passwordMutation.isPending ? 'Changing...' : 'Change Password'}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setShowPasswordForm(false)
                      setPasswordForm({ current_password: '', new_password: '', confirm_password: '' })
                    }}
                    className="inline-flex items-center rounded-md bg-white px-4 py-2 text-sm font-semibold text-gray-700 shadow-sm ring-1 ring-inset ring-gray-300 hover:bg-gray-50 transition-colors"
                  >
                    Cancel
                  </button>
                </div>
              </form>
            </div>
          )}
        </div>

        <SecuritySection />
      </div>
    </DashboardLayout>
  )
}
