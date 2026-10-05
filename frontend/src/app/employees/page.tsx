'use client';

import dynamic from 'next/dynamic';
import { useState, useEffect, useCallback, useMemo } from 'react';
import DashboardLayout from '@/components/layout/DashboardLayout';
import { useAuth } from '@/contexts/AuthContext';
import { usePermissions } from '@/contexts/PermissionsContext';
import { useToast } from '@/components/ui/Toast';
import { api } from '@/lib/api';
import { User, PaginatedResponse } from '@/types';
import { getPrimaryRole } from '@/lib/roles';
import EmployeeDetail from './EmployeeDetail';
import BulkActionsBar, { type BulkSelection } from './BulkActionsBar';
import OrgUnitSelect from './OrgUnitSelect';
import { useEmployeeFieldConfig, formatCustomValue, DEFAULT_EMPLOYEE_NUMBER_LABEL } from './customFields';
// Modals are only mounted once opened, so their code is fetched on demand
// rather than shipped in the page's initial bundle.
const EmployeeModal = dynamic(() => import('./EmployeeModal'));
const SeparationModal = dynamic(() => import('./SeparationModal'));
const ImportModal = dynamic(() => import('./ImportModal'));
// Employee Types (employment classifications) and Custom fields live with the
// employees they describe. Viewing needs settings:view, changing settings:edit.
const EmployeeTypesPanel = dynamic(() => import('./EmployeeTypesPanel'));
const CustomFieldsTab = dynamic(() => import('./CustomFieldsTab'));

type EmployeesView = 'directory' | 'types' | 'fields';

const COLUMNS_STORAGE_KEY = 'employees.customColumns';

