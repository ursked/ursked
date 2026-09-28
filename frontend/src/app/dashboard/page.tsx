'use client';

import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import { format, parseISO } from 'date-fns';
import { Users, Building2, Clock, AlertTriangle, CheckCircle, XCircle, TrendingUp, Calendar, CalendarDays, Palmtree, Hourglass, Timer } from 'lucide-react';
import DashboardLayout from '@/components/layout/DashboardLayout';
import { useAuth } from '@/contexts/AuthContext';
import { getPrimaryRole, hasAnyRole } from '@/lib/roles';
import { api } from '@/lib/api';
import { HomeDashboard, DashboardMetrics, PersonalDashboard } from '@/types';
import SetupChecklist from '@/components/SetupChecklist';

const statusColors: Record<string, string> = {
  pending: 'bg-yellow-100 text-yellow-800',
  approved: 'bg-green-100 text-green-800',
  rejected: 'bg-red-100 text-red-800',
  converted: 'bg-blue-100 text-blue-800',
};

// The dashboard used to ask for company metrics only, which three roles could
// read; everyone else got a 403 on load and on every 60-second refresh and saw
// a page of dashes. The endpoint now answers everyone: a personal block for all,
// plus metrics (company-wide or team-scoped) for reports:view holders.
export default function DashboardPage() {
  const { user } = useAuth();

  const { data, isLoading, isError, refetch } = useQuery<HomeDashboard>({
    queryKey: ['dashboard', user?.id],
    queryFn: () => api.getHomeDashboard(),
    refetchInterval: 60000,
    enabled: !!user,
    // This screen shows its own error card; the global toast would repeat it
    // on every refresh.
    meta: { handlesErrors: true },
  });

  const metrics = data?.metrics ?? null;

  return (
    <DashboardLayout>
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
          <p className="text-gray-500 mt-1">Welcome back, {user?.first_name}!</p>
        </div>

        {/* Onboarding checklist (admins only; self-hides when complete/dismissed) */}
        {user && hasAnyRole(user, ['tenant_admin', 'hr']) && <SetupChecklist />}

        {isError && !data && (
          <div className="rounded-xl border border-red-200 bg-red-50 p-6 text-center" role="alert">
            <p className="text-sm font-medium text-red-800">Could not load your dashboard.</p>
            <p className="mt-1 text-xs text-red-700">Check your connection and try again.</p>
            <button
              type="button"
              onClick={() => refetch()}
              className="mt-4 rounded-md bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-700"
            >
              Retry
            </button>
          </div>
        )}

        <PersonalSection personal={data?.personal} loading={isLoading} />

        {metrics && data && (
          <MetricsSection metrics={metrics} view={data.view} />
        )}

        {/* Profile card */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">Your Profile</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <p className="text-sm text-gray-500">Name</p>
              <p className="font-medium">{user?.first_name} {user?.last_name}</p>
            </div>
            <div className="min-w-0">
              <p className="text-sm text-gray-500">Email</p>
              <p className="font-medium truncate">{user?.email}</p>
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

// ── Personal: every signed-in user ──────────────────────────────────────────

function PersonalSection({ personal, loading }: { personal?: PersonalDashboard; loading: boolean }) {
  return (
    <section aria-labelledby="dash-personal" className="space-y-3">
      <h2 id="dash-personal" className="text-lg font-semibold text-gray-900">Your week</h2>
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        {/* Next shifts */}
        <PersonalCard
          title="Next shifts"
          icon={<CalendarDays className="h-5 w-5" />}
          href="/my/schedule"
          linkLabel="My schedule"
          loading={loading}
        >
          {personal && personal.next_shifts.length === 0 && (
            <p className="text-sm text-gray-500">No published shifts coming up.</p>
          )}
          {personal && personal.next_shifts.length > 0 && (
            <ul className="space-y-1.5">
              {personal.next_shifts.map((s, i) => (
                <li key={`${s.date}-${i}`} className="flex items-baseline justify-between gap-2 text-sm">
                  <span className="font-medium text-gray-900 whitespace-nowrap">
                    {s.date === personal.today ? 'Today' : format(parseISO(s.date), 'EEE d MMM')}
                  </span>
                  <span className="text-gray-600 truncate text-right">
                    {s.start_time && s.end_time ? `${s.start_time}–${s.end_time}` : s.status_label}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </PersonalCard>

        {/* Leave balance */}
        <PersonalCard
          title="Leave left"
          icon={<Palmtree className="h-5 w-5" />}
          href="/my/leave"
          linkLabel="My leave"
          loading={loading}
        >
          {personal && personal.leave_balances === null && (
            <p className="text-sm text-gray-500">Your leave balance could not be worked out right now.</p>
          )}
          {personal && personal.leave_balances && personal.leave_balances.length === 0 && (
            <p className="text-sm text-gray-500">No leave types apply to you yet.</p>
          )}
          {personal && personal.leave_balances && personal.leave_balances.length > 0 && (
            <ul className="space-y-1.5">
              {personal.leave_balances.slice(0, 4).map((b) => (
                <li key={b.leave_type} className="flex items-baseline justify-between gap-2 text-sm">
                  <span className="text-gray-700 truncate">{b.name}</span>
                  <span className="font-medium text-gray-900 whitespace-nowrap">
                    {b.available_days} {b.available_days === 1 ? 'day' : 'days'}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </PersonalCard>

        {/* Pending requests */}
        <PersonalCard
          title="Waiting for approval"
          icon={<Hourglass className="h-5 w-5" />}
          href="/my/leave"
          linkLabel="See requests"
          loading={loading}
        >
          {personal && (
            <>
              {personal.pending_leave_requests.length === 0 && personal.pending_schedule_requests === 0 ? (
                <p className="text-sm text-gray-500">Nothing is waiting for approval.</p>
              ) : (
                <ul className="space-y-1.5 text-sm">
                  {personal.pending_leave_requests.map((r) => (
                    <li key={r.id} className="flex items-baseline justify-between gap-2">
                      <span className="text-gray-700 capitalize truncate">{r.leave_type.replace(/_/g, ' ')}</span>
                      <span className="text-gray-600 whitespace-nowrap">
                        {format(parseISO(r.start_date), 'd MMM')}
                        {r.end_date !== r.start_date ? ` – ${format(parseISO(r.end_date), 'd MMM')}` : ''}
                      </span>
                    </li>
                  ))}
                  {personal.pending_schedule_requests > 0 && (
                    <li className="text-gray-700">
                      {personal.pending_schedule_requests} schedule{' '}
                      {personal.pending_schedule_requests === 1 ? 'request' : 'requests'}
                    </li>
                  )}
                </ul>
              )}
            </>
          )}
        </PersonalCard>

        {/* Clock status */}
        <PersonalCard
          title="Time clock"
          icon={<Timer className="h-5 w-5" />}
          href={personal?.clock.enabled ? '/my/timeclock' : undefined}
          linkLabel="Open time clock"
          loading={loading}
        >
          {personal && !personal.clock.enabled && (
            <p className="text-sm text-gray-500">Your company does not use the time clock.</p>
          )}
          {personal && personal.clock.enabled && (
            personal.clock.clocked_in ? (
              <p className="text-sm text-gray-900">
                <span className="inline-block w-2 h-2 rounded-full bg-green-500 mr-2 align-middle" aria-hidden="true" />
                Clocked in{personal.clock.since ? ` since ${format(new Date(personal.clock.since), 'HH:mm')}` : ''}
              </p>
            ) : (
              <p className="text-sm text-gray-900">
                <span className="inline-block w-2 h-2 rounded-full bg-gray-300 mr-2 align-middle" aria-hidden="true" />
                Not clocked in
              </p>
            )
          )}
        </PersonalCard>
      </div>
    </section>
  );
}

function PersonalCard({ title, icon, href, linkLabel, loading, children }: {
  title: string;
  icon: React.ReactNode;
  href?: string;
  linkLabel: string;
  loading: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-5 flex flex-col min-w-0">
      <div className="flex items-center gap-2 mb-3">
        <span className="p-1.5 rounded-lg bg-purple-50 text-purple-600">{icon}</span>
        <h3 className="text-sm font-semibold text-gray-900">{title}</h3>
      </div>
      <div className="flex-1">
        {loading ? (
          <div className="space-y-2">
            <div className="h-4 bg-gray-100 rounded animate-pulse" />
            <div className="h-4 w-2/3 bg-gray-100 rounded animate-pulse" />
          </div>
        ) : (
          children
        )}
      </div>
      {href && (
        <Link href={href} className="mt-3 text-sm font-medium text-purple-600 hover:text-purple-700">
          {linkLabel}
        </Link>
      )}
    </div>
  );
}

// ── Metrics: reports:view holders ───────────────────────────────────────────

function MetricsSection({ metrics: data, view }: { metrics: DashboardMetrics; view: HomeDashboard['view'] }) {
  return (
    <section aria-labelledby="dash-metrics" className="space-y-6">
      <div>
        <h2 id="dash-metrics" className="text-lg font-semibold text-gray-900">
          {view === 'team' ? 'Your teams' : 'Company overview'}
        </h2>
        {view === 'team' && (
          <p className="text-sm text-gray-500 mt-0.5">
            These figures cover only the people in the units you head or deputise.
          </p>
        )}
      </div>

      {/* Top KPI cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <KpiCard
          label="Active Employees"
          value={data.active_employees}
          subtitle={`${data.total_employees} total`}
          icon={<Users className="h-5 w-5" />}
          color="purple"
        />
        <KpiCard
          label="Departments"
          value={data.departments}
          icon={<Building2 className="h-5 w-5" />}
          color="blue"
        />
        <KpiCard
          label="Pending Leaves"
          value={data.pending_leaves}
          icon={<Clock className="h-5 w-5" />}
          color="yellow"
        />
        <KpiCard
          label="Pending Overtime"
          value={data.pending_overtime}
          icon={<AlertTriangle className="h-5 w-5" />}
          color="orange"
        />
      </div>

      {/* Today's Attendance + Month-to-Date */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
          <h3 className="text-lg font-semibold text-gray-900 mb-4">Today&apos;s Attendance</h3>
          <div className="grid grid-cols-3 gap-4">
            <AttendanceStat label="Present" value={data.today_present} icon={<CheckCircle className="h-5 w-5 text-green-500" />} />
            <AttendanceStat label="Late" value={data.today_late} icon={<Clock className="h-5 w-5 text-yellow-500" />} />
            <AttendanceStat label="Absent" value={data.today_absent} icon={<XCircle className="h-5 w-5 text-red-500" />} />
          </div>
        </div>

        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
          <h3 className="text-lg font-semibold text-gray-900 mb-4">Month-to-Date</h3>
          <div className="grid grid-cols-2 gap-4">
            <MtdStat label="Attendance Rate" value={`${data.month_attendance_rate}%`} icon={<TrendingUp className="h-4 w-4 text-blue-500" />} />
            <MtdStat label="Late Arrivals" value={data.month_late_count} icon={<Clock className="h-4 w-4 text-yellow-500" />} />
            <MtdStat label="Overtime Hours" value={data.month_ot_hours} icon={<AlertTriangle className="h-4 w-4 text-orange-500" />} />
            <MtdStat label="Leave Days" value={data.month_leave_days} icon={<Calendar className="h-4 w-4 text-purple-500" />} />
          </div>
        </div>
      </div>

      {/* Recent Activity Tables */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
          <h3 className="text-lg font-semibold text-gray-900 mb-4">Recent Leave Applications</h3>
          {data.recent_leave_applications.length ? (
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

        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
          <h3 className="text-lg font-semibold text-gray-900 mb-4">Recent Overtime Logs</h3>
          {data.recent_overtime_logs.length ? (
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
    </section>
  );
}

function KpiCard({ label, value, subtitle, icon, color }: {
  label: string;
  value: number;
  subtitle?: string;
  icon: React.ReactNode;
  color: string;
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
      <p className="text-3xl font-bold text-gray-900">{value.toLocaleString()}</p>
      {subtitle && <p className="text-xs text-gray-500 mt-1">{subtitle}</p>}
    </div>
  );
}

function AttendanceStat({ label, value, icon }: {
  label: string;
  value: number;
  icon: React.ReactNode;
}) {
  return (
    <div className="text-center">
      <div className="flex justify-center mb-2">{icon}</div>
      <p className="text-2xl font-bold text-gray-900">{value}</p>
      <p className="text-xs text-gray-500 mt-1">{label}</p>
    </div>
  );
}

function MtdStat({ label, value, icon }: {
  label: string;
  value: string | number;
  icon: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-3 p-3 bg-gray-50 rounded-lg">
      {icon}
      <div>
        <p className="text-lg font-semibold text-gray-900">{value}</p>
        <p className="text-xs text-gray-500">{label}</p>
      </div>
    </div>
  );
}
