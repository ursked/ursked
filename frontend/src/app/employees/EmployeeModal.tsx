'use client';

import { useState, useEffect, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { User, RoleCode, EmployeeTypeConfig, ScheduleFormatConfig, RolePermissionEntry, CustomFieldValue } from '@/types';
import { getRoleCodes, hasRole } from '@/lib/roles';
import { useAuth } from '@/contexts/AuthContext';
import { UserPicker } from '@/components/ui';
import OrgUnitSelect from './OrgUnitSelect';
import { passwordProblem } from '@/app/auth/passwordRule';
import { CustomFieldInput, useEmployeeFieldConfig, DEFAULT_EMPLOYEE_NUMBER_LABEL } from './customFields';

interface EmployeeModalProps {
  employee?: User;
  onClose: () => void;
  onSaved: () => void;
}

// Administration and operations are separate roles (2026-09-29). The
// administrator runs the system and does none of the day-to-day work;
// schedules, leave, reports and payroll come with the roles below.
const ROLE_OPTIONS: { code: RoleCode; label: string; description: string }[] = [
  {
    code: 'tenant_admin',
    label: 'Administrator',
    description: 'Runs the system from the admin sign-in: accounts, roles, organization, settings and policies. Not schedules, leave approvals, finances or reports',
  },
  { code: 'hr', label: 'HR', description: 'Employee records, schedules and leave for the whole company' },
  { code: 'finance', label: 'Finance', description: 'Payroll, salary grades, deductions and pay rules, from the finance sign-in' },
  { code: 'manager', label: 'Manager', description: 'Schedules, leave and attendance for the teams they head' },
  { code: 'leave_approver', label: 'Leave Approver', description: 'Approve leave applications in their chain' },
  { code: 'schedule_editor', label: 'Schedule Editor', description: 'Create and edit schedules' },
  { code: 'report_viewer', label: 'Reports & data', description: 'Runs and saves reports and reads the analytics' },
];

// The administrator role's matrix row counts only for administration, and of
// Leave only for configuration (edit, delete); see the Permissions screen.
const ADMIN_MODULES = new Set(['employees', 'organization', 'settings']);
function adminHas(module: string, action: string): boolean {
  if (ADMIN_MODULES.has(module)) return true;
  return module === 'leave' && (action === 'can_edit' || action === 'can_delete');
}

const MODULES: { key: string; label: string }[] = [
  { key: 'employees', label: 'Employees' },
  { key: 'organization', label: 'Org' },
  { key: 'schedules', label: 'Schedules' },
  { key: 'leave', label: 'Leave' },
  { key: 'finances', label: 'Finances' },
  { key: 'settings', label: 'Settings' },
  { key: 'reports', label: 'Reports' },
];

const ACTIONS: { key: keyof Pick<RolePermissionEntry, 'can_view' | 'can_create' | 'can_edit' | 'can_delete'>; label: string; name: string }[] = [
  { key: 'can_view', label: 'V', name: 'View' },
  { key: 'can_create', label: 'C', name: 'Create' },
  { key: 'can_edit', label: 'E', name: 'Edit' },
  { key: 'can_delete', label: 'D', name: 'Delete' },
];

const inputClass =
  'w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-brand-500 focus:border-transparent outline-none text-sm disabled:bg-gray-50 disabled:text-gray-500';

type Tab = 'basic' | 'employment' | 'additional' | 'roles';

export default function EmployeeModal({ employee, onClose, onSaved }: EmployeeModalProps) {
  const isEdit = !!employee;
  const { user: currentUser } = useAuth();
  // Only an administrator may grant or revoke Administrator, and only an
  // administrator may read the permission matrix used for the preview below.
  const isAdmin = !!currentUser && hasRole(currentUser, 'tenant_admin');
  // An administrator's sign-in details are an account-takeover path, so the
  // API only lets another administrator change them.
  const signInLocked = isEdit && !isAdmin && hasRole(employee, 'tenant_admin');
  // Your own roles. In the admin dashboard an administrator may give
  // themselves (or drop) the operational roles, so a one-person company can
  // still schedule and approve leave; never their own administrator role, and
  // every other administrator is told. Anywhere else nobody changes their own
  // roles (the API refuses), so they are shown, not offered.
  const editingSelf = isEdit && !!currentUser && employee?.id === currentUser.id;
  const ownRolesLocked = editingSelf && !isAdmin;

  // Basic info
  const [firstName, setFirstName] = useState(employee?.first_name ?? '');
  const [middleName, setMiddleName] = useState(employee?.middle_name ?? '');
  const [lastName, setLastName] = useState(employee?.last_name ?? '');
  const [email, setEmail] = useState(employee?.email ?? '');
  const [password, setPassword] = useState('');
  const [sendInvite, setSendInvite] = useState(true);
  const [contactNumber, setContactNumber] = useState(employee?.contact_number ?? '');

  // Employment info
  const [personnelNumber, setPersonnelNumber] = useState(employee?.personnel_number ?? '');
  const [jobTitle, setJobTitle] = useState(employee?.job_title ?? '');
  const [rank, setRank] = useState(employee?.rank ?? '');
  const [orgNodeId, setOrgNodeId] = useState<number | null>(employee?.org_node_id ?? null);
  const [reportsToId, setReportsToId] = useState<number | null>(employee?.reports_to_id ?? null);
  const [hiringDate, setHiringDate] = useState(employee?.hiring_date ?? '');
  const [employeeType, setEmployeeType] = useState(employee?.employee_type ?? '');
  const [scheduleFormat, setScheduleFormat] = useState(employee?.schedule_format ?? '');
  const [typecode, setTypecode] = useState(employee?.typecode ?? '');
  const [idNumber, setIdNumber] = useState(employee?.id_number ?? '');

  // Company-defined fields
  const initialCustom = useMemo(() => employee?.custom_fields ?? {}, [employee]);
  const [custom, setCustom] = useState<Record<string, CustomFieldValue>>(initialCustom);

  // Roles
  const [selectedRoles, setSelectedRoles] = useState<string[]>(() => {
    if (employee) {
      return getRoleCodes(employee).filter((c) => c !== 'employee');
    }
    return [];
  });

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [tab, setTab] = useState<Tab>('basic');

  const { data: employeeTypes } = useQuery<EmployeeTypeConfig[]>({
    queryKey: ['employee-types'],
    queryFn: () => api.getEmployeeTypes(),
  });

  const { data: scheduleFormats } = useQuery<ScheduleFormatConfig[]>({
    queryKey: ['schedule-formats'],
    queryFn: () => api.getScheduleFormats(),
  });

  const { data: fieldConfig } = useEmployeeFieldConfig();
  const customDefs = fieldConfig?.fields ?? [];
  const numberLabel = fieldConfig?.employee_number_label || DEFAULT_EMPLOYEE_NUMBER_LABEL;

  const { data: permissionMatrix } = useQuery({
    queryKey: ['permission-matrix'],
    queryFn: () => api.getPermissionMatrix(),
    select: (data) => data.entries,
    enabled: isAdmin,
  });

  // A format that was retired (or never existed, like the old hard-coded
  // "8_hour") matches nothing, so hours silently fell back to defaults.
  const formatMissing =
    !!scheduleFormat && !!scheduleFormats && !scheduleFormats.some((f) => f.code === scheduleFormat);
  const typeMissing =
    !!employeeType && !!employeeTypes && !employeeTypes.some((t) => t.code === employeeType);

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

  // Compute effective (merged) permissions from selected roles. There used to be
  // a "Salary" column here, read from a view_salary extra that nothing enforced;
  // salary figures follow salary access (Finances, Salary Access), not roles.
  const effectivePerms = useMemo(() => {
    const merged: Record<string, { can_view: boolean; can_create: boolean; can_edit: boolean; can_delete: boolean }> = {};
    for (const mod of MODULES) {
      merged[mod.key] = { can_view: false, can_create: false, can_edit: false, can_delete: false };
    }
    for (const roleCode of selectedRoles) {
      const roleModules = permsByRole[roleCode];
      if (!roleModules) continue;
      for (const mod of MODULES) {
        const stored = roleModules[mod.key];
        const p = roleCode === 'tenant_admin'
          ? {
              can_view: adminHas(mod.key, 'can_view'),
              can_create: adminHas(mod.key, 'can_create'),
              can_edit: adminHas(mod.key, 'can_edit'),
              can_delete: adminHas(mod.key, 'can_delete'),
            }
          : stored;
        if (!p) continue;
        merged[mod.key].can_view = merged[mod.key].can_view || p.can_view;
        merged[mod.key].can_create = merged[mod.key].can_create || p.can_create;
        merged[mod.key].can_edit = merged[mod.key].can_edit || p.can_edit;
        merged[mod.key].can_delete = merged[mod.key].can_delete || p.can_delete;
      }
    }
    return merged;
  }, [selectedRoles, permsByRole]);

  const toggleRole = (code: string) => {
    setSelectedRoles((prev) =>
      prev.includes(code) ? prev.filter((c) => c !== code) : [...prev, code]
    );
  };

  const pwProblem = !isEdit && !sendInvite ? passwordProblem(password) : null;
  const missingRequired = customDefs.filter(
    (d) => d.is_required && (custom[d.key] === null || custom[d.key] === undefined || custom[d.key] === '')
  );
  const canSubmit = firstName.trim() && lastName.trim() && email.trim() && !pwProblem && (isEdit || missingRequired.length === 0);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    setError('');
    setLoading(true);

    // Only custom values that changed are sent: a field this user may see but
    // not edit is left alone rather than refused.
    const customChanges: Record<string, CustomFieldValue> = {};
    for (const d of customDefs) {
      const now = custom[d.key] ?? null;
      const before = initialCustom[d.key] ?? null;
      if (now !== before) customChanges[d.key] = now;
    }

    try {
      const data: Record<string, unknown> = {
        first_name: firstName.trim(),
        middle_name: middleName.trim() || null,
        last_name: lastName.trim(),
        ...(signInLocked ? {} : { email: email.trim() }),
        contact_number: contactNumber.trim() || null,
        personnel_number: personnelNumber.trim() || null,
        job_title: jobTitle.trim() || null,
        rank: rank.trim() || null,
        typecode: typecode.trim() || null,
        id_number: idNumber.trim() || null,
        hiring_date: hiringDate || null,
        employee_type: employeeType || null,
        schedule_format: scheduleFormat || null,
        org_node_id: orgNodeId,
        reports_to_id: reportsToId,
        // Omitted when the person may not change them (their own roles
        // outside the admin dashboard), so saving a profile never touches them.
        ...(ownRolesLocked ? {} : { role_codes: ['employee', ...selectedRoles] }),
      };
      if (Object.keys(customChanges).length > 0) data.custom_fields = customChanges;

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

  const tabs: { key: Tab; label: string }[] = [
    { key: 'basic', label: 'Basic Info' },
    { key: 'employment', label: 'Employment' },
    ...(customDefs.length > 0 ? [{ key: 'additional' as Tab, label: 'Additional' }] : []),
    { key: 'roles', label: 'Roles' },
  ];

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto">
      <div className="fixed inset-0 bg-black/50" onClick={onClose} />
      <div className="relative min-h-full flex items-center justify-center p-4">
        <div role="dialog" aria-modal="true" aria-labelledby="employee-modal-title" className="relative bg-white rounded-xl shadow-xl w-full max-w-2xl max-h-[90vh] overflow-hidden flex flex-col">
          {/* Header */}
          <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
            <h2 id="employee-modal-title" className="text-lg font-semibold text-gray-900">
              {isEdit ? 'Edit Employee' : 'Add New Employee'}
            </h2>
            <button onClick={onClose} className="text-gray-400 hover:text-gray-600" aria-label="Close">
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          {/* Tabs */}
          <div className="flex border-b border-gray-100 px-6 overflow-x-auto" role="tablist">
            {tabs.map((t) => (
              <button
                key={t.key}
                type="button"
                role="tab"
                aria-selected={tab === t.key}
                onClick={() => setTab(t.key)}
                className={`px-4 py-2.5 text-sm font-medium border-b-2 -mb-px whitespace-nowrap transition-colors ${
                  tab === t.key
                    ? 'border-brand-600 text-brand-600'
                    : 'border-transparent text-gray-500 hover:text-gray-700'
                }`}
              >
                {t.label}
                {t.key === 'additional' && missingRequired.length > 0 && !isEdit && (
                  <span className="ml-1 text-red-600" aria-label="required fields missing">*</span>
                )}
              </button>
            ))}
          </div>

          {/* Body */}
          <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto px-6 py-4">
            {error && (
              <div className="mb-4 bg-red-50 border border-red-200 rounded-lg p-3" role="alert">
                <p className="text-sm text-red-700">{error}</p>
              </div>
            )}

            {/* Basic Info Tab */}
            {tab === 'basic' && (
              <div className="space-y-4">
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                  <div>
                    <label htmlFor="emp-first" className="block text-sm font-medium text-gray-700 mb-1">First Name *</label>
                    <input id="emp-first" type="text" value={firstName} onChange={(e) => setFirstName(e.target.value)} required maxLength={100} className={inputClass} />
                  </div>
                  <div>
                    <label htmlFor="emp-middle" className="block text-sm font-medium text-gray-700 mb-1">Middle Name</label>
                    <input id="emp-middle" type="text" value={middleName} onChange={(e) => setMiddleName(e.target.value)} maxLength={100} className={inputClass} />
                  </div>
                  <div>
                    <label htmlFor="emp-last" className="block text-sm font-medium text-gray-700 mb-1">Last Name *</label>
                    <input id="emp-last" type="text" value={lastName} onChange={(e) => setLastName(e.target.value)} required maxLength={100} className={inputClass} />
                  </div>
                </div>

                <div>
                  <label htmlFor="emp-email" className="block text-sm font-medium text-gray-700 mb-1">Email *</label>
                  <input
                    id="emp-email"
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    disabled={signInLocked}
                    required
                    className={inputClass}
                  />
                  {signInLocked && (
                    <p className="mt-1 text-xs text-gray-500">Only an administrator can change an administrator&apos;s email address.</p>
                  )}
                </div>

                {!isEdit && (
                  <div className="space-y-3">
                    <span className="block text-sm font-medium text-gray-700">Account Setup</span>
                    <div className="flex flex-col sm:flex-row gap-3">
                      <label
                        className={`flex-1 flex items-center gap-2 p-3 rounded-lg border cursor-pointer transition-colors ${
                          sendInvite ? 'border-brand-300 bg-brand-50' : 'border-gray-200 hover:bg-gray-50'
                        }`}
                      >
                        <input
                          type="radio"
                          name="accountSetup"
                          checked={sendInvite}
                          onChange={() => setSendInvite(true)}
                          className="w-4 h-4 text-brand-600 border-gray-300 focus:ring-brand-500"
                        />
                        <div>
                          <p className="text-sm font-medium text-gray-900">Send Invite Email</p>
                          <p className="text-xs text-gray-500">User sets their own password</p>
                        </div>
                      </label>
                      <label
                        className={`flex-1 flex items-center gap-2 p-3 rounded-lg border cursor-pointer transition-colors ${
                          !sendInvite ? 'border-brand-300 bg-brand-50' : 'border-gray-200 hover:bg-gray-50'
                        }`}
                      >
                        <input
                          type="radio"
                          name="accountSetup"
                          checked={!sendInvite}
                          onChange={() => setSendInvite(false)}
                          className="w-4 h-4 text-brand-600 border-gray-300 focus:ring-brand-500"
                        />
                        <div>
                          <p className="text-sm font-medium text-gray-900">Set Password Manually</p>
                          <p className="text-xs text-gray-500">You create a temporary password</p>
                        </div>
                      </label>
                    </div>
                    {!sendInvite && (
                      <div>
                        <label htmlFor="emp-password" className="block text-sm font-medium text-gray-700 mb-1">Temporary Password *</label>
                        <input
                          id="emp-password"
                          type="password"
                          value={password}
                          onChange={(e) => setPassword(e.target.value)}
                          required
                          autoComplete="new-password"
                          aria-describedby="emp-password-help"
                          className={inputClass}
                        />
                        <p id="emp-password-help" className={`mt-1 text-xs ${password && pwProblem ? 'text-red-700' : 'text-gray-500'}`}>
                          {password && pwProblem
                            ? pwProblem
                            : 'At least 8 characters with an uppercase letter, a lowercase letter and a digit. The employee will be asked to change it when they first sign in.'}
                        </p>
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
                  <label htmlFor="emp-contact" className="block text-sm font-medium text-gray-700 mb-1">Contact Number</label>
                  <input
                    id="emp-contact"
                    type="text"
                    value={contactNumber}
                    onChange={(e) => setContactNumber(e.target.value)}
                    placeholder="e.g. +63 917 123 4567"
                    maxLength={50}
                    className={inputClass}
                  />
                </div>
              </div>
            )}

            {/* Employment Tab */}
            {tab === 'employment' && (
              <div className="space-y-4">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div>
                    <label htmlFor="emp-number" className="block text-sm font-medium text-gray-700 mb-1">{numberLabel}</label>
                    <input id="emp-number" type="text" value={personnelNumber} onChange={(e) => setPersonnelNumber(e.target.value)} maxLength={50} className={inputClass} />
                    <p className="mt-1 text-xs text-gray-500">Must be unique in your company.</p>
                  </div>
                  <div>
                    <label htmlFor="emp-hired" className="block text-sm font-medium text-gray-700 mb-1">Hiring Date</label>
                    <input id="emp-hired" type="date" value={hiringDate} onChange={(e) => setHiringDate(e.target.value)} className={inputClass} />
                  </div>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div>
                    <label htmlFor="emp-title" className="block text-sm font-medium text-gray-700 mb-1">Job Title</label>
                    <input id="emp-title" type="text" value={jobTitle} onChange={(e) => setJobTitle(e.target.value)} maxLength={200} className={inputClass} />
                  </div>
                  <div>
                    <label htmlFor="emp-rank" className="block text-sm font-medium text-gray-700 mb-1">Rank</label>
                    <input id="emp-rank" type="text" value={rank} onChange={(e) => setRank(e.target.value)} maxLength={100} className={inputClass} />
                  </div>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div>
                    <label htmlFor="emp-typecode" className="block text-sm font-medium text-gray-700 mb-1">Typecode</label>
                    <input id="emp-typecode" type="text" value={typecode} onChange={(e) => setTypecode(e.target.value)} maxLength={50} className={inputClass} />
                  </div>
                  <div>
                    <label htmlFor="emp-idnumber" className="block text-sm font-medium text-gray-700 mb-1">ID Number</label>
                    <input id="emp-idnumber" type="text" value={idNumber} onChange={(e) => setIdNumber(e.target.value)} maxLength={100} className={inputClass} />
                  </div>
                </div>

                <div>
                  <label htmlFor="emp-unit" className="block text-sm font-medium text-gray-700 mb-1">Organization Unit</label>
                  <OrgUnitSelect id="emp-unit" value={orgNodeId} onChange={setOrgNodeId} />
                  <p className="mt-1 text-xs text-gray-500">Units are managed on the Organization page.</p>
                </div>

                <div>
                  <UserPicker
                    id="emp-reports-to"
                    label="Line Manager (reports to)"
                    value={reportsToId}
                    onChange={(id) => setReportsToId(id)}
                    excludeIds={employee ? [employee.id] : []}
                    placeholder="Search for their manager"
                  />
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div>
                    <label htmlFor="emp-type" className="block text-sm font-medium text-gray-700 mb-1">Employee Type</label>
                    <select id="emp-type" value={employeeType} onChange={(e) => setEmployeeType(e.target.value)} className={`${inputClass} bg-white`}>
                      <option value="">Select type</option>
                      {(employeeTypes ?? []).map((t) => (
                        <option key={t.code} value={t.code}>{t.name}</option>
                      ))}
                      {typeMissing && <option value={employeeType}>{employeeType} (no longer configured)</option>}
                    </select>
                  </div>
                  <div>
                    <label htmlFor="emp-format" className="block text-sm font-medium text-gray-700 mb-1">Schedule Format</label>
                    <select id="emp-format" value={scheduleFormat} onChange={(e) => setScheduleFormat(e.target.value)} className={`${inputClass} bg-white`}>
                      <option value="">Select format</option>
                      {(scheduleFormats ?? []).map((f) => (
                        <option key={f.code} value={f.code}>{f.name}</option>
                      ))}
                      {formatMissing && <option value={scheduleFormat}>{scheduleFormat} (no longer exists)</option>}
                    </select>
                    {formatMissing && (
                      <p className="mt-1 text-xs text-amber-700" role="status">
                        &ldquo;{scheduleFormat}&rdquo; is not one of your schedule formats, so hours for this employee fall back to defaults. Choose a current format.
                      </p>
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* Additional (company-defined) fields */}
            {tab === 'additional' && (
              <div className="space-y-4">
                <p className="text-sm text-gray-500">Fields your company added to employee records.</p>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  {customDefs.map((d) => (
                    <CustomFieldInput
                      key={d.key}
                      def={d}
                      value={custom[d.key]}
                      onChange={(v) => setCustom((prev) => ({ ...prev, [d.key]: v }))}
                    />
                  ))}
                </div>
                {!isEdit && missingRequired.length > 0 && (
                  <p className="text-xs text-red-700">Required: {missingRequired.map((d) => d.label).join(', ')}.</p>
                )}
              </div>
            )}

            {/* Roles Tab */}
            {tab === 'roles' && (
              <div className="space-y-4">
                <p className="text-sm text-gray-500">
                  Every employee automatically has the base &quot;Employee&quot; role.
                  Select additional roles below to grant specific permissions.
                </p>
                {ownRolesLocked && (
                  <p className="rounded-lg border border-gray-200 bg-gray-50 p-3 text-sm text-gray-700" role="note">
                    These are your own roles. An administrator can change your roles from the admin dashboard.
                  </p>
                )}
                {editingSelf && isAdmin && (
                  <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900" role="note">
                    <p>Other administrators will be told about changes to your own roles.</p>
                    {selectedRoles.includes('finance') && (
                      <p className="mt-1">Salary figures still need another person&apos;s approval.</p>
                    )}
                  </div>
                )}
                {!isAdmin && !ownRolesLocked && (
                  <p className="text-xs text-gray-500">Only an administrator can grant or remove the Administrator role.</p>
                )}
                <div className="space-y-2">
                  {ROLE_OPTIONS.filter((role) => isAdmin || ownRolesLocked || role.code !== 'tenant_admin')
                    .filter((role) => !ownRolesLocked || selectedRoles.includes(role.code))
                    .map((role) => {
                    const isSelected = selectedRoles.includes(role.code);
                    const rolePerms = permsByRole[role.code];
                    const isTenantAdmin = role.code === 'tenant_admin';
                    // Your own administrator role is another administrator's
                    // to change; every role, outside the admin dashboard.
                    const lockReason = ownRolesLocked
                      ? 'An administrator can change your roles from the admin dashboard.'
                      : editingSelf && isTenantAdmin
                        ? 'Another administrator has to change your own administrator role.'
                        : null;

                    return (
                      <div
                        key={role.code}
                        className={`rounded-lg border transition-colors ${
                          isSelected ? 'border-brand-300 bg-brand-50/50' : 'border-gray-200 hover:bg-gray-50'
                        }`}
                      >
                        <label className={`flex items-center gap-3 p-3 ${lockReason ? 'cursor-not-allowed' : 'cursor-pointer'}`}>
                          <input
                            type="checkbox"
                            checked={isSelected}
                            disabled={!!lockReason}
                            onChange={() => toggleRole(role.code)}
                            className="w-4 h-4 text-brand-600 border-gray-300 rounded focus:ring-brand-500 disabled:opacity-50"
                          />
                          <div className="flex-1 min-w-0">
                            <p className="text-sm font-medium text-gray-900">{role.label}</p>
                            <p className="text-xs text-gray-500">{role.description}</p>
                            {lockReason && !ownRolesLocked && (
                              <p className="mt-0.5 text-xs text-amber-700">{lockReason}</p>
                            )}
                          </div>
                        </label>

                        {/* Inline permission grid (administrators only: it reads the permission matrix) */}
                        {isAdmin && isSelected && rolePerms && (
                          <div className="px-3 pb-3 pt-0">
                            <div className="bg-white rounded-lg border border-gray-100 overflow-x-auto">
                              <table className="w-full text-[10px]">
                                <thead>
                                  <tr className="bg-gray-50">
                                    <th className="px-1.5 py-1 text-left font-medium text-gray-500 w-[60px]"></th>
                                    {MODULES.map(m => (
                                      <th key={m.key} className="px-1 py-1 text-center font-medium text-gray-500">{m.label}</th>
                                    ))}
                                  </tr>
                                </thead>
                                <tbody>
                                  {ACTIONS.map(action => (
                                    <tr key={action.key} className="border-t border-gray-50">
                                      <td className="px-1.5 py-0.5 font-medium text-gray-500">{action.name}</td>
                                      {MODULES.map(m => {
                                        const granted = isTenantAdmin ? adminHas(m.key, action.key) : rolePerms[m.key]?.[action.key];
                                        return (
                                          <td key={m.key} className="px-1 py-0.5 text-center">
                                            <span className={`inline-block w-3.5 h-3.5 rounded-full text-[8px] leading-[14px] ${granted ? 'bg-green-500 text-white font-bold' : 'bg-gray-200 text-gray-400'}`}>{action.label}</span>
                                          </td>
                                        );
                                      })}
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
                {isAdmin && selectedRoles.length > 0 && (
                  <div className="mt-4 bg-brand-50 border border-brand-200 rounded-lg p-4">
                    <div className="mb-2">
                      <h4 className="text-sm font-semibold text-brand-900">Effective Permissions</h4>
                      <p className="text-xs text-brand-600">
                        Combined access from: {selectedRoles.map(c => ROLE_OPTIONS.find(r => r.code === c)?.label).filter(Boolean).join(', ')}
                      </p>
                    </div>
                    <div className="bg-white rounded-lg border border-brand-100 overflow-x-auto">
                      <table className="w-full text-[10px]">
                        <thead>
                          <tr className="bg-brand-50/50">
                            <th className="px-1.5 py-1 text-left font-medium text-brand-700 w-[60px]"></th>
                            {MODULES.map(m => (
                              <th key={m.key} className="px-1 py-1 text-center font-medium text-brand-700">{m.label}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {ACTIONS.map(action => (
                            <tr key={action.key} className="border-t border-brand-50">
                              <td className="px-1.5 py-0.5 font-medium text-brand-600">{action.name}</td>
                              {MODULES.map(m => {
                                const granted = effectivePerms[m.key]?.[action.key];
                                return (
                                  <td key={m.key} className="px-1 py-0.5 text-center">
                                    <span className={`inline-block w-3.5 h-3.5 rounded-full text-[8px] leading-[14px] ${granted ? 'bg-brand-600 text-white font-bold' : 'bg-gray-200 text-gray-400'}`}>{action.label}</span>
                                  </td>
                                );
                              })}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    <p className="mt-2 text-xs text-brand-700">
                      Administrator works only from the administrator sign-in, and Finance only from the finance
                      sign-in. No role shows salary figures: each person needs salary access, approved by someone
                      else under Salary access.
                    </p>
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
              className="px-4 py-2.5 text-sm font-medium text-white bg-brand-600 rounded-lg hover:bg-brand-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
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
