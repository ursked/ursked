'use client';

import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import { format, parseISO } from 'date-fns';
import { CalendarClock, CheckCircle2, ClipboardCheck, Wallet } from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import { api } from '@/lib/api';
import { useCurrency } from '@/lib/currency';
import { PayoutSchedule, PayrollPeriod } from '@/types';
import { titleFor } from '@/components/layout/RouteTitle';
import { ADMIN_LOGIN_PATH, hasEmployeeWorkspace, isAdminEligible } from '@/lib/workspace';

// The finance dashboard (finance session): where payroll stands. The same
// payroll calendar the Payroll tab reads (finances:view); totals come back
// only for someone another person has approved for salary access, and are
// shown only when they do. Nothing here decides anything: the sign-offs are
// on the Payroll tab.

// The payroll run's life (payroll_service): draft -> computing -> computed
// (or compute_failed) -> approved -> finalized. Approve and finalize are the
// sign-offs, each by someone other than whoever computed the run.
const STATUS_LABEL: Record<string, string> = {
  draft: 'Draft',
  computing: 'Computing',
  computed: 'Computed',
  compute_failed: 'Compute failed',
  approved: 'Approved',
  finalized: 'Finalized',
};

const STATUS_COLORS: Record<string, string> = {
  draft: 'bg-gray-100 text-gray-700',
  computing: 'bg-yellow-100 text-yellow-700',
  computed: 'bg-blue-100 text-blue-700',
  compute_failed: 'bg-red-100 text-red-700',
  approved: 'bg-green-100 text-green-700',
  finalized: 'bg-purple-100 text-purple-700',
};

// What each waiting status needs next.
const NEXT_STEP: Record<string, string> = {
  computed: 'waiting to be approved',
  approved: 'waiting to be finalized',
  compute_failed: 'compute failed; run it again',
};

const FREQUENCY_LABEL: Record<PayoutSchedule['frequency'], string> = {
  semi_monthly: 'Semi-monthly',
  monthly: 'Monthly',
  weekly: 'Weekly',
  bi_weekly: 'Every two weeks',
};

const day = (d: string) => format(parseISO(d), 'd MMM yyyy');
const range = (a: string, b: string) => `${format(parseISO(a), 'd MMM')} – ${day(b)}`;

