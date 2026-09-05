'use client';

import { useQuery } from '@tanstack/react-query';
import { Users, Building2, Clock, AlertTriangle, CheckCircle, XCircle, TrendingUp, Calendar } from 'lucide-react';
import DashboardLayout from '@/components/layout/DashboardLayout';
import { useAuth } from '@/contexts/AuthContext';
import { getPrimaryRole, hasAnyRole } from '@/lib/roles';
import { api } from '@/lib/api';
import { DashboardMetrics } from '@/types';
import SetupChecklist from '@/components/SetupChecklist';

const statusColors: Record<string, string> = {
  pending: 'bg-yellow-100 text-yellow-800',
  approved: 'bg-green-100 text-green-800',
  rejected: 'bg-red-100 text-red-800',
  converted: 'bg-blue-100 text-blue-800',
};

export default function DashboardPage() {
  const { user } = useAuth();

  const { data, isLoading } = useQuery<DashboardMetrics>({
    queryKey: ['dashboard'],
    queryFn: () => api.getDashboardMetrics(),
    refetchInterval: 60000,
  });

  return (
    <DashboardLayout>
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
          <p className="text-gray-500 mt-1">Welcome back, {user?.first_name}!</p>
        </div>

        {/* Onboarding checklist (admins only; self-hides when complete/dismissed) */}
        {user && hasAnyRole(user, ['tenant_admin', 'hr']) && <SetupChecklist />}

        {/* Top KPI cards */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          <KpiCard
            label="Active Employees"
            value={data?.active_employees}
            subtitle={data ? `${data.total_employees} total` : undefined}
            icon={<Users className="h-5 w-5" />}
            color="purple"
            loading={isLoading}
          />
          <KpiCard
            label="Departments"
            value={data?.departments}
            icon={<Building2 className="h-5 w-5" />}
            color="blue"
            loading={isLoading}
          />
          <KpiCard
            label="Pending Leaves"
            value={data?.pending_leaves}
            icon={<Clock className="h-5 w-5" />}
            color="yellow"
            loading={isLoading}
          />
          <KpiCard
            label="Pending Overtime"
            value={data?.pending_overtime}
            icon={<AlertTriangle className="h-5 w-5" />}
            color="orange"
            loading={isLoading}
          />
        </div>

        {/* Today's Attendance + Month-to-Date */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Today */}
          <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
            <h2 className="text-lg font-semibold text-gray-900 mb-4">Today&apos;s Attendance</h2>
            <div className="grid grid-cols-3 gap-4">
              <AttendanceStat
                label="Present"
                value={data?.today_present}
                icon={<CheckCircle className="h-5 w-5 text-green-500" />}
                loading={isLoading}
              />
              <AttendanceStat
                label="Late"
                value={data?.today_late}
                icon={<Clock className="h-5 w-5 text-yellow-500" />}
                loading={isLoading}
              />
              <AttendanceStat
                label="Absent"
                value={data?.today_absent}
                icon={<XCircle className="h-5 w-5 text-red-500" />}
                loading={isLoading}
              />
            </div>
          </div>

          {/* Month-to-Date */}
          <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
            <h2 className="text-lg font-semibold text-gray-900 mb-4">Month-to-Date</h2>
            <div className="grid grid-cols-2 gap-4">
              <MtdStat
                label="Attendance Rate"
                value={data ? `${data.month_attendance_rate}%` : undefined}
                icon={<TrendingUp className="h-4 w-4 text-blue-500" />}
                loading={isLoading}
              />
              <MtdStat
                label="Late Arrivals"
                value={data?.month_late_count}
                icon={<Clock className="h-4 w-4 text-yellow-500" />}
                loading={isLoading}
              />
              <MtdStat
                label="Overtime Hours"
                value={data?.month_ot_hours}
                icon={<AlertTriangle className="h-4 w-4 text-orange-500" />}
                loading={isLoading}
              />
              <MtdStat
                label="Leave Days"
                value={data?.month_leave_days}
                icon={<Calendar className="h-4 w-4 text-purple-500" />}
                loading={isLoading}
              />
            </div>
          </div>
        </div>

        {/* Recent Activity Tables */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Recent Leave Applications */}
          <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
            <h2 className="text-lg font-semibold text-gray-900 mb-4">Recent Leave Applications</h2>
            {isLoading ? (
              <TableSkeleton rows={5} />
            ) : data?.recent_leave_applications.length ? (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-gray-500 border-b">
                      <th className="pb-2 font-medium">Employee</th>
                      <th className="pb-2 font-medium">Type</th>
                      <th className="pb-2 font-medium">Days</th>
                      <th className="pb-2 font-medium">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50">
                    {data.recent_leave_applications.map((la) => (
                      <tr key={la.id}>
                        <td className="py-2 font-medium text-gray-900">{la.employee_name}</td>
                        <td className="py-2 text-gray-600 capitalize">{la.leave_type.replace(/_/g, ' ')}</td>
                        <td className="py-2 text-gray-600">{la.days}</td>
                        <td className="py-2">
                          <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${statusColors[la.status] || 'bg-gray-100 text-gray-800'}`}>
                            {la.status}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="text-gray-500 text-sm">No recent leave applications</p>
            )}
          </div>

          {/* Recent Overtime Logs */}
          <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
            <h2 className="text-lg font-semibold text-gray-900 mb-4">Recent Overtime Logs</h2>
            {isLoading ? (
              <TableSkeleton rows={5} />
            ) : data?.recent_overtime_logs.length ? (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-gray-500 border-b">
                      <th className="pb-2 font-medium">Employee</th>
                      <th className="pb-2 font-medium">Category</th>
                      <th className="pb-2 font-medium">Hours</th>
                      <th className="pb-2 font-medium">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50">
                    {data.recent_overtime_logs.map((ot) => (
                      <tr key={ot.id}>
                        <td className="py-2 font-medium text-gray-900">{ot.employee_name}</td>
                        <td className="py-2 text-gray-600">{ot.category}</td>
                        <td className="py-2 text-gray-600">{ot.hours}h</td>
                        <td className="py-2">
                          <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${statusColors[ot.status] || 'bg-gray-100 text-gray-800'}`}>
                            {ot.status}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="text-gray-500 text-sm">No recent overtime logs</p>
            )}
          </div>
        </div>

        {/* Profile card */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">Your Profile</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <p className="text-sm text-gray-500">Name</p>
              <p className="font-medium">{user?.first_name} {user?.last_name}</p>
            </div>
            <div>
              <p className="text-sm text-gray-500">Email</p>
              <p className="font-medium">{user?.email}</p>
            </div>
            <div>
              <p className="text-sm text-gray-500">Role</p>
              <p className="font-medium capitalize">{user ? getPrimaryRole(user) : ''}</p>
            </div>
            <div>
              <p className="text-sm text-gray-500">Status</p>
              <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800">
                Active
              </span>
            </div>
          </div>
        </div>
      </div>
    </DashboardLayout>
  );
}

function KpiCard({ label, value, subtitle, icon, color, loading }: {
  label: string;
  value?: number;
  subtitle?: string;
  icon: React.ReactNode;
  color: string;
  loading: boolean;
}) {
  const colorMap: Record<string, string> = {
    purple: 'bg-purple-50 text-purple-600',
    blue: 'bg-blue-50 text-blue-600',
    yellow: 'bg-yellow-50 text-yellow-600',
    orange: 'bg-orange-50 text-orange-600',
    green: 'bg-green-50 text-green-600',
  };

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
      <div className="flex items-center justify-between mb-3">
        <p className="text-sm font-medium text-gray-500">{label}</p>
        <div className={`p-2 rounded-lg ${colorMap[color] || colorMap.blue}`}>
          {icon}
        </div>
      </div>
      {loading ? (
        <div className="h-9 w-20 bg-gray-100 rounded animate-pulse" />
      ) : (
        <>
          <p className="text-3xl font-bold text-gray-900">{value?.toLocaleString() ?? '-'}</p>
          {subtitle && <p className="text-xs text-gray-500 mt-1">{subtitle}</p>}
        </>
      )}
    </div>
  );
}

function AttendanceStat({ label, value, icon, loading }: {
  label: string;
  value?: number;
  icon: React.ReactNode;
  loading: boolean;
}) {
  return (
    <div className="text-center">
      <div className="flex justify-center mb-2">{icon}</div>
      {loading ? (
        <div className="h-8 w-12 bg-gray-100 rounded animate-pulse mx-auto" />
      ) : (
        <p className="text-2xl font-bold text-gray-900">{value ?? 0}</p>
      )}
      <p className="text-xs text-gray-500 mt-1">{label}</p>
    </div>
  );
}

function MtdStat({ label, value, icon, loading }: {
  label: string;
  value?: string | number;
  icon: React.ReactNode;
  loading: boolean;
}) {
  return (
    <div className="flex items-center gap-3 p-3 bg-gray-50 rounded-lg">
      {icon}
      <div>
        {loading ? (
          <div className="h-5 w-16 bg-gray-200 rounded animate-pulse" />
        ) : (
          <p className="text-lg font-semibold text-gray-900">{value ?? '-'}</p>
        )}
        <p className="text-xs text-gray-500">{label}</p>
      </div>
    </div>
  );
}

function TableSkeleton({ rows }: { rows: number }) {
  return (
    <div className="space-y-3">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-8 bg-gray-100 rounded animate-pulse" />
      ))}
    </div>
  );
}
