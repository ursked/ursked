'use client';

import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import { format, parseISO } from 'date-fns';
import { AlertTriangle, CheckCircle2, KeyRound, Server, UserX, Users } from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import { api } from '@/lib/api';
import { AdminOverview, AdminOverviewJob, BackgroundJobsView } from '@/types';
import SetupChecklist from '@/components/SetupChecklist';
import { titleFor } from '@/components/layout/RouteTitle';
import { hasEmployeeWorkspace } from '@/lib/workspace';

// The admin dashboard: ADMINISTRATION, nothing operational. "A manager for
// graphics is not an administrator of the app": schedules, leave decisions,
// attendance, finances and reports are done from the regular (or finance)
// dashboard by the people holding the role for each. So this screen decides
// nothing and links into none of those screens. Its questions are the
// administrator's: is the system set up, is it running, does every account
// have a role, and has someone been given each job? When nobody has, the
// fix is on Employees (give someone, or yourself, the role).

// Read like the Employees role picker names them.
const ROLE_LABEL: Record<string, string> = {
  manager: 'Manager',
  hr: 'HR',
  schedule_editor: 'Schedule editor',
  leave_approver: 'Leave approver',
  report_viewer: 'Reports & data',
  finance: 'Finance',
};

const JOB_VERB: Record<AdminOverviewJob['key'], string> = {
  schedules: 'manage schedules',
  leave: 'approve leave',
  reports: 'run reports',
  finance: 'run payroll',
};

function orList(items: string[]): string {
  if (items.length <= 1) return items.join('');
  return `${items.slice(0, -1).join(', ')} or ${items[items.length - 1]}`;
}

const rolesOf = (job: AdminOverviewJob) => orList(job.roles.map((r) => ROLE_LABEL[r] ?? r));

function dateRange(start: string, end: string): string {
  const from = format(parseISO(start), 'd MMM');
  return end !== start ? `${from} – ${format(parseISO(end), 'd MMM')}` : from;
}

export default function AdminDashboard({ ownPath, opsPath }: { ownPath: string | null; opsPath: string | null }) {
  const { user, exitAdmin } = useAuth();

  const overview = useQuery<AdminOverview>({
    queryKey: ['admin-dashboard', 'overview'],
    queryFn: () => api.getAdminOverview(),
    refetchInterval: 60000,
    enabled: !!user,
    meta: { handlesErrors: true },
  });

  const jobs = useQuery<BackgroundJobsView>({
    queryKey: ['admin-dashboard', 'jobs'],
    queryFn: () => api.getBackgroundJobs(),
    refetchInterval: 60000,
    meta: { handlesErrors: true },
  });

  const ownScreen = ownPath ? titleFor(ownPath) ?? 'That screen' : null;
  const opsScreen = opsPath ? titleFor(opsPath) ?? 'That screen' : null;
  const data = overview.data;
  const stuckLeave = data?.leave_without_approver ?? [];
  const nobodyApproves = !!data && (data.nobody_can_approve_leave || stuckLeave.length > 0);

  const exitButton = hasEmployeeWorkspace(user) && (
    <button
      type="button"
      onClick={() => void exitAdmin()}
      className="mt-3 inline-flex min-h-[44px] flex-shrink-0 items-center justify-center rounded-lg bg-gray-900 px-4 py-2 text-sm font-semibold text-white hover:bg-gray-800 sm:mt-0"
    >
      Go to my employee dashboard
    </button>
  );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Admin Dashboard</h1>
        <p className="mt-1 text-gray-500">Setting up and running the system: accounts, roles, settings and policies.</p>
      </div>

      {ownScreen && (
        <div role="status" className="rounded-xl border border-amber-300 bg-amber-50 p-4 sm:flex sm:items-center sm:justify-between sm:gap-4">
          <div className="min-w-0">
            <p className="text-sm font-medium text-amber-900">{ownScreen} is on your employee dashboard.</p>
            <p className="mt-0.5 text-sm text-amber-800">
              Your own schedule, leave, time clock and payslips are kept out of admin mode.
            </p>
          </div>
          {exitButton}
        </div>
      )}

      {opsScreen && (
        <div role="status" className="rounded-xl border border-amber-300 bg-amber-50 p-4 sm:flex sm:items-center sm:justify-between sm:gap-4">
          <div className="min-w-0">
            <p className="text-sm font-medium text-amber-900">{opsScreen} is not part of the admin dashboard.</p>
            <p className="mt-0.5 text-sm text-amber-800">
              This is done from the regular dashboard by people with that role — sign in normally.
            </p>
          </div>
          {exitButton}
        </div>
      )}

      {nobodyApproves && <NobodyApprovesLeave stuck={stuckLeave} />}

      {overview.isError && !data && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-6 text-center" role="alert">
          <p className="text-sm font-medium text-red-800">Could not load the overview.</p>
          <button
            type="button"
            onClick={() => overview.refetch()}
            className="mt-3 rounded-md bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-700"
          >
            Retry
          </button>
        </div>
      )}

      <SetupChecklist />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {data && <JobCoverage jobs={data.jobs} />}
        <JobsStatus view={jobs.data} error={jobs.isError} />
        {data && data.salary_requests_pending !== null && (
          <SalaryRequests pending={data.salary_requests_pending} />
        )}
        {data && <UsersWithoutRoles users={data.users_without_roles} />}
      </div>
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

