'use client';

import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import { format, parseISO } from 'date-fns';
import { AlertTriangle, CheckCircle2, Inbox, Server } from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import { api } from '@/lib/api';
import { BackgroundJobsView, HomeDashboard, LeaveApplication, ScheduleChangeRequest } from '@/types';
import SetupChecklist from '@/components/SetupChecklist';
import { titleFor } from '@/components/layout/RouteTitle';
import { hasEmployeeWorkspace } from '@/lib/workspace';
import { MetricsSection } from './MetricsSection';

// The admin dashboard (admin mode): running the company, not the admin's own
// week. Their own shifts, leave and payslips are on their employee dashboard.
// Everything here is read with the admin session's full access; figures that
// need salary access are not shown.

interface LeaveList {
  items: LeaveApplication[];
  total: number;
}

export default function AdminDashboard({ ownPath }: { ownPath: string | null }) {
  const { user, exitAdmin } = useAuth();

  const dashboard = useQuery<HomeDashboard>({
    queryKey: ['dashboard', 'admin', user?.id],
    queryFn: () => api.getHomeDashboard(),
    refetchInterval: 60000,
    enabled: !!user,
    meta: { handlesErrors: true },
  });

  const pendingLeave = useQuery<LeaveList>({
    queryKey: ['admin-dashboard', 'pending-leave'],
    queryFn: () =>
      api.getLeaveApplications({ status: 'pending', scope: 'team', per_page: '5' }) as Promise<LeaveList>,
    refetchInterval: 60000,
    meta: { handlesErrors: true },
  });

  const pendingSchedule = useQuery<ScheduleChangeRequest[]>({
    queryKey: ['admin-dashboard', 'pending-schedule'],
    queryFn: () => api.getPendingScheduleApprovals(),
    refetchInterval: 60000,
    meta: { handlesErrors: true },
  });

  const jobs = useQuery<BackgroundJobsView>({
    queryKey: ['admin-dashboard', 'jobs'],
    queryFn: () => api.getBackgroundJobs(),
    refetchInterval: 60000,
    meta: { handlesErrors: true },
  });

  const metrics = dashboard.data?.metrics ?? null;
  const ownScreen = ownPath ? titleFor(ownPath) ?? 'That screen' : null;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Admin Dashboard</h1>
        <p className="mt-1 text-gray-500">Company overview and what needs attention.</p>
      </div>

      {ownScreen && (
        <div role="status" className="rounded-xl border border-amber-300 bg-amber-50 p-4 sm:flex sm:items-center sm:justify-between sm:gap-4">
          <div>
            <p className="text-sm font-medium text-amber-900">{ownScreen} is on your employee dashboard.</p>
            <p className="mt-0.5 text-sm text-amber-800">
              Your own schedule, leave, time clock and payslips are kept out of admin mode.
            </p>
          </div>
          {hasEmployeeWorkspace(user) && (
            <button
              type="button"
              onClick={() => void exitAdmin()}
              className="mt-3 inline-flex min-h-[44px] flex-shrink-0 items-center justify-center rounded-lg bg-gray-900 px-4 py-2 text-sm font-semibold text-white hover:bg-gray-800 sm:mt-0"
            >
              Go to my employee dashboard
            </button>
          )}
        </div>
      )}

      <SetupChecklist />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <ApprovalsQueue
          leave={pendingLeave.data}
          leaveError={pendingLeave.isError}
          scheduleCount={pendingSchedule.data?.length ?? null}
          overtimeCount={metrics?.pending_overtime ?? null}
        />
        <JobsStatus view={jobs.data} error={jobs.isError} />
      </div>

      {dashboard.isError && !dashboard.data && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-6 text-center" role="alert">
          <p className="text-sm font-medium text-red-800">Could not load the company figures.</p>
          <button
            type="button"
            onClick={() => dashboard.refetch()}
            className="mt-3 rounded-md bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-700"
          >
            Retry
          </button>
        </div>
      )}
      {metrics && dashboard.data && <MetricsSection metrics={metrics} view={dashboard.data.view} />}
    </div>
  );
}

function Card({ title, icon, children, footer }: {
  title: string;
  icon: React.ReactNode;
  children: React.ReactNode;
  footer?: React.ReactNode;
}) {
  return (
    <section className="flex min-w-0 flex-col rounded-xl border border-gray-100 bg-white p-6 shadow-sm">
      <div className="mb-4 flex items-center gap-2">
        <span className="rounded-lg bg-gray-100 p-1.5 text-gray-700">{icon}</span>
        <h2 className="text-lg font-semibold text-gray-900">{title}</h2>
      </div>
      <div className="flex-1">{children}</div>
      {footer && <div className="mt-4">{footer}</div>}
    </section>
  );
}

