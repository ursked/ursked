'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { getColor } from '@/lib/chart-colors';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer,
} from 'recharts';
import type { OvertimeTrendsResponse, OvertimePaidUnpaidResponse } from '@/types';

interface Props {
  year: number;
  startDate?: string;
  endDate?: string;
}

export default function OvertimeAnalyticsTab({ year, startDate, endDate }: Props) {
  const [statusFilter, setStatusFilter] = useState<string>('approved');

  const { data: trends, isLoading: trendsLoading, isError: trendsError, refetch: refetchTrends } = useQuery<OvertimeTrendsResponse>({
    queryKey: ['analytics', 'overtime', 'trends', year, statusFilter, startDate, endDate],
    queryFn: () => api.getOvertimeTrends({
      year,
      status: statusFilter || undefined,
      start_date: startDate || undefined,
      end_date: endDate || undefined,
    }),
  });

  const { data: paidUnpaid, isLoading: puLoading, isError: puError, refetch: refetchPu } = useQuery<OvertimePaidUnpaidResponse>({
    queryKey: ['analytics', 'overtime', 'paid-unpaid', year, statusFilter, startDate, endDate],
    queryFn: () => api.getOvertimePaidUnpaid({
      year,
      status: statusFilter || undefined,
      start_date: startDate || undefined,
      end_date: endDate || undefined,
    }),
  });

  const isLoading = trendsLoading || puLoading;
  const isError = trendsError || puError;

  // Transform for stacked bar: convert minutes to hours per category
  const stackedData = trends?.months.map((m) => {
    const point: Record<string, string | number> = { month_label: m.month_label };
    for (const cat of trends.categories) {
      point[cat.code] = Math.round(((m.by_category[cat.code] || 0) / 60) * 10) / 10;
    }
    return point;
  }) ?? [];

  // Transform for paid vs unpaid
  const paidUnpaidData = paidUnpaid?.months.map((m) => ({
    month_label: m.month_label,
    'Paid OT': m.paid_hours,
    'Unpaid OT': m.unpaid_hours,
  })) ?? [];

  // KPIs
  const totalHours = trends?.months.reduce((s, m) => s + m.total_hours, 0) ?? 0;
  const totalPay = trends?.months.reduce((s, m) => s + m.total_pay, 0) ?? 0;
  const totalLogs = trends?.months.reduce((s, m) => s + m.log_count, 0) ?? 0;
  const avgMonthly = totalHours > 0 ? Math.round((totalHours / 12) * 10) / 10 : 0;

  const statusOptions = [
    { value: 'approved', label: 'Approved Only' },
    { value: '', label: 'All Statuses' },
  ];

  return (
    <div className="space-y-6">
      {/* Status filter */}
      <div className="flex items-center gap-2">
        <span className="text-sm text-gray-500">Show:</span>
        {statusOptions.map((opt) => (
          <button
            key={opt.value}
            onClick={() => setStatusFilter(opt.value)}
            className={`px-3 py-1.5 rounded-full text-xs font-medium transition-colors ${
              statusFilter === opt.value
                ? 'bg-purple-100 text-purple-700'
                : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
            }`}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-white border border-gray-200 rounded-xl p-5">
          <p className="text-sm text-gray-500">Total OT Hours</p>
          <p className="mt-1 text-2xl font-bold text-gray-900">{totalHours.toLocaleString()}</p>
        </div>
        <div className="bg-white border border-gray-200 rounded-xl p-5">
          <p className="text-sm text-gray-500">Total OT Pay</p>
          <p className="mt-1 text-2xl font-bold text-gray-900">{totalPay.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</p>
        </div>
        <div className="bg-white border border-gray-200 rounded-xl p-5">
          <p className="text-sm text-gray-500">Total OT Logs</p>
          <p className="mt-1 text-2xl font-bold text-gray-900">{totalLogs.toLocaleString()}</p>
        </div>
        <div className="bg-white border border-gray-200 rounded-xl p-5">
          <p className="text-sm text-gray-500">Avg Monthly Hours</p>
          <p className="mt-1 text-2xl font-bold text-gray-900">{avgMonthly}</p>
        </div>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-16">
          <svg className="w-8 h-8 animate-spin text-purple-500" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
        </div>
      ) : isError ? (
        <div className="rounded-xl border border-red-200 bg-red-50 p-6 text-center">
          <p className="text-sm font-medium text-red-800">Could not load overtime analytics.</p>
          <p className="mt-1 text-xs text-red-700">The server did not return data for this period.</p>
          <button
            type="button"
            onClick={() => { refetchTrends(); refetchPu(); }}
            className="mt-4 rounded-md bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-700"
          >
            Retry
          </button>
        </div>
      ) : (
        <>
          {/* Chart 1: Stacked bar by category */}
          <div className="bg-white border border-gray-200 rounded-xl shadow-sm p-6">
            <h3 className="text-sm font-semibold text-gray-900 mb-4">Overtime by Category (Monthly Hours)</h3>
            {trends && trends.categories.length > 0 ? (
              <ResponsiveContainer width="100%" height={350}>
                <BarChart data={stackedData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                  <XAxis dataKey="month_label" tick={{ fontSize: 12 }} />
                  <YAxis tick={{ fontSize: 12 }} label={{ value: 'Hours', angle: -90, position: 'insideLeft', style: { fontSize: 12 } }} />
                  <Tooltip />
                  <Legend />
                  {trends.categories.map((cat, idx) => (
                    <Bar key={cat.code} dataKey={cat.code} name={cat.name} stackId="overtime" fill={getColor(idx)} />
                  ))}
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="text-center py-12 text-gray-400">
                <p className="text-sm">No overtime categories configured yet.</p>
                <p className="text-xs mt-1">Create overtime categories in Policies to see data here.</p>
              </div>
            )}
          </div>

          {/* Chart 2: Paid vs Unpaid */}
          <div className="bg-white border border-gray-200 rounded-xl shadow-sm p-6">
            <h3 className="text-sm font-semibold text-gray-900 mb-4">Paid vs Unpaid Overtime (Monthly Hours)</h3>
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={paidUnpaidData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis dataKey="month_label" tick={{ fontSize: 12 }} />
                <YAxis tick={{ fontSize: 12 }} />
                <Tooltip />
                <Legend />
                <Bar dataKey="Paid OT" fill="#10b981" />
                <Bar dataKey="Unpaid OT" fill="#f59e0b" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </>
      )}
    </div>
  );
}
