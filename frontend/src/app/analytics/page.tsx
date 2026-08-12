'use client';

import { useState } from 'react';
import dynamic from 'next/dynamic';
import DashboardLayout from '@/components/layout/DashboardLayout';
import { useAuth } from '@/contexts/AuthContext';
import { hasAnyRole } from '@/lib/roles';
import { Skeleton } from '@/components/ui/Skeleton';

// Each tab pulls in recharts (~250KB). Loading them on demand keeps that out of
// the shared bundle, and only the tab actually opened is ever fetched.
const chartLoading = () => <Skeleton variant="rectangular" className="h-96 w-full" />;

const OvertimeAnalyticsTab = dynamic(() => import('./OvertimeAnalyticsTab'), {
  loading: chartLoading,
  ssr: false,
});
const LeaveAnalyticsTab = dynamic(() => import('./LeaveAnalyticsTab'), {
  loading: chartLoading,
  ssr: false,
});
const AttendanceAnalyticsTab = dynamic(() => import('./AttendanceAnalyticsTab'), {
  loading: chartLoading,
  ssr: false,
});

type TabKey = 'overtime' | 'leave' | 'attendance';

const tabs: { key: TabKey; label: string }[] = [
  { key: 'overtime', label: 'Overtime' },
  { key: 'leave', label: 'Leave' },
  { key: 'attendance', label: 'Attendance' },
];

export default function AnalyticsPage() {
  const { user } = useAuth();
  const [activeTab, setActiveTab] = useState<TabKey>('overtime');
  const [year, setYear] = useState<number>(new Date().getFullYear());
  const [startDate, setStartDate] = useState<string>('');
  const [endDate, setEndDate] = useState<string>('');

  const hasAccess = user && hasAnyRole(user, ['tenant_admin', 'hr', 'manager']);

  if (!hasAccess) {
    return (
      <DashboardLayout>
        <div className="text-center py-12">
          <p className="text-gray-500">You do not have access to analytics.</p>
        </div>
      </DashboardLayout>
    );
  }

  const currentYear = new Date().getFullYear();
  const yearOptions = Array.from({ length: 5 }, (_, i) => currentYear - i);

  const clearDateRange = () => {
    setStartDate('');
    setEndDate('');
  };

  const setPreset = (preset: string) => {
    const now = new Date();
    const y = now.getFullYear();
    const m = now.getMonth(); // 0-indexed

    switch (preset) {
      case 'this_month': {
        const s = new Date(y, m, 1);
        const e = new Date(y, m + 1, 0);
        setYear(y);
        setStartDate(fmt(s));
        setEndDate(fmt(e));
        break;
      }
      case 'last_month': {
        const s = new Date(y, m - 1, 1);
        const e = new Date(y, m, 0);
        setYear(s.getFullYear());
        setStartDate(fmt(s));
        setEndDate(fmt(e));
        break;
      }
      case 'this_quarter': {
        const qStart = Math.floor(m / 3) * 3;
        const s = new Date(y, qStart, 1);
        const e = new Date(y, qStart + 3, 0);
        setYear(y);
        setStartDate(fmt(s));
        setEndDate(fmt(e));
        break;
      }
      case 'last_quarter': {
        const qStart = Math.floor(m / 3) * 3 - 3;
        const s = new Date(y, qStart, 1);
        const e = new Date(y, qStart + 3, 0);
        setYear(s.getFullYear());
        setStartDate(fmt(s));
        setEndDate(fmt(e));
        break;
      }
      case 'ytd': {
        setYear(y);
        setStartDate(fmt(new Date(y, 0, 1)));
        setEndDate(fmt(now));
        break;
      }
      case 'full_year': {
        clearDateRange();
        break;
      }
    }
  };

  const hasDateFilter = startDate || endDate;

  return (
    <DashboardLayout>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Analytics</h1>
            <p className="text-gray-500 mt-1">Monthly trends for overtime, leave, and attendance.</p>
          </div>
        </div>

        {/* Filters Row */}
        <div className="bg-white border border-gray-200 rounded-xl p-4 space-y-3">
          <div className="flex flex-wrap items-end gap-4">
            {/* Year */}
            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1">Year</label>
              <select
                value={year}
                onChange={(e) => { setYear(Number(e.target.value)); clearDateRange(); }}
                className="px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-transparent outline-none text-sm bg-white"
              >
                {yearOptions.map((y) => (
                  <option key={y} value={y}>{y}</option>
                ))}
              </select>
            </div>

            {/* Start Date */}
            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1">From</label>
              <input
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
                className="px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-transparent outline-none text-sm bg-white"
              />
            </div>

            {/* End Date */}
            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1">To</label>
              <input
                type="date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
                className="px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-transparent outline-none text-sm bg-white"
              />
            </div>

            {/* Clear */}
            {hasDateFilter && (
              <button
                onClick={clearDateRange}
                className="px-3 py-2 text-sm text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-lg transition-colors"
              >
                Clear dates
              </button>
            )}
          </div>

          {/* Quick Presets */}
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-gray-400 mr-1">Quick:</span>
            {[
              { key: 'this_month', label: 'This Month' },
              { key: 'last_month', label: 'Last Month' },
              { key: 'this_quarter', label: 'This Quarter' },
              { key: 'last_quarter', label: 'Last Quarter' },
              { key: 'ytd', label: 'Year to Date' },
              { key: 'full_year', label: 'Full Year' },
            ].map((p) => (
              <button
                key={p.key}
                onClick={() => setPreset(p.key)}
                className="px-2.5 py-1 rounded-full text-xs font-medium bg-gray-100 text-gray-600 hover:bg-purple-100 hover:text-purple-700 transition-colors"
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>

        {/* Tabs */}
        <div className="border-b border-gray-200">
          <nav className="-mb-px flex space-x-8">
            {tabs.map((tab) => (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab.key)}
                className={`whitespace-nowrap border-b-2 py-3 px-1 text-sm font-medium transition-colors ${
                  activeTab === tab.key
                    ? 'border-purple-500 text-purple-600'
                    : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </nav>
        </div>

        {/* Tab content */}
        {activeTab === 'overtime' && <OvertimeAnalyticsTab year={year} startDate={startDate} endDate={endDate} />}
        {activeTab === 'leave' && <LeaveAnalyticsTab year={year} startDate={startDate} endDate={endDate} />}
        {activeTab === 'attendance' && <AttendanceAnalyticsTab year={year} startDate={startDate} endDate={endDate} />}
      </div>
    </DashboardLayout>
  );
}

function fmt(d: Date): string {
  return d.toISOString().split('T')[0];
}
