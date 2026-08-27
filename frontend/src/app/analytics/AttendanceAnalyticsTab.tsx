'use client';

import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import {
  BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer,
} from 'recharts';
import type { AttendanceSummaryResponse } from '@/types';

interface Props {
  year: number;
  startDate?: string;
  endDate?: string;
}

export default function AttendanceAnalyticsTab({ year, startDate, endDate }: Props) {
  const { data: summary, isLoading, isError, refetch } = useQuery<AttendanceSummaryResponse>({
    queryKey: ['analytics', 'attendance', 'summary', year, startDate, endDate],
    queryFn: () => api.getAttendanceSummary({
      year,
      start_date: startDate || undefined,
      end_date: endDate || undefined,
    }),
  });

  // Transform for stacked bar: present / late / absent per month
  const statusData = summary?.months.map((m) => ({
    month_label: m.month_label,
    Present: m.present_count,
    Late: m.late_count,
    Absent: m.absent_count,
  })) ?? [];

  // Transform for line chart: avg hours per month
  const hoursData = summary?.months.map((m) => ({
    month_label: m.month_label,
    'Avg Hours': m.avg_hours_worked,
  })) ?? [];

  // KPIs
  const totalRecords = summary?.months.reduce((s, m) => s + m.total_records, 0) ?? 0;
  const totalLate = summary?.months.reduce((s, m) => s + m.late_count, 0) ?? 0;
  const totalAbsent = summary?.months.reduce((s, m) => s + m.absent_count, 0) ?? 0;
  const totalTardiness = summary?.months.reduce((s, m) => s + m.total_tardiness_minutes, 0) ?? 0;
  const avgHours = totalRecords > 0
    ? Math.round((summary?.months.reduce((s, m) => s + m.avg_hours_worked * m.total_records, 0) ?? 0) / totalRecords * 10) / 10
    : 0;

  return (
    <div className="space-y-6">
      {/* KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
        <div className="bg-white border border-gray-200 rounded-xl p-5">
          <p className="text-sm text-gray-500">Total Records</p>
          <p className="mt-1 text-2xl font-bold text-gray-900">{totalRecords.toLocaleString()}</p>
        </div>
        <div className="bg-white border border-gray-200 rounded-xl p-5">
          <p className="text-sm text-gray-500">Avg Hours/Day</p>
          <p className="mt-1 text-2xl font-bold text-gray-900">{avgHours}</p>
        </div>
        <div className="bg-white border border-gray-200 rounded-xl p-5">
          <p className="text-sm text-gray-500">Total Late</p>
          <p className="mt-1 text-2xl font-bold text-orange-600">{totalLate.toLocaleString()}</p>
        </div>
        <div className="bg-white border border-gray-200 rounded-xl p-5">
          <p className="text-sm text-gray-500">Total Absent</p>
          <p className="mt-1 text-2xl font-bold text-red-600">{totalAbsent.toLocaleString()}</p>
        </div>
        <div className="bg-white border border-gray-200 rounded-xl p-5">
          <p className="text-sm text-gray-500">Total Tardiness</p>
          <p className="mt-1 text-2xl font-bold text-gray-900">{Math.round(totalTardiness / 60)}h {totalTardiness % 60}m</p>
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
          <p className="text-sm font-medium text-red-800">Could not load attendance analytics.</p>
          <p className="mt-1 text-xs text-red-700">The server did not return data for this period.</p>
          <button
            type="button"
            onClick={() => refetch()}
            className="mt-4 rounded-md bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-700"
          >
            Retry
          </button>
        </div>
      ) : (
        <>
          {/* Stacked bar: Present / Late / Absent */}
          <div className="bg-white border border-gray-200 rounded-xl shadow-sm p-6">
            <h3 className="text-sm font-semibold text-gray-900 mb-4">Attendance Status Breakdown (Monthly)</h3>
            <ResponsiveContainer width="100%" height={350}>
              <BarChart data={statusData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis dataKey="month_label" tick={{ fontSize: 12 }} />
                <YAxis tick={{ fontSize: 12 }} label={{ value: 'Records', angle: -90, position: 'insideLeft', style: { fontSize: 12 } }} />
                <Tooltip />
                <Legend />
                <Bar dataKey="Present" stackId="status" fill="#10b981" />
                <Bar dataKey="Late" stackId="status" fill="#f59e0b" />
                <Bar dataKey="Absent" stackId="status" fill="#ef4444" />
              </BarChart>
            </ResponsiveContainer>
          </div>

          {/* Line chart: avg hours per month */}
          <div className="bg-white border border-gray-200 rounded-xl shadow-sm p-6">
            <h3 className="text-sm font-semibold text-gray-900 mb-4">Average Hours Worked (Monthly Trend)</h3>
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={hoursData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis dataKey="month_label" tick={{ fontSize: 12 }} />
                <YAxis tick={{ fontSize: 12 }} domain={[0, 'auto']} label={{ value: 'Hours', angle: -90, position: 'insideLeft', style: { fontSize: 12 } }} />
                <Tooltip />
                <Legend />
                <Line type="monotone" dataKey="Avg Hours" stroke="#8b5cf6" strokeWidth={2} dot={{ fill: '#8b5cf6', r: 4 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </>
      )}
    </div>
  );
}
