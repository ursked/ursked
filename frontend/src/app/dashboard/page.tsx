'use client';

import { Suspense } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import { format, parseISO } from 'date-fns';
import { CalendarDays, Palmtree, Hourglass, Timer } from 'lucide-react';
import DashboardLayout from '@/components/layout/DashboardLayout';
import { useAuth } from '@/contexts/AuthContext';
import { getPrimaryRole, hasAnyRole } from '@/lib/roles';
import { api } from '@/lib/api';
import { HomeDashboard, PersonalDashboard } from '@/types';
import SetupChecklist from '@/components/SetupChecklist';
import { titleFor } from '@/components/layout/RouteTitle';
import {
  ADMIN_LOGIN_PATH,
  FINANCE_LOGIN_PATH,
  hasOtherDashboard,
  isAdminEligible,
  isFinanceEligible,
  workspaceOf,
} from '@/lib/workspace';
import AdminDashboard from './AdminDashboard';
import FinanceDashboard from './FinanceDashboard';
import { MetricsSection } from './MetricsSection';

// One person, up to three dashboards. An admin session gets the admin
// dashboard (setup, accounts and roles, background jobs: administration
// only), a finance session the finance dashboard (payroll), and every other
// session the employee dashboard below, an administrator's or finance
// person's included. `?admin=` / `?own=` / `?ops=` / `?finance=` are set by
// DashboardLayout when it turned someone away from a screen that lives in
// another dashboard.
export default function DashboardPage() {
  return (
    <DashboardLayout>
      <Suspense>
        <DashboardSwitch />
      </Suspense>
    </DashboardLayout>
  );
}

function DashboardSwitch() {
  const { user } = useAuth();
  const params = useSearchParams();
  const workspace = workspaceOf(user);
  if (workspace === 'admin') return <AdminDashboard ownPath={params.get('own')} opsPath={params.get('ops')} />;
  if (workspace === 'finance') return <FinanceDashboard ownPath={params.get('own')} adminPath={params.get('admin')} />;
  return <EmployeeDashboard adminPath={params.get('admin')} financePath={params.get('finance')} />;
}

/** Shown in an employee session when an administrator opened an admin screen. */
function AdminScreenNotice({ path }: { path: string }) {
  const screen = titleFor(path) ?? 'That screen';
  return (
    <div role="status" className="rounded-xl border border-amber-300 bg-amber-50 p-4 sm:flex sm:items-center sm:justify-between sm:gap-4">
      <div className="min-w-0">
        <p className="text-sm font-medium text-amber-900">{screen} is part of the admin dashboard.</p>
        <p className="mt-0.5 text-sm text-amber-800">
          You are signed in to your employee dashboard, where your administrator role is switched off.
        </p>
      </div>
      <Link
        href={ADMIN_LOGIN_PATH}
        className="mt-3 inline-flex min-h-[44px] flex-shrink-0 items-center justify-center rounded-lg bg-gray-900 px-4 py-2 text-sm font-semibold text-white hover:bg-gray-800 sm:mt-0"
      >
        Administrator sign-in
      </Link>
    </div>
  );
}

/** Shown in an employee session when someone opened a finance screen. Only
 * the finance role opens Finances, and only from the finance sign-in. */
function FinanceScreenNotice({ path, eligible }: { path: string; eligible: boolean }) {
  const screen = titleFor(path) ?? 'That screen';
  if (!eligible) {
    return (
      <div role="status" className="rounded-xl border border-gray-200 bg-white p-4">
        <p className="text-sm font-medium text-gray-900">Finances are managed by the finance team.</p>
      </div>
    );
  }
  return (
    <div role="status" className="rounded-xl border border-emerald-300 bg-emerald-50 p-4 sm:flex sm:items-center sm:justify-between sm:gap-4">
      <div className="min-w-0">
        <p className="text-sm font-medium text-emerald-900">{screen} is part of the finance dashboard.</p>
        <p className="mt-0.5 text-sm text-emerald-800">
          You are signed in to your employee dashboard, where your finance role is switched off.
        </p>
      </div>
      <Link
        href={FINANCE_LOGIN_PATH}
        className="mt-3 inline-flex min-h-[44px] flex-shrink-0 items-center justify-center rounded-lg bg-gray-900 px-4 py-2 text-sm font-semibold text-white hover:bg-gray-800 sm:mt-0"
      >
        Finance sign-in
      </Link>
    </div>
  );
}

// The dashboard used to ask for company metrics only, which three roles could
// read; everyone else got a 403 on load and on every 60-second refresh and saw
// a page of dashes. The endpoint now answers everyone: a personal block for all,
// plus metrics (company-wide or team-scoped) for reports:view holders.
function EmployeeDashboard({ adminPath, financePath }: { adminPath: string | null; financePath: string | null }) {
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
      <div className="space-y-6">
        <div>
          {/* "My" only where there is an admin or finance dashboard to tell it from. */}
          <h1 className="text-2xl font-bold text-gray-900">{hasOtherDashboard(user) ? 'My Dashboard' : 'Dashboard'}</h1>
          <p className="text-gray-500 mt-1">Welcome back, {user?.first_name}!</p>
        </div>

        {adminPath && isAdminEligible(user) && <AdminScreenNotice path={adminPath} />}
        {financePath && <FinanceScreenNotice path={financePath} eligible={isFinanceEligible(user)} />}

        {/* Onboarding checklist (HR here; administrators see it on the admin
            dashboard; self-hides when complete/dismissed) */}
        {user && hasAnyRole(user, ['hr']) && <SetupChecklist />}

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
        <span className="p-1.5 rounded-lg bg-brand-50 text-brand-600">{icon}</span>
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
        <Link href={href} className="mt-3 text-sm font-medium text-brand-600 hover:text-brand-700">
          {linkLabel}
        </Link>
      )}
    </div>
  );
}