export default function EmployeesPage() {
  const { user: currentUser } = useAuth();
  const { showToast } = useToast();
  const { hasPermission } = usePermissions();

  const [view, setView] = useState<EmployeesView>('directory');

  const [employees, setEmployees] = useState<User[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');

  // Filters
  const [search, setSearch] = useState('');
  const [roleFilter, setRoleFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [unitFilter, setUnitFilter] = useState<number | null>(null);
  const [customFilters, setCustomFilters] = useState<Record<string, string>>({});

  // Sorting
  const [sortBy, setSortBy] = useState('');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('asc');

  // Selection for bulk actions: explicit ids, or "everyone matching the filter".
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [allMatching, setAllMatching] = useState(false);

  // Modals
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [editingEmployee, setEditingEmployee] = useState<User | null>(null);
  const [viewingEmployee, setViewingEmployee] = useState<User | null>(null);
  const [separatingEmployee, setSeparatingEmployee] = useState<User | null>(null);

  const { data: fieldConfig } = useEmployeeFieldConfig();
  const numberLabel = fieldConfig?.employee_number_label || DEFAULT_EMPLOYEE_NUMBER_LABEL;
  const customDefs = useMemo(() => fieldConfig?.fields ?? [], [fieldConfig]);
  // Optional table columns: any custom field shown in lists (sensitive ones
  // never come back in list responses below HR level anyway).
  const columnDefs = customDefs;
  const filterDefs = customDefs.filter((d) => d.field_type === 'select' && !d.is_sensitive);

  // Read after mount: the server render has no localStorage, and reading it
  // during the first render would make the client disagree with the server.
  const [shownColumns, setShownColumns] = useState<string[]>([]);
  useEffect(() => {
    void Promise.resolve().then(() => {
      try {
        const saved = JSON.parse(window.localStorage.getItem(COLUMNS_STORAGE_KEY) || '[]');
        if (Array.isArray(saved)) setShownColumns(saved.filter((k) => typeof k === 'string'));
      } catch { /* ignore a corrupt preference */ }
    });
  }, []);
  // /employees?open=<id> opens that person's record (the admin dashboard
  // links people who have no role yet here). Read after mount, like the
  // column preference above.
  useEffect(() => {
    const id = Number(new URLSearchParams(window.location.search).get('open'));
    if (!Number.isInteger(id) || id <= 0) return;
    let active = true;
    api.getUser(id)
      .then((u) => { if (active) setViewingEmployee(u); })
      .catch(() => { /* not visible to this user, or gone: stay on the list */ });
    return () => { active = false; };
  }, []);

  const [showColumnPicker, setShowColumnPicker] = useState(false);
  const visibleColumns = columnDefs.filter((d) => shownColumns.includes(d.key));
  const toggleColumn = (key: string) => {
    setShownColumns((prev) => {
      const next = prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key];
      try { window.localStorage.setItem(COLUMNS_STORAGE_KEY, JSON.stringify(next)); } catch { /* ignore */ }
      return next;
    });
  };

  const perPage = 15;

  const filterParams = useCallback((): Record<string, string> => {
    const params: Record<string, string> = {};
    if (search) params.search = search;
    if (roleFilter) params.role = roleFilter;
    if (statusFilter === 'true' || statusFilter === 'false') {
      params.is_active = statusFilter;
    }
    if (statusFilter === 'resigned' || statusFilter === 'terminated') {
      params.is_active = 'false';
      params.separation_type = statusFilter;
    }
    if (unitFilter) params.org_node_id = String(unitFilter);
    for (const [k, v] of Object.entries(customFilters)) {
      if (v) params[`cf_${k}`] = v;
    }
    return params;
  }, [search, roleFilter, statusFilter, unitFilter, customFilters]);

  const fetchEmployees = useCallback(async () => {
    setLoading(true);
    setLoadError('');
    try {
      const params: Record<string, string> = {
        page: String(page),
        per_page: String(perPage),
        ...filterParams(),
      };
      if (sortBy) {
        params.sort_by = sortBy;
        params.order = sortOrder;
      }

      const result = (await api.getUsers(params)) as PaginatedResponse<User>;
      setEmployees(result.items);
      setTotal(result.total);
      setTotalPages(result.total_pages);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to load employees';
      setLoadError(message);
      setEmployees([]);
    } finally {
      setLoading(false);
    }
  }, [page, filterParams, sortBy, sortOrder]);

  useEffect(() => {
    let active = true;
    // Defer so fetchEmployees' loading-state update does not run synchronously in
    // the effect body (react-hooks/set-state-in-effect).
    void Promise.resolve().then(() => {
      if (active) fetchEmployees();
    });
    return () => {
      active = false;
    };
  }, [fetchEmployees]);

  // A new filter is a new set of people; a selection made under the old one
  // must not silently carry over.
  useEffect(() => {
    void Promise.resolve().then(() => {
      setSelectedIds([]);
      setAllMatching(false);
    });
  }, [search, roleFilter, statusFilter, unitFilter, customFilters]);

  // Debounced search
  const [searchInput, setSearchInput] = useState('');
  useEffect(() => {
    const timer = setTimeout(() => {
      setSearch(searchInput);
      setPage(1);
    }, 300);
    return () => clearTimeout(timer);
  }, [searchInput]);

  const handleSeparateEmployee = async (data: { separation_type: string; separation_date: string; separation_reason?: string; delete_future_shifts: boolean }) => {
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

  const handleResendInvite = async (employee: User) => {
    try {
      await api.resendInvite(employee.id);
      showToast(`Invite sent again to ${employee.email}`, 'success');
      fetchEmployees();
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to resend the invite', 'error');
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

  // A render helper (not a component) so it is not re-created as a new component
  // type on every render (react-hooks/static-components). Called as
  // {renderSortIcon('name')} rather than <SortIcon column="name" />.
  const renderSortIcon = (column: string) => {
    if (sortBy !== column) {
      return (
        <svg className="w-3.5 h-3.5 text-gray-400 ml-1 inline-block" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16V4m0 0L3 8m4-4l4 4m6 0v12m0 0l4-4m-4 4l-4-4" />
        </svg>
      );
    }
    return sortOrder === 'asc' ? (
      <svg className="w-3.5 h-3.5 text-brand-600 ml-1 inline-block" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 15l7-7 7 7" />
      </svg>
    ) : (
      <svg className="w-3.5 h-3.5 text-brand-600 ml-1 inline-block" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
      </svg>
    );
  };

  // Every action is shown only when the API will accept it (audit E-8): the
  // same employees/settings permissions the backend checks.
  const canCreate = hasPermission('employees', 'create');
  const canEdit = hasPermission('employees', 'edit');
  const canSeparate = hasPermission('employees', 'delete');
  const canViewSettings = hasPermission('settings', 'view');
  const canBulk = canCreate || canEdit || canSeparate;

  const pageIds = employees.map((e) => e.id);
  const allOnPageSelected = pageIds.length > 0 && pageIds.every((id) => selectedIds.includes(id));
  const toggleOne = (id: number) => {
    setAllMatching(false);
    setSelectedIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  };
  const togglePage = () => {
    setAllMatching(false);
    setSelectedIds((prev) => (allOnPageSelected ? prev.filter((id) => !pageIds.includes(id)) : Array.from(new Set([...prev, ...pageIds]))));
  };

  const bulkSelection: BulkSelection | null = allMatching
    ? {
        mode: 'filter',
        count: total,
        filter: (() => {
          const p = filterParams();
          const custom: Record<string, string> = {};
          for (const [k, v] of Object.entries(customFilters)) if (v) custom[k] = v;
          return {
            search: p.search,
            role: p.role,
            is_active: p.is_active === undefined ? undefined : p.is_active === 'true',
            separation_type: p.separation_type,
            org_node_id: unitFilter ?? undefined,
            custom: Object.keys(custom).length ? custom : undefined,
          };
        })(),
      }
    : selectedIds.length > 0
      ? { mode: 'ids', ids: selectedIds }
      : null;

  const colCount = 7 + visibleColumns.length + (canBulk ? 1 : 0);

  const tabs: { key: EmployeesView; label: string }[] = [
    { key: 'directory', label: 'Directory' },
    { key: 'types', label: 'Employee Types' },
    { key: 'fields', label: 'Custom fields' },
  ];

  return (
    <DashboardLayout>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Employees</h1>
            <p className="text-gray-500 mt-1">
              {view === 'directory'
                ? `${total} ${total === 1 ? 'employee' : 'employees'}`
                : view === 'types'
                  ? 'Employment classifications used across your organization'
                  : 'Information your company records about employees'}
            </p>
          </div>
          {view === 'directory' && (
            <div className="flex flex-wrap gap-2">
              {(canCreate || canEdit) && (
                <button
                  onClick={() => setShowImport(true)}
                  className="inline-flex items-center gap-2 bg-white text-gray-700 border border-gray-300 px-4 py-2.5 rounded-lg font-medium hover:bg-gray-50 transition-colors"
                >
                  Import
                </button>
              )}
              {canCreate && (
                <button
                  onClick={() => setShowCreateModal(true)}
                  className="inline-flex items-center gap-2 bg-brand-600 text-white px-4 py-2.5 rounded-lg font-medium hover:bg-brand-700 transition-colors"
                >
                  <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6v6m0 0v6m0-6h6m-6 0H6" />
                  </svg>
                  Add Employee
                </button>
              )}
            </div>
          )}
        </div>

        {/* Tabs: types and custom fields are company settings (settings:view) */}
        {canViewSettings && (
          <div>
            <nav className="flex space-x-8 overflow-x-auto shadow-[inset_0_-1px_0_0_#e5e7eb]" role="tablist">
              {tabs.map((tab) => (
                <button
                  key={tab.key}
                  role="tab"
                  aria-selected={view === tab.key}
                  onClick={() => setView(tab.key)}
                  className={`whitespace-nowrap border-b-2 py-3 px-1 text-sm font-medium transition-colors ${
                    view === tab.key
                      ? 'border-brand-500 text-brand-600'
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
          <EmployeeTypesPanel />
        ) : view === 'fields' ? (
          <CustomFieldsTab />
        ) : (
          <>
        {/* Filters */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-4 space-y-3">
          <div className="flex flex-col lg:flex-row gap-3">
            {/* Search */}
            <div className="relative flex-1">
              <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
              <input
                type="text"
                aria-label="Search employees"
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                placeholder={`Search by name, email, ${numberLabel}…`}
                className="w-full pl-10 pr-4 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-brand-500 focus:border-transparent outline-none text-sm"
              />
            </div>

            {/* Role filter */}
            <select
              aria-label="Filter by role"
              value={roleFilter}
              onChange={(e) => { setRoleFilter(e.target.value); setPage(1); }}
              className="px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-brand-500 focus:border-transparent outline-none text-sm bg-white"
            >
              <option value="">All Roles</option>
              <option value="tenant_admin">Administrator</option>
              <option value="hr">HR</option>
              <option value="finance">Finance</option>
              <option value="manager">Manager</option>
              <option value="leave_approver">Leave Approver</option>
              <option value="schedule_editor">Schedule Editor</option>
              <option value="report_viewer">Reports &amp; data</option>
              <option value="employee">Employee</option>
            </select>

            {/* Status filter */}
            <select
              aria-label="Filter by status"
              value={statusFilter}
              onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}
              className="px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-brand-500 focus:border-transparent outline-none text-sm bg-white"
            >
              <option value="">All Employees</option>
              <option value="true">Active</option>
              <option value="false">Inactive (All)</option>
              <option value="resigned">Resigned</option>
              <option value="terminated">Terminated</option>
            </select>

            {/* Unit filter (includes sub-units) */}
            <div className="lg:w-56">
              <OrgUnitSelect
                value={unitFilter}
                onChange={(id) => { setUnitFilter(id); setPage(1); }}
                emptyLabel="All units"
                className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-brand-500 focus:border-transparent outline-none text-sm bg-white"
              />
            </div>
          </div>

          {(filterDefs.length > 0 || columnDefs.length > 0) && (
            <div className="flex flex-wrap items-center gap-3">
              {filterDefs.map((d) => (
                <select
                  key={d.key}
                  aria-label={`Filter by ${d.label}`}
                  value={customFilters[d.key] ?? ''}
                  onChange={(e) => { setCustomFilters((prev) => ({ ...prev, [d.key]: e.target.value })); setPage(1); }}
                  className="px-3 py-2 border border-gray-300 rounded-lg text-sm bg-white"
                >
                  <option value="">{d.label}: any</option>
                  {d.options.map((o) => <option key={o} value={o}>{o}</option>)}
                </select>
              ))}
              {columnDefs.length > 0 && (
                <div className="relative">
                  <button
                    type="button"
                    onClick={() => setShowColumnPicker((v) => !v)}
                    aria-expanded={showColumnPicker}
                    className="px-3 py-2 border border-gray-300 rounded-lg text-sm bg-white hover:bg-gray-50"
                  >
                    Columns{visibleColumns.length ? ` (${visibleColumns.length})` : ''}
                  </button>
                  {showColumnPicker && (
                    <div className="absolute z-20 mt-1 w-64 rounded-lg border border-gray-200 bg-white p-2 shadow-lg">
                      <p className="px-2 pb-1 text-xs text-gray-500">Show custom fields as columns</p>
                      {columnDefs.map((d) => (
                        <label key={d.key} className="flex items-center gap-2 rounded px-2 py-1.5 text-sm hover:bg-gray-50">
                          <input type="checkbox" checked={shownColumns.includes(d.key)} onChange={() => toggleColumn(d.key)} className="h-4 w-4 rounded border-gray-300 text-brand-600" />
                          {d.label}
                        </label>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>

        {canBulk && bulkSelection && (
          <BulkActionsBar
            selection={bulkSelection}
            canEdit={canEdit}
            canCreate={canCreate}
            canSeparate={canSeparate}
            onClear={() => { setSelectedIds([]); setAllMatching(false); }}
            onDone={fetchEmployees}
          />
        )}

        {canBulk && allOnPageSelected && !allMatching && total > employees.length && (
          <div className="rounded-lg bg-brand-50 px-4 py-2 text-sm text-brand-900">
            All {employees.length} on this page are selected.{' '}
            <button type="button" onClick={() => setAllMatching(true)} className="font-medium underline">
              Select all {total} matching this filter
            </button>
          </div>
        )}

        {/* Table */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-100">
                  {canBulk && (
                    <th className="py-3 pl-4 w-8">
                      <input
                        type="checkbox"
                        aria-label="Select all on this page"
                        checked={allOnPageSelected || allMatching}
                        onChange={togglePage}
                        className="h-4 w-4 rounded border-gray-300 text-brand-600"
                      />
                    </th>
                  )}
                  <th className="text-left py-3 px-4 font-medium text-gray-600">
                    <button onClick={() => handleSort('first_name')} className="inline-flex items-center hover:text-brand-600 transition-colors">
                      Employee{renderSortIcon('first_name')}
                    </button>
                  </th>
                  <th className="text-left py-3 px-4 font-medium text-gray-600 hidden md:table-cell">
                    <button onClick={() => handleSort('personnel_number')} className="inline-flex items-center hover:text-brand-600 transition-colors">
                      {numberLabel}{renderSortIcon('personnel_number')}
                    </button>
                  </th>
                  <th className="text-left py-3 px-4 font-medium text-gray-600 hidden lg:table-cell">
                    <button onClick={() => handleSort('job_title')} className="inline-flex items-center hover:text-brand-600 transition-colors">
                      Job Title{renderSortIcon('job_title')}
                    </button>
                  </th>
                  <th className="text-left py-3 px-4 font-medium text-gray-600 hidden lg:table-cell">Department</th>
                  <th className="text-left py-3 px-4 font-medium text-gray-600">Role</th>
                  <th className="text-left py-3 px-4 font-medium text-gray-600 hidden sm:table-cell">Status</th>
                  {visibleColumns.map((d) => (
                    <th key={d.key} className="text-left py-3 px-4 font-medium text-gray-600 hidden md:table-cell">{d.label}</th>
                  ))}
                  <th className="text-right py-3 px-4 font-medium text-gray-600">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {loading ? (
                  <tr>
                    <td colSpan={colCount} className="py-12 text-center text-gray-400">
                      <svg className="w-8 h-8 animate-spin mx-auto mb-2 text-brand-500" fill="none" viewBox="0 0 24 24" aria-hidden="true">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                      </svg>
                      Loading employees...
                    </td>
                  </tr>
                ) : loadError ? (
                  <tr>
                    <td colSpan={colCount} className="py-12 text-center">
                      <p className="font-medium text-gray-700">{loadError}</p>
                    </td>
                  </tr>
                ) : employees.length === 0 ? (
                  <tr>
                    <td colSpan={colCount} className="py-12 text-center text-gray-400">
                      <p className="font-medium text-gray-500">No employees found</p>
                      <p className="text-sm mt-1">Try adjusting your search or filters</p>
                    </td>
                  </tr>
                ) : (
                  employees.map((emp) => (
                    <tr key={emp.id} className={`hover:bg-gray-50 transition-colors ${selectedIds.includes(emp.id) || allMatching ? 'bg-brand-50/40' : ''}`}>
                      {canBulk && (
                        <td className="py-3 pl-4">
                          <input
                            type="checkbox"
                            aria-label={`Select ${emp.first_name} ${emp.last_name}`}
                            checked={allMatching || selectedIds.includes(emp.id)}
                            onChange={() => toggleOne(emp.id)}
                            className="h-4 w-4 rounded border-gray-300 text-brand-600"
                          />
                        </td>
                      )}
                      {/* Employee name + email */}
                      <td className="py-3 px-4">
                        <button
                          onClick={() => setViewingEmployee(emp)}
                          className="flex items-center gap-3 text-left hover:text-brand-600 transition-colors"
                        >
                          <div className="w-9 h-9 rounded-full bg-brand-100 text-brand-700 flex items-center justify-center text-sm font-semibold flex-shrink-0">
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
                      <td className="py-3 px-4 text-gray-600 hidden md:table-cell">
                        {emp.personnel_number || <span className="text-gray-500">-</span>}
                      </td>
                      <td className="py-3 px-4 text-gray-600 hidden lg:table-cell">
                        {emp.job_title || <span className="text-gray-500">-</span>}
                      </td>
                      {/* Department = the organization unit (the free-text column is legacy) */}
                      <td className="py-3 px-4 text-gray-600 hidden lg:table-cell">
                        {emp.org_node_name || <span className="text-gray-500">-</span>}
                      </td>
                      <td className="py-3 px-4">
                        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-brand-50 text-brand-700">
                          {getPrimaryRole(emp)}
                        </span>
                      </td>
                      <td className="py-3 px-4 hidden sm:table-cell">
                        <div className="flex flex-wrap gap-1">
                          {emp.is_active ? (
                            <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-green-50 text-green-700">Active</span>
                          ) : emp.separation_type === 'resigned' ? (
                            <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-orange-50 text-orange-700">Resigned</span>
                          ) : emp.separation_type === 'terminated' ? (
                            <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-red-50 text-red-700">Terminated</span>
                          ) : (
                            <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-600">Inactive</span>
                          )}
                          {emp.is_active && emp.invite_pending && (
                            <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-amber-50 text-amber-800">
                              {emp.invite_expired ? 'Invite expired' : 'Invite pending'}
                            </span>
                          )}
                        </div>
                      </td>
                      {visibleColumns.map((d) => (
                        <td key={d.key} className="py-3 px-4 text-gray-600 hidden md:table-cell">
                          {formatCustomValue(d, emp.custom_fields?.[d.key]) || <span className="text-gray-500">-</span>}
                        </td>
                      ))}
                      {/* Actions */}
                      <td className="py-3 px-4 text-right">
                        <div className="flex items-center justify-end gap-1">
                          <button
                            onClick={() => setViewingEmployee(emp)}
                            className="p-1.5 text-gray-400 hover:text-brand-600 rounded-lg hover:bg-brand-50 transition-colors"
                            title="View details"
                            aria-label={`View ${emp.first_name} ${emp.last_name}`}
                          >
                            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                            </svg>
                          </button>
                          {canCreate && emp.is_active && emp.invite_pending && (
                            <button
                              onClick={() => handleResendInvite(emp)}
                              className="px-2 py-1 text-xs font-medium text-amber-800 rounded-lg hover:bg-amber-50 transition-colors"
                              title="Send the activation email again"
                            >
                              Resend invite
                            </button>
                          )}
                          {canEdit && (
                              <button
                                onClick={() => setEditingEmployee(emp)}
                                className="p-1.5 text-gray-400 hover:text-blue-600 rounded-lg hover:bg-blue-50 transition-colors"
                                title="Edit"
                                aria-label={`Edit ${emp.first_name} ${emp.last_name}`}
                              >
                                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                                </svg>
                              </button>
                          )}
                          {canSeparate && emp.id !== currentUser?.id && (
                            <>
                              {emp.is_active ? (
                                <button
                                  onClick={() => setSeparatingEmployee(emp)}
                                  className="p-1.5 text-gray-400 hover:text-orange-600 rounded-lg hover:bg-orange-50 transition-colors"
                                  title="Resign / Terminate"
                                  aria-label={`Separate ${emp.first_name} ${emp.last_name}`}
                                >
                                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
                                  </svg>
                                </button>
                              ) : (
                                <button
                                  onClick={() => handleReinstateEmployee(emp)}
                                  className="p-1.5 text-gray-400 hover:text-green-600 rounded-lg hover:bg-green-50 transition-colors"
                                  title="Reinstate"
                                  aria-label={`Reinstate ${emp.first_name} ${emp.last_name}`}
                                >
                                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
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
                      aria-current={page === pageNum ? 'page' : undefined}
                      className={`px-3 py-1.5 text-sm rounded-lg ${
                        page === pageNum
                          ? 'bg-brand-600 text-white'
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

      {showImport && (
        <ImportModal onClose={() => setShowImport(false)} onImported={fetchEmployees} />
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
          canEdit={canEdit}
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
