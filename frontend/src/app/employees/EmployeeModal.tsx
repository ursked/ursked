'use client';

import { useState, useEffect, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { User, RoleCode, EmployeeTypeConfig, ScheduleFormatConfig, PermissionMatrixEntry, RolePermissionEntry } from '@/types';
import { getRoleCodes } from '@/lib/roles';

interface EmployeeModalProps {
  employee?: User;
  onClose: () => void;
  onSaved: () => void;
}

const ROLE_OPTIONS: { code: RoleCode; label: string; description: string }[] = [
  { code: 'tenant_admin', label: 'Administrator', description: 'Full tenant access, settings, and billing' },
  { code: 'hr', label: 'HR', description: 'Payroll, onboarding, employee records access' },
  { code: 'finance', label: 'Finance', description: 'Payroll management, salary grades, deductions, and payroll processing' },
  { code: 'manager', label: 'Manager', description: 'Manage direct and indirect reports' },
  { code: 'leave_approver', label: 'Leave Approver', description: 'Approve leave applications in their chain' },
  { code: 'schedule_editor', label: 'Schedule Editor', description: 'Create and edit schedules' },
];

const MODULES: { key: string; label: string }[] = [
  { key: 'employees', label: 'Employees' },
  { key: 'organization', label: 'Org' },
  { key: 'schedules', label: 'Schedules' },
  { key: 'leave', label: 'Leave' },
  { key: 'finances', label: 'Finances' },
  { key: 'settings', label: 'Settings' },
  { key: 'reports', label: 'Reports' },
];

const ACTIONS: { key: keyof Pick<RolePermissionEntry, 'can_view' | 'can_create' | 'can_edit' | 'can_delete'>; label: string }[] = [
  { key: 'can_view', label: 'V' },
  { key: 'can_create', label: 'C' },
  { key: 'can_edit', label: 'E' },
  { key: 'can_delete', label: 'D' },
];

// Employee types and schedule formats are now fetched from API

export default function EmployeeModal({ employee, onClose, onSaved }: EmployeeModalProps) {
  const isEdit = !!employee;

  // Basic info
  const [firstName, setFirstName] = useState(employee?.first_name ?? '');
  const [lastName, setLastName] = useState(employee?.last_name ?? '');
  const [email, setEmail] = useState(employee?.email ?? '');
  const [password, setPassword] = useState('');
  const [sendInvite, setSendInvite] = useState(true);
  const [contactNumber, setContactNumber] = useState(employee?.contact_number ?? '');

  // Employment info
  const [personnelNumber, setPersonnelNumber] = useState(employee?.personnel_number ?? '');
  const [jobTitle, setJobTitle] = useState(employee?.job_title ?? '');
  const [rank, setRank] = useState(employee?.rank ?? '');
  const [divDepartment, setDivDepartment] = useState(employee?.div_department ?? '');
  const [hiringDate, setHiringDate] = useState(employee?.hiring_date ?? '');
  const [employeeType, setEmployeeType] = useState(employee?.employee_type ?? '');
  const [scheduleFormat, setScheduleFormat] = useState(employee?.schedule_format ?? '');
  const [typecode, setTypecode] = useState(employee?.typecode ?? '');
  const [idNumber, setIdNumber] = useState(employee?.id_number ?? '');

  // Roles
  const [selectedRoles, setSelectedRoles] = useState<string[]>(() => {
    if (employee) {
      return getRoleCodes(employee).filter((c) => c !== 'employee');
    }
    return [];
  });

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [tab, setTab] = useState<'basic' | 'employment' | 'roles'>('basic');

  const { data: employeeTypes } = useQuery<EmployeeTypeConfig[]>({
    queryKey: ['employee-types'],
    queryFn: () => api.getEmployeeTypes(),
  });

  const { data: scheduleFormats } = useQuery<ScheduleFormatConfig[]>({
    queryKey: ['schedule-formats'],
    queryFn: () => api.getScheduleFormats(),
  });

  const { data: permissionMatrix } = useQuery({
    queryKey: ['permission-matrix'],
    queryFn: () => api.getPermissionMatrix(),
    select: (data) => data.entries,
  });

  // Build lookup: roleCode -> modules permissions
  const permsByRole = useMemo(() => {
    const map: Record<string, Record<string, RolePermissionEntry>> = {};
    if (permissionMatrix) {
      for (const entry of permissionMatrix) {
        map[entry.role_code] = entry.modules;
      }
    }
    return map;
  }, [permissionMatrix]);

  // Compute effective (merged) permissions from selected roles
  const effectivePerms = useMemo(() => {
    const merged: Record<string, { can_view: boolean; can_create: boolean; can_edit: boolean; can_delete: boolean; view_salary: boolean }> = {};
    for (const mod of MODULES) {
      merged[mod.key] = { can_view: false, can_create: false, can_edit: false, can_delete: false, view_salary: false };
    }
    for (const roleCode of selectedRoles) {
      const roleModules = permsByRole[roleCode];
      if (!roleModules) continue;
      for (const mod of MODULES) {
        const p = roleModules[mod.key];
        if (!p) continue;
        merged[mod.key].can_view = merged[mod.key].can_view || p.can_view;
        merged[mod.key].can_create = merged[mod.key].can_create || p.can_create;
        merged[mod.key].can_edit = merged[mod.key].can_edit || p.can_edit;
        merged[mod.key].can_delete = merged[mod.key].can_delete || p.can_delete;
        if (p.extra_permissions?.view_salary) {
          merged[mod.key].view_salary = true;
        }
      }
    }
    return merged;
  }, [selectedRoles, permsByRole]);

  const hasAnyEffectivePermission = selectedRoles.length > 0;

  const toggleRole = (code: string) => {
    setSelectedRoles((prev) =>
      prev.includes(code) ? prev.filter((c) => c !== code) : [...prev, code]
    );
  };

  const canSubmit = firstName && lastName && email && (isEdit || sendInvite || password.length >= 8);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      const data: Record<string, unknown> = {
        first_name: firstName,
        last_name: lastName,
        email,
        contact_number: contactNumber || null,
        personnel_number: personnelNumber || null,
        job_title: jobTitle || null,
        rank: rank || null,
        div_department: divDepartment || null,
        hiring_date: hiringDate || null,
        employee_type: employeeType || null,
        schedule_format: scheduleFormat || null,
        role_codes: ['employee', ...selectedRoles],
      };

      if (isEdit) {
        await api.updateUser(employee.id, data);
      } else {
        data.send_invite = sendInvite;
        if (!sendInvite) {
          data.password = password;
        }
        await api.createUser(data);
      }
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Operation failed');
    } finally {
      setLoading(false);
    }
  };

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto">
      <div className="fixed inset-0 bg-black/50" onClick={onClose} />
      <div className="relative min-h-full flex items-center justify-center p-4">
        <div className="relative bg-white rounded-xl shadow-xl w-full max-w-2xl max-h-[90vh] overflow-hidden flex flex-col">
          {/* Header */}
          <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
            <h2 className="text-lg font-semibold text-gray-900">
              {isEdit ? 'Edit Employee' : 'Add New Employee'}
            </h2>
            <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          {/* Tabs */}
          <div className="flex border-b border-gray-100 px-6">
            {(['basic', 'employment', 'roles'] as const).map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors ${
                  tab === t
                    ? 'border-purple-600 text-purple-600'
                    : 'border-transparent text-gray-500 hover:text-gray-700'
                }`}
              >
                {t === 'basic' ? 'Basic Info' : t === 'employment' ? 'Employment' : 'Roles'}
              </button>
            ))}
          </div>

          {/* Body */}
          <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto px-6 py-4">
            {error && (
              <div className="mb-4 bg-red-50 border border-red-200 rounded-lg p-3">
                <p className="text-sm text-red-700">{error}</p>
              </div>
            )}

            {/* Basic Info Tab */}
            {tab === 'basic' && (
              <div className="space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">First Name *</label>
                    <input
                      type="text"
                      value={firstName}
                      onChange={(e) => setFirstName(e.target.value)}
                      required
                      className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-transparent outline-none text-sm"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">Last Name *</label>
                    <input
                      type="text"
                      value={lastName}
                      onChange={(e) => setLastName(e.target.value)}
                      required
                      className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-transparent outline-none text-sm"
                    />
                  </div>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Email *</label>
                  <input
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                    className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-transparent outline-none text-sm"
                  />
                </div>

                {!isEdit && (
                  <div className="space-y-3">
                    <label className="block text-sm font-medium text-gray-700">Account Setup</label>
                    <div className="flex gap-3">
                      <label
                        className={`flex-1 flex items-center gap-2 p-3 rounded-lg border cursor-pointer transition-colors ${
                          sendInvite ? 'border-purple-300 bg-purple-50' : 'border-gray-200 hover:bg-gray-50'
                        }`}
                      >
                        <input
                          type="radio"
                          name="accountSetup"
                          checked={sendInvite}
                          onChange={() => setSendInvite(true)}
                          className="w-4 h-4 text-purple-600 border-gray-300 focus:ring-purple-500"
                        />
                        <div>
                          <p className="text-sm font-medium text-gray-900">Send Invite Email</p>
                          <p className="text-xs text-gray-500">User sets their own password</p>
                        </div>
                      </label>
                      <label
                        className={`flex-1 flex items-center gap-2 p-3 rounded-lg border cursor-pointer transition-colors ${
                          !sendInvite ? 'border-purple-300 bg-purple-50' : 'border-gray-200 hover:bg-gray-50'
                        }`}
                      >
                        <input
                          type="radio"
                          name="accountSetup"
                          checked={!sendInvite}
                          onChange={() => setSendInvite(false)}
                          className="w-4 h-4 text-purple-600 border-gray-300 focus:ring-purple-500"
                        />
                        <div>
                          <p className="text-sm font-medium text-gray-900">Set Password Manually</p>
                          <p className="text-xs text-gray-500">You create the password</p>
                        </div>
                      </label>
                    </div>
                    {!sendInvite && (
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">Password *</label>
                        <input
                          type="password"
                          value={password}
                          onChange={(e) => setPassword(e.target.value)}
                          required
                          minLength={8}
                          placeholder="Minimum 8 characters"
                          className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-transparent outline-none text-sm"
                        />
                      </div>
                    )}
                    {sendInvite && (
                      <div className="bg-blue-50 border border-blue-200 rounded-lg p-3">
                        <p className="text-xs text-blue-700">
                          An activation email will be sent to the employee. They will set their own password when they activate their account.
                        </p>
                      </div>
                    )}
                  </div>
                )}

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Contact Number</label>
                  <input
                    type="text"
                    value={contactNumber}
                    onChange={(e) => setContactNumber(e.target.value)}
                    placeholder="e.g. +63 917 123 4567"
                    className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-transparent outline-none text-sm"
                  />
                </div>
              </div>
            )}

            {/* Employment Tab */}
            {tab === 'employment' && (
              <div className="space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">Personnel Number</label>
                    <input
                      type="text"
                      value={personnelNumber}
                      onChange={(e) => setPersonnelNumber(e.target.value)}
                      className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-transparent outline-none text-sm"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">Typecode</label>
                    <input
                      type="text"
                      value={typecode}
                      onChange={(e) => setTypecode(e.target.value)}
                      className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-transparent outline-none text-sm"
                    />
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">ID Number</label>
                    <input
                      type="text"
                      value={idNumber}
                      onChange={(e) => setIdNumber(e.target.value)}
                      className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-transparent outline-none text-sm"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">Hiring Date</label>
                    <input
                      type="date"
                      value={hiringDate}
                      onChange={(e) => setHiringDate(e.target.value)}
                      className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-transparent outline-none text-sm"
                    />
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">Job Title</label>
                    <input
                      type="text"
                      value={jobTitle}
                      onChange={(e) => setJobTitle(e.target.value)}
                      className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-transparent outline-none text-sm"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">Rank</label>
                    <input
                      type="text"
                      value={rank}
                      onChange={(e) => setRank(e.target.value)}
                      className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-transparent outline-none text-sm"
                    />
                  </div>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Division / Department</label>
                  <input
                    type="text"
                    value={divDepartment}
                    onChange={(e) => setDivDepartment(e.target.value)}
                    className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-transparent outline-none text-sm"
                  />
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">Employee Type</label>
                    <select
                      value={employeeType}
                      onChange={(e) => setEmployeeType(e.target.value)}
                      className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-transparent outline-none text-sm bg-white"
                    >
                      <option value="">Select type</option>
                      {(employeeTypes ?? []).map((t) => (
                        <option key={t.code} value={t.code}>{t.name}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">Schedule Format</label>
                    <select
                      value={scheduleFormat}
                      onChange={(e) => setScheduleFormat(e.target.value)}
                      className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-transparent outline-none text-sm bg-white"
                    >
                      <option value="">Select format</option>
                      {(scheduleFormats ?? []).map((f) => (
                        <option key={f.code} value={f.code}>{f.name}</option>
                      ))}
                    </select>
                  </div>
                </div>
              </div>
            )}

            {/* Roles Tab */}
            {tab === 'roles' && (
              <div className="space-y-4">
                <p className="text-sm text-gray-500">
                  Every employee automatically has the base &quot;Employee&quot; role.
                  Select additional roles below to grant specific permissions.
                </p>
                <div className="space-y-2">
                  {ROLE_OPTIONS.map((role) => {
                    const isSelected = selectedRoles.includes(role.code);
                    const rolePerms = permsByRole[role.code];
                    const isTenantAdmin = role.code === 'tenant_admin';
                    const hasViewSalary = isTenantAdmin || (rolePerms && Object.values(rolePerms).some(p => p.extra_permissions?.view_salary));

                    return (
                      <div
                        key={role.code}
                        className={`rounded-lg border transition-colors ${
                          isSelected ? 'border-purple-300 bg-purple-50/50' : 'border-gray-200 hover:bg-gray-50'
                        }`}
                      >
                        <label className="flex items-center gap-3 p-3 cursor-pointer">
                          <input
                            type="checkbox"
                            checked={isSelected}
                            onChange={() => toggleRole(role.code)}
                            className="w-4 h-4 text-purple-600 border-gray-300 rounded focus:ring-purple-500"
                          />
                          <div className="flex-1 min-w-0">
                            <p className="text-sm font-medium text-gray-900">{role.label}</p>
                            <p className="text-xs text-gray-500">{role.description}</p>
                          </div>
                        </label>

                        {/* Inline permission grid — shown when role is selected */}
                        {isSelected && rolePerms && (
                          <div className="px-3 pb-3 pt-0">
                            <div className="bg-white rounded-lg border border-gray-100 overflow-hidden">
                              <table className="w-full text-[10px]">
                                <thead>
                                  <tr className="bg-gray-50">
                                    <th className="px-1.5 py-1 text-left font-medium text-gray-500 w-[60px]"></th>
                                    {MODULES.map(m => (
                                      <th key={m.key} className="px-1 py-1 text-center font-medium text-gray-500">{m.label}</th>
                                    ))}
                                    <th className="px-1 py-1 text-center font-medium text-gray-500">Salary</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {ACTIONS.map(action => (
                                    <tr key={action.key} className="border-t border-gray-50">
                                      <td className="px-1.5 py-0.5 font-medium text-gray-500">{action.label === 'V' ? 'View' : action.label === 'C' ? 'Create' : action.label === 'E' ? 'Edit' : 'Delete'}</td>
                                      {MODULES.map(m => {
                                        const granted = isTenantAdmin || rolePerms[m.key]?.[action.key];
                                        return (
                                          <td key={m.key} className="px-1 py-0.5 text-center">
                                            {granted ? (
                                              <span className="inline-block w-3.5 h-3.5 rounded-full bg-green-500 text-white text-[8px] leading-[14px] font-bold">{action.label}</span>
                                            ) : (
                                              <span className="inline-block w-3.5 h-3.5 rounded-full bg-gray-200 text-gray-400 text-[8px] leading-[14px]">{action.label}</span>
                                            )}
                                          </td>
                                        );
                                      })}
                                      {action.key === 'can_view' ? (
                                        <td className="px-1 py-0.5 text-center" rowSpan={4}>
                                          {hasViewSalary ? (
                                            <span className="text-green-600 font-bold text-xs">&#10003;</span>
                                          ) : (
                                            <span className="text-gray-500 text-xs">&#8212;</span>
                                          )}
                                        </td>
                                      ) : null}
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>

                {/* Effective Permissions Summary */}
                {hasAnyEffectivePermission && (
                  <div className="mt-4 bg-purple-50 border border-purple-200 rounded-lg p-4">
                    <div className="mb-2">
                      <h4 className="text-sm font-semibold text-purple-900">Effective Permissions</h4>
                      <p className="text-xs text-purple-600">
                        Combined access from: {selectedRoles.map(c => ROLE_OPTIONS.find(r => r.code === c)?.label).filter(Boolean).join(', ')}
                      </p>
                    </div>
                    <div className="bg-white rounded-lg border border-purple-100 overflow-hidden">
                      <table className="w-full text-[10px]">
                        <thead>
                          <tr className="bg-purple-50/50">
                            <th className="px-1.5 py-1 text-left font-medium text-purple-700 w-[60px]"></th>
                            {MODULES.map(m => (
                              <th key={m.key} className="px-1 py-1 text-center font-medium text-purple-700">{m.label}</th>
                            ))}
                            <th className="px-1 py-1 text-center font-medium text-purple-700">Salary</th>
                          </tr>
                        </thead>
                        <tbody>
                          {ACTIONS.map(action => (
                            <tr key={action.key} className="border-t border-purple-50">
                              <td className="px-1.5 py-0.5 font-medium text-purple-600">{action.label === 'V' ? 'View' : action.label === 'C' ? 'Create' : action.label === 'E' ? 'Edit' : 'Delete'}</td>
                              {MODULES.map(m => {
                                const granted = effectivePerms[m.key]?.[action.key];
                                return (
                                  <td key={m.key} className="px-1 py-0.5 text-center">
                                    {granted ? (
                                      <span className="inline-block w-3.5 h-3.5 rounded-full bg-purple-600 text-white text-[8px] leading-[14px] font-bold">{action.label}</span>
                                    ) : (
                                      <span className="inline-block w-3.5 h-3.5 rounded-full bg-gray-200 text-gray-400 text-[8px] leading-[14px]">{action.label}</span>
                                    )}
                                  </td>
                                );
                              })}
                              {action.key === 'can_view' ? (
                                <td className="px-1 py-0.5 text-center" rowSpan={4}>
                                  {Object.values(effectivePerms).some(p => p.view_salary) ? (
                                    <span className="text-purple-600 font-bold text-xs">&#10003;</span>
                                  ) : (
                                    <span className="text-gray-500 text-xs">&#8212;</span>
                                  )}
                                </td>
                              ) : null}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </div>
            )}
          </form>

          {/* Footer */}
          <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-gray-100 bg-gray-50">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2.5 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleSubmit}
              disabled={!canSubmit || loading}
              className="px-4 py-2.5 text-sm font-medium text-white bg-purple-600 rounded-lg hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
            >
              {loading && (
                <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
              )}
              {isEdit ? 'Save Changes' : sendInvite ? 'Create & Send Invite' : 'Create Employee'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