function ApprovalsQueue({ leave, leaveError, scheduleCount, overtimeCount }: {
  leave?: LeaveList;
  leaveError: boolean;
  scheduleCount: number | null;
  overtimeCount: number | null;
}) {
  return (
    <Card
      title="Waiting for a decision"
      icon={<Inbox className="h-5 w-5" />}
      footer={
        <Link href="/leaves" className="text-sm font-medium text-purple-600 hover:text-purple-700">
          Open Leave &amp; Approvals
        </Link>
      }
    >
      {leaveError && <p className="text-sm text-red-700">Could not load pending leave requests.</p>}
      {leave && leave.total === 0 && <p className="text-sm text-gray-500">No leave requests are waiting.</p>}
      {leave && leave.total > 0 && (
        <>
          <p className="mb-2 text-sm text-gray-700">
            {leave.total} leave {leave.total === 1 ? 'request is' : 'requests are'} waiting.
          </p>
          <ul className="divide-y divide-gray-50 text-sm">
            {leave.items.map((la) => (
              <li key={la.id} className="flex items-baseline justify-between gap-3 py-1.5">
                <span className="truncate font-medium text-gray-900">{la.employee_name}</span>
                <span className="whitespace-nowrap text-gray-600">
                  {format(parseISO(la.start_date), 'd MMM')}
                  {la.end_date !== la.start_date ? ` – ${format(parseISO(la.end_date), 'd MMM')}` : ''}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
      <ul className="mt-3 space-y-1 text-sm text-gray-700">
        {scheduleCount !== null && scheduleCount > 0 && (
          <li>
            {scheduleCount} schedule change {scheduleCount === 1 ? 'request' : 'requests'} waiting for you
          </li>
        )}
        {overtimeCount !== null && overtimeCount > 0 && (
          <li>
            {overtimeCount} overtime {overtimeCount === 1 ? 'entry' : 'entries'} to review on{' '}
            <Link href="/attendance" className="font-medium text-purple-600 hover:text-purple-700">Attendance</Link>
          </li>
        )}
      </ul>
    </Card>
  );
}

function JobsStatus({ view, error }: { view?: BackgroundJobsView; error: boolean }) {
  // The latest run of each job: what an administrator wants to know is
  // whether anything is failing now, not the full history (Settings has it).
  const latest = new Map<string, BackgroundJobsView['runs'][number]>();
  for (const run of view?.runs ?? []) {
    const seen = latest.get(run.job_name);
    if (!seen || (run.started_at ?? '') > (seen.started_at ?? '')) latest.set(run.job_name, run);
  }
  const failing = Array.from(latest.values()).filter((r) => r.status === 'failed');
  const failedEmails = view?.outbox.counts.failed ?? 0;

  return (
    <Card
      title="Background jobs"
      icon={<Server className="h-5 w-5" />}
      footer={
        <Link href="/settings?tab=jobs" className="text-sm font-medium text-purple-600 hover:text-purple-700">
          See all jobs
        </Link>
      }
    >
      {error && <p className="text-sm text-red-700">Could not load the background jobs.</p>}
      {view && failing.length === 0 && failedEmails === 0 && (
        <p className="flex items-center gap-2 text-sm text-gray-700">
          <CheckCircle2 className="h-4 w-4 text-green-600" aria-hidden="true" />
          Everything ran as it should.
        </p>
      )}
      {view && (failing.length > 0 || failedEmails > 0) && (
        <ul className="space-y-2 text-sm">
          {failing.map((r) => (
            <li key={r.id} className="flex items-start gap-2 text-gray-800">
              <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0 text-red-600" aria-hidden="true" />
              <span className="min-w-0">
                <span className="font-medium">{r.job_name.replace(/_/g, ' ')}</span> failed
                {r.started_at ? ` at ${format(parseISO(r.started_at), 'd MMM HH:mm')}` : ''}.
              </span>
            </li>
          ))}
          {failedEmails > 0 && (
            <li className="flex items-start gap-2 text-gray-800">
              <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0 text-red-600" aria-hidden="true" />
              <span>
                {failedEmails} {failedEmails === 1 ? 'email' : 'emails'} could not be sent.
              </span>
            </li>
          )}
        </ul>
      )}
      {view && (
        <p className="mt-3 text-xs text-gray-500">
          {view.jobs.length} scheduled {view.jobs.length === 1 ? 'job' : 'jobs'}; {view.outbox.counts.queued} {view.outbox.counts.queued === 1 ? 'email' : 'emails'} queued.
        </p>
      )}
    </Card>
  );
}
