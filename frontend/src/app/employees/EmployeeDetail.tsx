'use client';

import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { User, EmployeeTypeConfig, ScheduleFormatConfig } from '@/types';
import { getPrimaryRole, getRoleNames } from '@/lib/roles';

interface EmployeeDetailProps {
  employee: User;
  onClose: () => void;
  onEdit: (employee: User) => void;
  canEdit: boolean;
}

function InfoRow({ label, value }: { label: string; value?: string | null }) {
  return (
    <div>
      <p className="text-xs font-medium text-gray-400 uppercase tracking-wider">{label}</p>
      <p className="text-sm text-gray-900 mt-0.5">{value || <span className="text-gray-500">Not set</span>}</p>
    </div>
  );
}

// Employee types and schedule formats are now fetched from API

export default function EmployeeDetail({ employee, onClose, onEdit, canEdit }: EmployeeDetailProps) {
  const { data: employeeTypes } = useQuery<EmployeeTypeConfig[]>({
    queryKey: ['employee-types'],
    queryFn: () => api.getEmployeeTypes(),
  });

  const { data: scheduleFormats } = useQuery<ScheduleFormatConfig[]>({
    queryKey: ['schedule-formats'],
    queryFn: () => api.getScheduleFormats(),
  });

  const getEmployeeTypeLabel = (code: string) => employeeTypes?.find((t) => t.code === code)?.name ?? code.replace(/_/g, ' ');
  const getScheduleFormatLabel = (code: string) => scheduleFormats?.find((f) => f.code === code)?.name ?? code.replace(/_/g, ' ');

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 overflow-hidden">
      <div className="fixed inset-0 bg-black/50" onClick={onClose} />
      <div className="fixed inset-y-0 right-0 flex max-w-full pl-10">
        <div className="w-screen max-w-md">
          <div className="flex flex-col h-full bg-white shadow-xl">
            {/* Header */}
            <div className="px-6 py-5 border-b border-gray-100">
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-semibold text-gray-900">Employee Details</h2>
                <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
                  <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
            </div>

            {/* Body */}
            <div className="flex-1 overflow-y-auto px-6 py-5 space-y-6">
              {/* Profile header */}
              <div className="flex items-center gap-4">
                <div className="w-16 h-16 rounded-full bg-purple-100 text-purple-700 flex items-center justify-center text-xl font-bold flex-shrink-0">
                  {employee.first_name[0]}{employee.last_name[0]}
                </div>
                <div>
                  <h3 className="text-lg font-semibold text-gray-900">
                    {employee.first_name} {employee.last_name}
                  </h3>
                  <p className="text-sm text-gray-500">{employee.email}</p>
                  <div className="flex items-center gap-2 mt-1">
                    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-purple-50 text-purple-700">
                      {getPrimaryRole(employee)}
                    </span>
                    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
                      employee.is_active
                        ? 'bg-green-50 text-green-700'
                        : 'bg-red-50 text-red-700'
                    }`}>
                      {employee.is_active ? 'Active' : 'Inactive'}
                    </span>
                  </div>
                </div>
              </div>

              {/* Roles */}
              <div>
                <h4 className="text-sm font-semibold text-gray-900 mb-2">Roles</h4>
                <div className="flex flex-wrap gap-2">
                  {employee.roles && employee.roles.length > 0 ? (
                    employee.roles.map((ur) => (
                      <span
                        key={ur.id}
                        className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-gray-100 text-gray-700"
                      >
                        {ur.role.name}
                        {ur.title && <span className="ml-1 text-gray-400">({ur.title})</span>}
                      </span>
                    ))
                  ) : (
                    <span className="text-sm text-gray-400">Employee</span>
                  )}
                </div>
              </div>

              {/* Personal Info */}
              <div>
                <h4 className="text-sm font-semibold text-gray-900 mb-3">Personal Information</h4>
                <div className="grid grid-cols-2 gap-4">
                  <InfoRow label="First Name" value={employee.first_name} />
                  <InfoRow label="Last Name" value={employee.last_name} />
                  <InfoRow label="Email" value={employee.email} />
                  <InfoRow label="Contact Number" value={employee.contact_number} />
                  <InfoRow label="Username" value={employee.username} />
                </div>
              </div>

              {/* Employment Info */}
              <div>
                <h4 className="text-sm font-semibold text-gray-900 mb-3">Employment Information</h4>
                <div className="grid grid-cols-2 gap-4">
                  <InfoRow label="Personnel Number" value={employee.personnel_number} />
                  <InfoRow label="Typecode" value={employee.typecode} />
                  <InfoRow label="ID Number" value={employee.id_number} />
                  <InfoRow label="Hiring Date" value={employee.hiring_date} />
                  <InfoRow label="Job Title" value={employee.job_title} />
                  <InfoRow label="Rank" value={employee.rank} />
                  <InfoRow label="Div / Department" value={employee.div_department} />
                  <InfoRow
                    label="Employee Type"
                    value={employee.employee_type ? getEmployeeTypeLabel(employee.employee_type) : null}
                  />
                  <InfoRow
                    label="Schedule Format"
                    value={employee.schedule_format ? getScheduleFormatLabel(employee.schedule_format) : null}
                  />
                </div>
              </div>

              {/* Timestamps */}
              <div>
                <h4 className="text-sm font-semibold text-gray-900 mb-3">System</h4>
                <div className="grid grid-cols-2 gap-4">
                  <InfoRow label="Created" value={employee.created_at ? new Date(employee.created_at).toLocaleDateString() : null} />
                  <InfoRow label="Updated" value={employee.updated_at ? new Date(employee.updated_at).toLocaleDateString() : null} />
                </div>
              </div>
            </div>

            {/* Footer */}
            {canEdit && (
              <div className="px-6 py-4 border-t border-gray-100 bg-gray-50">
                <button
                  onClick={() => onEdit(employee)}
                  className="w-full px-4 py-2.5 text-sm font-medium text-white bg-purple-600 rounded-lg hover:bg-purple-700 transition-colors flex items-center justify-center gap-2"
                >
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                  </svg>
                  Edit Employee
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
