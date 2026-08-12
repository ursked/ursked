'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { getColor } from '@/lib/chart-colors';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer,
} from 'recharts';
import type { LeaveTrendsResponse } from '@/types';

interface Props {
  year: number;
  startDate?: string;
  endDate?: string;
}

export default function LeaveAnalyticsTab({ year, startDate, endDate }: Props) {
  const [statusFilter, setStatusFilter] = useState<string>('approved');

  const { data: trends, isLoading } = useQuery<LeaveTrendsResponse>({
    queryKey: ['analytics', 'leave', 'trends', year, statusFilter, startDate, endDate],
    queryFn: () => api.getLeaveTrends({
      year,
      status: statusFilter || undefined,
      start_date: startDate || undefined,
      end_date: endDate || undefined,
    }),
  });

  // Transform for stacked bar: days per leave type per month
  const stackedData = trends?.months.map((m) => {
    const point: Record<string, string | number> = { month_label: m.month_label };
    for (const lt of trends.leave_types) {
      point[lt.code] = Math.round((m.by_type[lt.code] || 0) * 10) / 10;
    }
    return point;
  }) ?? [];

  // KPIs
  const totalDays = trends?.months.reduce((s, m) => s + m.total_days, 0) ?? 0;
  const totalApps = trends?.months.reduce((s, m) => s + m.application_count, 0) ?? 0;
  const avgMonthly = totalDays > 0 ? Math.round((totalDays / 12) * 10) / 10 : 0;

  // Per-type year totals for horizontal bar
  const typeYearTotals = trends?.leave_types.map((lt) => ({
    name: lt.name,
    code: lt.code,
    days: Math.round((trends.months.reduce((s, m) => s + (m.by_type[lt.code] || 0), 0)) * 10) / 10,
  })).sort((a, b) => b.days - a.days) ?? [];

  const maxTypeDays = typeYearTotals.length > 0 ? typeYearTotals[0].days : 1;

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
          <p className="text-sm text-gray-500">Total Leave Days</p>
          <p className="mt-1 text-2xl font-bold text-gray-900">{totalDays.toLocaleString()}</p>
        </div>
        <div className="bg-white border border-gray-200 rounded-xl p-5">
          <p className="text-sm text-gray-500">Total Applications</p>
          <p className="mt-1 text-2xl font-bold text-gray-900">{totalApps.toLocaleString()}</p>
        </div>
        <div className="bg-white border border-gray-200 rounded-xl p-5">
          <p className="text-sm text-gray-500">Leave Types</p>
          <p className="mt-1 text-2xl font-bold text-gray-900">{trends?.leave_types.length ?? 0}</p>
        </div>
        <div className="bg-white border border-gray-200 rounded-xl p-5">
          <p className="text-sm text-gray-500">Avg Monthly Days</p>
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
      ) : (
        <>
          {/* Year totals by type - horizontal bar */}
          {typeYearTotals.length > 0 && (
            <div className="bg-white border border-gray-200 rounded-xl shadow-sm p-6">
              <h3 className="text-sm font-semibold text-gray-900 mb-4">Leave Days by Type ({year} Total)</h3>
              <div className="space-y-3">
                {typeYearTotals.map((t, idx) => (
                  <div key={t.code}>
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-sm text-gray-700">{t.name}</span>
                      <span className="text-sm font-medium text-gray-900">{t.days} days</span>
                    </div>
                    <div className="h-2.5 bg-gray-100 rounded-full overflow-hidden">
                      <div
                        className="h-full rounded-full transition-all"
                        style={{
                          width: `${maxTypeDays > 0 ? (t.days / maxTypeDays) * 100 : 0}%`,
                          backgroundColor: getColor(idx),
                        }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Stacked bar chart: days per type per month */}
          <div className="bg-white border border-gray-200 rounded-xl shadow-sm p-6">
            <h3 className="text-sm font-semibold text-gray-900 mb-4">Leave Days by Type (Monthly)</h3>
            {trends && trends.leave_types.length > 0 ? (
              <ResponsiveContainer width="100%" height={350}>
                <BarChart data={stackedData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                  <XAxis dataKey="month_label" tick={{ fontSize: 12 }} />
                  <YAxis tick={{ fontSize: 12 }} label={{ value: 'Days', angle: -90, position: 'insideLeft', style: { fontSize: 12 } }} />
                  <Tooltip />
                  <Legend />
                  {trends.leave_types.map((lt, idx) => (
                    <Bar key={lt.code} dataKey={lt.code} name={lt.name} stackId="leave" fill={getColor(idx)} />
                  ))}
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="text-center py-12 text-gray-400">
                <p className="text-sm">No leave types configured yet.</p>
                <p className="text-xs mt-1">Create leave types in Policies to see data here.</p>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