export default function FinanceDashboard({ ownPath, adminPath }: { ownPath: string | null; adminPath: string | null }) {
  const { user, exitFinance } = useAuth();
  const { format: money } = useCurrency();

  const periods = useQuery<PayrollPeriod[]>({
    queryKey: ['finance-dashboard', 'periods'],
    queryFn: () => api.getPayrollPeriods(),
    refetchInterval: 60000,
    enabled: !!user,
    meta: { handlesErrors: true },
  });

  const schedule = useQuery<PayoutSchedule | null>({
    queryKey: ['finance-dashboard', 'payout-schedule'],
    queryFn: () => api.getActivePayoutSchedule(),
    enabled: !!user,
    meta: { handlesErrors: true },
  });

  const ownScreen = ownPath ? titleFor(ownPath) ?? 'That screen' : null;
  const adminScreen = adminPath ? titleFor(adminPath) ?? 'That screen' : null;

  const all = periods.data ?? [];
  const latest = [...all].sort((a, b) => b.start_date.localeCompare(a.start_date)).slice(0, 5);
  const waiting = all.filter((p) => NEXT_STEP[p.status as string]);
  const today = format(new Date(), 'yyyy-MM-dd');
  const nextPayout = all
    .filter((p) => p.status !== 'finalized' && p.payout_date && p.payout_date >= today)
    .sort((a, b) => (a.payout_date ?? '').localeCompare(b.payout_date ?? ''))[0];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Finance Dashboard</h1>
        <p className="mt-1 text-gray-500">Where payroll stands, and what is waiting for a sign-off.</p>
      </div>

      {ownScreen && (
        <div role="status" className="rounded-xl border border-emerald-300 bg-emerald-50 p-4 sm:flex sm:items-center sm:justify-between sm:gap-4">
          <div className="min-w-0">
            <p className="text-sm font-medium text-emerald-900">This is in your employee dashboard.</p>
            <p className="mt-0.5 text-sm text-emerald-800">
              {ownScreen} is not part of finance mode. Your own things, and any other work your roles give you, are
              in your employee dashboard.
            </p>
          </div>
          {hasEmployeeWorkspace(user) && (
            <button
              type="button"
              onClick={() => void exitFinance()}
              className="mt-3 inline-flex min-h-[44px] flex-shrink-0 items-center justify-center rounded-lg bg-gray-900 px-4 py-2 text-sm font-semibold text-white hover:bg-gray-800 sm:mt-0"
            >
              Go to my employee dashboard
            </button>
          )}
        </div>
      )}

      {adminScreen && (
        <div role="status" className="rounded-xl border border-amber-300 bg-amber-50 p-4 sm:flex sm:items-center sm:justify-between sm:gap-4">
          <div className="min-w-0">
            <p className="text-sm font-medium text-amber-900">{adminScreen} is part of the admin dashboard.</p>
            <p className="mt-0.5 text-sm text-amber-800">
              {isAdminEligible(user)
                ? 'Administration has its own sign-in.'
                : 'An administrator looks after it.'}
            </p>
          </div>
          {isAdminEligible(user) && (
            <Link
              href={ADMIN_LOGIN_PATH}
              className="mt-3 inline-flex min-h-[44px] flex-shrink-0 items-center justify-center rounded-lg bg-gray-900 px-4 py-2 text-sm font-semibold text-white hover:bg-gray-800 sm:mt-0"
            >
              Administrator sign-in
            </Link>
          )}
        </div>
      )}

      {periods.isError && !periods.data && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-6 text-center" role="alert">
          <p className="text-sm font-medium text-red-800">Could not load the payroll calendar.</p>
          <button
            type="button"
            onClick={() => periods.refetch()}
            className="mt-3 rounded-md bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-700"
          >
            Retry
          </button>
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card
          title="Pending sign-offs"
          icon={<ClipboardCheck className="h-5 w-5" />}
          footer={<Link href="/finances?tab=payroll" className={linkCls}>Open Payroll</Link>}
        >
          {periods.isLoading && <Skeleton />}
          {periods.data && waiting.length === 0 && (
            <p className="flex items-center gap-2 text-sm text-gray-700">
              <CheckCircle2 className="h-4 w-4 text-green-600" aria-hidden="true" />
              No payroll run is waiting for a sign-off.
            </p>
          )}
          {waiting.length > 0 && (
            <ul className="space-y-1.5 text-sm">
              {waiting.map((p) => (
                <li key={p.id} className="flex min-w-0 flex-wrap items-baseline justify-between gap-x-3">
                  <span className="min-w-0 truncate font-medium text-gray-900">{p.name}</span>
                  <span className="text-gray-600">{NEXT_STEP[p.status as string]}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Next payout" icon={<CalendarClock className="h-5 w-5" />}>
          {periods.isLoading && <Skeleton />}
          {periods.data && nextPayout && (
            <div className="text-sm">
              <p className="text-lg font-semibold text-gray-900">{day(nextPayout.payout_date as string)}</p>
              <p className="mt-0.5 text-gray-600">
                {nextPayout.name} ({STATUS_LABEL[nextPayout.status as string] ?? nextPayout.status})
              </p>
            </div>
          )}
          {periods.data && !nextPayout && schedule.data && (
            <p className="text-sm text-gray-700">
              No upcoming payroll period has a payout date yet. The company pays on the{' '}
              <span className="font-medium">{schedule.data.name}</span> schedule (
              {FREQUENCY_LABEL[schedule.data.frequency] ?? schedule.data.frequency}).
            </p>
          )}
          {periods.data && !nextPayout && schedule.isFetched && !schedule.data && (
            <p className="text-sm text-gray-500">
              No payout date is set, and there is no payout schedule yet. Set one up under Finances, Payout Schedule.
            </p>
          )}
        </Card>
      </div>

      <Card
        title="Payroll status"
        icon={<Wallet className="h-5 w-5" />}
        footer={<Link href="/finances" className={linkCls}>Open Finances</Link>}
      >
        {periods.isLoading && <Skeleton />}
        {periods.data && latest.length === 0 && (
          <p className="text-sm text-gray-500">No payroll periods yet. Create the first one on the Payroll tab.</p>
        )}
        {latest.length > 0 && (
          <ul className="divide-y divide-gray-50">
            {latest.map((p) => {
              const showTotals = !p.figures_hidden && typeof p.total_net === 'number';
              return (
                <li key={p.id} className="flex min-w-0 flex-wrap items-center justify-between gap-x-4 gap-y-1 py-2.5">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-gray-900">{p.name}</p>
                    <p className="text-xs text-gray-500">
                      {range(p.start_date, p.end_date)}
                      {p.payout_date ? ` · paid ${day(p.payout_date)}` : ''}
                    </p>
                  </div>
                  <div className="flex flex-shrink-0 items-center gap-3">
                    {showTotals && (
                      <span className="text-sm text-gray-700" title="Net pay for the period">
                        {money(p.total_net as number)}
                      </span>
                    )}
                    <span
                      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_COLORS[p.status as string] ?? 'bg-gray-100 text-gray-700'}`}
                    >
                      {STATUS_LABEL[p.status as string] ?? p.status}
                    </span>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
        {latest.some((p) => p.figures_hidden) && (
          <p className="mt-3 text-xs text-gray-500">
            Totals are shown only to people another person has approved for{' '}
            <Link href="/salary-access" className="font-medium text-purple-600 hover:text-purple-700">salary access</Link>.
          </p>
        )}
      </Card>
    </div>
  );
}

const linkCls = 'text-sm font-medium text-purple-600 hover:text-purple-700';

function Skeleton() {
  return (
    <div className="space-y-2">
      <div className="h-4 rounded bg-gray-100 animate-pulse" />
      <div className="h-4 w-2/3 rounded bg-gray-100 animate-pulse" />
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
        <span className="rounded-lg bg-emerald-50 p-1.5 text-emerald-700">{icon}</span>
        <h2 className="text-lg font-semibold text-gray-900">{title}</h2>
      </div>
      <div className="flex-1">{children}</div>
      {footer && <div className="mt-4">{footer}</div>}
    </section>
  );
}