const linkCls = 'text-sm font-medium text-purple-600 hover:text-purple-700';

/** Leave requests are waiting and nobody can decide them. The administrator
 * cannot either (approving is not administration); the fix is a role. Plain
 * text on purpose: there is no leave screen in the admin dashboard. */
function NobodyApprovesLeave({ stuck }: { stuck: AdminOverview['leave_without_approver'] }) {
  return (
    <div role="alert" className="rounded-xl border border-red-300 bg-red-50 p-4">
      <div className="flex items-start gap-3">
        <AlertTriangle className="mt-0.5 h-5 w-5 flex-shrink-0 text-red-600" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-red-900">
            Nobody can approve leave — give someone the HR or Leave approver role.
          </p>
          <p className="mt-0.5 text-sm text-red-800">
            Leave requests wait until someone with that role decides them. If that should be you, give yourself the
            role on your own employee record and approve from your regular dashboard.
          </p>
          {stuck.length > 0 && (
            <>
              <p className="mt-3 text-sm font-medium text-red-900">
                {stuck.length} {stuck.length === 1 ? 'request is' : 'requests are'} waiting:
              </p>
              <ul className="mt-1 space-y-0.5 text-sm text-red-800">
                {stuck.map((r) => (
                  <li key={r.id} className="flex flex-wrap items-baseline justify-between gap-x-3">
                    <span className="min-w-0 truncate">{r.employee_name}</span>
                    <span className="whitespace-nowrap">{dateRange(r.start_date, r.end_date)}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
          <Link
            href="/employees"
            className="mt-3 inline-flex min-h-[44px] items-center rounded-lg bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-700"
          >
            Give someone the role
          </Link>
        </div>
      </div>
    </div>
  );
}

/** Has someone been given each of the company's jobs? */
function JobCoverage({ jobs }: { jobs: AdminOverviewJob[] }) {
  const missing = jobs.filter((j) => j.holders === 0);
  return (
    <Card
      title="Who does the work"
      icon={<Users className="h-5 w-5" />}
      footer={<Link href="/employees" className={linkCls}>Give roles on Employees</Link>}
    >
      <p className="mb-3 text-sm text-gray-600">
        Schedules, leave, reports and payroll are done by the people holding the role for each, from their own
        dashboard. Administrators give the roles.
      </p>
      <ul className="space-y-2 text-sm">
        {jobs.map((job) =>
          job.holders === 0 ? (
            <li key={job.key} className="flex items-start gap-2 text-gray-900">
              <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0 text-amber-600" aria-hidden="true" />
              <span className="min-w-0">
                Nobody has been given a role to {JOB_VERB[job.key]} — give someone (or yourself) {rolesOf(job)}.
              </span>
            </li>
          ) : (
            <li key={job.key} className="flex items-start gap-2 text-gray-700">
              <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-green-600" aria-hidden="true" />
              <span className="min-w-0">
                {job.label}: {job.holders} {job.holders === 1 ? 'person' : 'people'}
                <span className="text-gray-500"> ({rolesOf(job)})</span>
              </span>
            </li>
          ),
        )}
      </ul>
      {missing.length === 0 && (
        <p className="mt-3 text-xs text-gray-500">Every job has someone to do it.</p>
      )}
    </Card>
  );
}

function SalaryRequests({ pending }: { pending: number }) {
  return (
    <Card
      title="Salary access requests"
      icon={<KeyRound className="h-5 w-5" />}
      footer={<Link href="/salary-access" className={linkCls}>Open Salary access</Link>}
    >
      {pending === 0 ? (
        <p className="text-sm text-gray-500">No requests are waiting for you.</p>
      ) : (
        <p className="text-sm text-gray-900">
          {pending} {pending === 1 ? 'request is' : 'requests are'} waiting for your decision.
        </p>
      )}
    </Card>
  );
}

function UsersWithoutRoles({ users }: { users: AdminOverview['users_without_roles'] }) {
  return (
    <Card title="Accounts without a role" icon={<UserX className="h-5 w-5" />}>
      {users.length === 0 ? (
        <p className="flex items-center gap-2 text-sm text-gray-700">
          <CheckCircle2 className="h-4 w-4 text-green-600" aria-hidden="true" />
          Every active account has a role.
        </p>
      ) : (
        <>
          <p className="mb-2 text-sm text-gray-600">
            These accounts cannot do anything yet, not even see their own schedule. Open each one and give it a role.
          </p>
          <ul className="divide-y divide-gray-50 text-sm">
            {users.map((u) => (
              <li key={u.id} className="flex min-w-0 flex-wrap items-baseline justify-between gap-x-3 py-1.5">
                <Link href={`/employees?open=${u.id}`} className="min-w-0 truncate font-medium text-purple-600 hover:text-purple-700">
                  {u.name || u.email}
                </Link>
                <span className="min-w-0 truncate text-gray-500">{u.email}</span>
              </li>
            ))}
          </ul>
        </>
      )}
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
        <Link href="/settings?tab=jobs" className={linkCls}>
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
