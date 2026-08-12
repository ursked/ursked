'use client';

import dynamic from 'next/dynamic';
import { useState, useEffect, useCallback } from 'react';
import DashboardLayout from '@/components/layout/DashboardLayout';
import { useAuth } from '@/contexts/AuthContext';
import { useToast } from '@/components/ui/Toast';
import { api } from '@/lib/api';
import { User, PaginatedResponse } from '@/types';
import { getPrimaryRole, getRoleNames, hasAnyRole } from '@/lib/roles';
// Modals are only mounted once opened, so their code is fetched on demand
// rather than shipped in the page's initial bundle.
const EmployeeModal = dynamic(() => import('./EmployeeModal'));
import EmployeeDetail from './EmployeeDetail';
const SeparationModal = dynamic(() => import('./SeparationModal'));
// Employee Types (employment classifications) live with the employees they
// describe; the component itself still resides under settings/.
const EmployeeTypesTab = dynamic(() => import('@/app/settings/EmployeeTypesTab'));

type EmployeesView = 'directory' | 'types';

export default function EmployeesPage() {
  const { user: currentUser } = useAuth();
  const { showToast } = useToast();

  const [view, setView] = useState<EmployeesView>('directory');

  const [employees, setEmployees] = useState<User[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [loading, setLoading] = useState(true);

  // Filters
  const [search, setSearch] = useState('');
  const [roleFilter, setRoleFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');

  // Sorting
  const [sortBy, setSortBy] = useState('');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('asc');

  // Modals
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [editingEmployee, setEditingEmployee] = useState<User | null>(null);
  const [viewingEmployee, setViewingEmployee] = useState<User | null>(null);
  const [separatingEmployee, setSeparatingEmployee] = useState<User | null>(null);

  const perPage = 15;

  const fetchEmployees = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, string> = {
        page: String(page),
        per_page: String(perPage),
      };
      if (search) params.search = search;
      if (roleFilter) params.role = roleFilter;
      if (statusFilter === 'true' || statusFilter === 'false') {
        params.is_active = statusFilter;
      }
      if (statusFilter === 'resigned' || statusFilter === 'terminated') {
        params.is_active = 'false';
        params.separation_type = statusFilter;
      }
      if (sortBy) {
        params.sort_by = sortBy;
        params.order = sortOrder;
      }

      const result = (await api.getUsers(params)) as PaginatedResponse<User>;
      setEmployees(result.items);
      setTotal(result.total);
      setTotalPages(result.total_pages);
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to load employees', 'error');
    } finally {
      setLoading(false);
    }
  }, [page, search, roleFilter, statusFilter, sortBy, sortOrder, showToast]);

  useEffect(() => {
    fetchEmployees();
  }, [fetchEmployees]);

  // Debounced search
  const [searchInput, setSearchInput] = useState('');
  useEffect(() => {
    const timer = setTimeout(() => {
      setSearch(searchInput);
      setPage(1);
    }, 300);
    return () => clearTimeout(timer);
  }, [searchInput]);

  const handleSeparateEmployee = async (data: { separation_type: string; separation_date: string; separation_reason?: string }) => {
    if (!separatingEmployee) return;
    try {
      await api.separateUser(separatingEmployee.id, data);
      showToast(
        `${separatingEmployee.first_name} ${separatingEmployee.last_name} marked as ${data.separation_type}`,
        'success'
      );
      setSeparatingEmployee(null);
      fetchEmployees();
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to separate employee', 'error');
    }
  };

  const handleReinstateEmployee = async (employee: User) => {
    if (!confirm(`Are you sure you want to reinstate ${employee.first_name} ${employee.last_name} to active status?`)) {
      return;
    }
    try {
      await api.reinstateUser(employee.id);
      showToast(`${employee.first_name} ${employee.last_name} has been reinstated`, 'success');
      fetchEmployees();
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to reinstate employee', 'error');
    }
  };

  const handleSort = (column: string) => {
    if (sortBy === column) {
      if (sortOrder === 'asc') {
        setSortOrder('desc');
      } else {
        // Third click clears sort
        setSortBy('');
        setSortOrder('asc');
      }
    } else {
      setSortBy(column);
      setSortOrder('asc');
    }
    setPage(1);
  };

  const SortIcon = ({ column }: { column: string }) => {
    if (sortBy !== column) {
      return (
        <svg className="w-3.5 h-3.5 text-gray-400 ml-1 inline-block" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16V4m0 0L3 8m4-4l4 4m6 0v12m0 0l4-4m-4 4l-4-4" />
        </svg>
      );
    }
    return sortOrder === 'asc' ? (
      <svg className="w-3.5 h-3.5 text-purple-600 ml-1 inline-block" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 15l7-7 7 7" />
      </svg>
    ) : (
      <svg className="w-3.5 h-3.5 text-purple-600 ml-1 inline-block" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
      </svg>
    );
  };

  const canManageEmployees = currentUser && hasAnyRole(currentUser, ['tenant_admin', 'hr']);

  return (
    <DashboardLayout>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Employees</h1>
            <p className="text-gray-500 mt-1">
              {view === 'directory' ? `${total} total employees` : 'Employment classifications used across your organization'}
            </p>
          </div>
          {canManageEmployees && view === 'directory' && (
            <button
              onClick={() => setShowCreateModal(true)}
              className="inline-flex items-center gap-2 bg-purple-600 text-white px-4 py-2.5 rounded-lg font-medium hover:bg-purple-700 transition-colors"
            >
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6v6m0 0v6m0-6h6m-6 0H6" />
              </svg>
              Add Employee
            </button>
          )}
        </div>

        {/* Tabs: Directory / Employee Types (types are admin/HR only) */}
        {canManageEmployees && (
          <div className="border-b border-gray-200">
            <nav className="-mb-px flex space-x-8">
              {([
                { key: 'directory', label: 'Directory' },
                { key: 'types', label: 'Employee Types' },
              ] as const).map((tab) => (
                <button
                  key={tab.key}
                  onClick={() => setView(tab.key)}
                  className={`whitespace-nowrap border-b-2 py-3 px-1 text-sm font-medium transition-colors ${
                    view === tab.key
                      ? 'border-purple-500 text-purple-600'
                      : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700'
                  }`}
                >
                  {tab.label}
                </button>
              ))}
            </nav>
          </div>
        )}

        {view === 'types' ? (
          <EmployeeTypesTab />
        ) : (
          <>
        {/* Filters */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-4">
          <div className="flex flex-col sm:flex-row gap-3">
            {/* Search */}
            <div className="relative flex-1">
              <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
              <input
                type="text"
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                placeholder="Search by name, email, or username..."
                className="w-full pl-10 pr-4 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-transparent outline-none text-sm"
              />
            </div>

            {/* Role filter */}
            <select
              value={roleFilter}
              onChange={(e) => { setRoleFilter(e.target.value); setPage(1); }}
              className="px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-transparent outline-none text-sm bg-white"
            >
              <option value="">All Roles</option>
              <option value="tenant_admin">Administrator</option>
              <option value="hr">HR</option>
              <option value="manager">Manager</option>
              <option value="leave_approver">Leave Approver</option>
              <option value="schedule_editor">Schedule Editor</option>
              <option value="employee">Employee</option>
            </select>

            {/* Status filter */}
            <select
              value={statusFilter}
              onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}
              className="px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-transparent outline-none text-sm bg-white"
            >
              <option value="">All Employees</option>
              <option value="true">Active</option>
              <option value="false">Inactive (All)</option>
              <option value="resigned">Resigned</option>
              <option value="terminated">Terminated</option>
            </select>
          </div>
        </div>

        {/* Table */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-100">
                  <th className="text-left py-3 px-4 font-medium text-gray-600">
                    <button onClick={() => handleSort('first_name')} className="inline-flex items-center hover:text-purple-600 transition-colors">
                      Employee<SortIcon column="first_name" />
                    </button>
                  </th>
                  <th className="text-left py-3 px-4 font-medium text-gray-600 hidden md:table-cell">
                    <button onClick={() => handleSort('personnel_number')} className="inline-flex items-center hover:text-purple-600 transition-colors">
                      Personnel #<SortIcon column="personnel_number" />
                    </button>
                  </th>
                  <th className="text-left py-3 px-4 font-medium text-gray-600 hidden lg:table-cell">
                    <button onClick={() => handleSort('job_title')} className="inline-flex items-center hover:text-purple-600 transition-colors">
                      Job Title<SortIcon column="job_title" />
                    </button>
                  </th>
                  <th className="text-left py-3 px-4 font-medium text-gray-600 hidden lg:table-cell">Department</th>
                  <th className="text-left py-3 px-4 font-medium text-gray-600">Role</th>
                  <th className="text-left py-3 px-4 font-medium text-gray-600 hidden sm:table-cell">Status</th>
                  <th className="text-right py-3 px-4 font-medium text-gray-600">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {loading ? (
                  <tr>
                    <td colSpan={7} className="py-12 text-center text-gray-400">
                      <svg className="w-8 h-8 animate-spin mx-auto mb-2 text-purple-500" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                      </svg>
                      Loading employees...
                    </td>
                  </tr>
                ) : employees.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="py-12 text-center text-gray-400">
                      <svg className="w-12 h-12 mx-auto mb-3 text-gray-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z" />
                      </svg>
                      <p className="font-medium text-gray-500">No employees found</p>
                      <p className="text-sm mt-1">Try adjusting your search or filters</p>
                    </td>
                  </tr>
                ) : (
                  employees.map((emp) => (
                    <tr key={emp.id} className="hover:bg-gray-50 transition-colors">
                      {/* Employee name + email */}
                      <td className="py-3 px-4">
                        <button
                          onClick={() => setViewingEmployee(emp)}
                          className="flex items-center gap-3 text-left hover:text-purple-600 transition-colors"
                        >
                          <div className="w-9 h-9 rounded-full bg-purple-100 text-purple-700 flex items-center justify-center text-sm font-semibold flex-shrink-0">
                            {emp.first_name[0]}{emp.last_name[0]}
                          </div>
                          <div className="min-w-0">
                            <p className="font-medium text-gray-900 truncate">
                              {emp.first_name} {emp.last_name}
                            </p>
                            <p className="text-xs text-gray-500 truncate">{emp.email}</p>
                          </div>
                        </button>
                      </td>
                      {/* Personnel # */}
                      <td className="py-3 px-4 text-gray-600 hidden md:table-cell">
                        {emp.personnel_number || <span className="text-gray-300">-</span>}
                      </td>
                      {/* Job title */}
                      <td className="py-3 px-4 text-gray-600 hidden lg:table-cell">
                        {emp.job_title || <span className="text-gray-300">-</span>}
                      </td>
                      {/* Department */}
                      <td className="py-3 px-4 text-gray-600 hidden lg:table-cell">
                        {emp.div_department || <span className="text-gray-300">-</span>}
                      </td>
                      {/* Role */}
                      <td className="py-3 px-4">
                        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-purple-50 text-purple-700">
                          {getPrimaryRole(emp)}
                        </span>
                      </td>
                      {/* Status */}
                      <td className="py-3 px-4 hidden sm:table-cell">
                        {emp.is_active ? (
                          <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-green-50 text-green-700">
                            Active
                          </span>
                        ) : emp.separation_type === 'resigned' ? (
                          <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-orange-50 text-orange-700">
                            Resigned
                          </span>
                        ) : emp.separation_type === 'terminated' ? (
                          <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-red-50 text-red-700">
                            Terminated
                          </span>
                        ) : (
                          <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-600">
                            Inactive
                          </span>
                        )}
                      </td>
                      {/* Actions */}
                      <td className="py-3 px-4 text-right">
                        <div className="flex items-center justify-end gap-1">
                          <button
                            onClick={() => setViewingEmployee(emp)}
                            className="p-1.5 text-gray-400 hover:text-purple-600 rounded-lg hover:bg-purple-50 transition-colors"
                            title="View details"
                          >
                            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                            </svg>
                          </button>
                          {canManageEmployees && (
                            <>
                              <button
                                onClick={() => setEditingEmployee(emp)}
                                className="p-1.5 text-gray-400 hover:text-blue-600 rounded-lg hover:bg-blue-50 transition-colors"
                                title="Edit"
                              >
                                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                                </svg>
                              </button>
                              {emp.is_active ? (
                                <button
                                  onClick={() => setSeparatingEmployee(emp)}
                                  className="p-1.5 text-gray-400 hover:text-orange-600 rounded-lg hover:bg-orange-50 transition-colors"
                                  title="Resign / Terminate"
                                >
                                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
                                  </svg>
                                </button>
                              ) : (
                                <button
                                  onClick={() => handleReinstateEmployee(emp)}
                                  className="p-1.5 text-gray-400 hover:text-green-600 rounded-lg hover:bg-green-50 transition-colors"
                                  title="Reinstate"
                                >
                                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                                  </svg>
                                </button>
                              )}
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between px-4 py-3 border-t border-gray-100">
              <p className="text-sm text-gray-500">
                Showing {(page - 1) * perPage + 1}-{Math.min(page * perPage, total)} of {total}
              </p>
              <div className="flex items-center gap-1">
                <button
                  onClick={() => setPage(Math.max(1, page - 1))}
                  disabled={page <= 1}
                  className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Previous
                </button>
                {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                  let pageNum: number;
                  if (totalPages <= 5) {
                    pageNum = i + 1;
                  } else if (page <= 3) {
                    pageNum = i + 1;
                  } else if (page >= totalPages - 2) {
                    pageNum = totalPages - 4 + i;
                  } else {
                    pageNum = page - 2 + i;
                  }
                  return (
                    <button
                      key={pageNum}
                      onClick={() => setPage(pageNum)}
                      className={`px-3 py-1.5 text-sm rounded-lg ${
                        page === pageNum
                          ? 'bg-purple-600 text-white'
                          : 'border border-gray-300 hover:bg-gray-50'
                      }`}
                    >
                      {pageNum}
                    </button>
                  );
                })}
                <button
                  onClick={() => setPage(Math.min(totalPages, page + 1))}
                  disabled={page >= totalPages}
                  className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </div>
          </>
        )}
      </div>

      {/* Create Modal */}
      {showCreateModal && (
        <EmployeeModal
          onClose={() => setShowCreateModal(false)}
          onSaved={() => {
            setShowCreateModal(false);
            fetchEmployees();
            showToast('Employee created successfully', 'success');
          }}
        />
      )}

      {/* Edit Modal */}
      {editingEmployee && (
        <EmployeeModal
          employee={editingEmployee}
          onClose={() => setEditingEmployee(null)}
          onSaved={() => {
            setEditingEmployee(null);
            fetchEmployees();
            showToast('Employee updated successfully', 'success');
          }}
        />
      )}

      {/* Detail Slide-over */}
      {viewingEmployee && (
        <EmployeeDetail
          employee={viewingEmployee}
          onClose={() => setViewingEmployee(null)}
          onEdit={(emp) => {
            setViewingEmployee(null);
            setEditingEmployee(emp);
          }}
          canEdit={!!canManageEmployees}
        />
      )}

      {/* Separation Modal */}
      {separatingEmployee && (
        <SeparationModal
          employee={separatingEmployee}
          onClose={() => setSeparatingEmployee(null)}
          onConfirm={handleSeparateEmployee}
        />
      )}
    </DashboardLayout>
  );
}
