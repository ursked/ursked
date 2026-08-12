'use client';

import React from 'react';
import { ScheduleStats } from '@/types';

interface StatsBarProps {
  stats: ScheduleStats;
  loading?: boolean;
}

export default function StatsBar({ stats, loading }: StatsBarProps) {
  const items = [
    {
      label: 'Employees',
      value: stats.total_employees,
      icon: (
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" />
        </svg>
      ),
      color: 'text-blue-600 bg-blue-50',
    },
    {
      label: 'Total Shifts',
      value: stats.total_shifts,
      icon: (
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
        </svg>
      ),
      color: 'text-purple-600 bg-purple-50',
    },
    {
      label: 'Scheduled',
      value: stats.scheduled_count,
      icon: (
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
      ),
      color: 'text-green-600 bg-green-50',
    },
    {
      label: 'On Leave',
      value: stats.leave_count,
      icon: (
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
        </svg>
      ),
      color: 'text-amber-600 bg-amber-50',
    },
    {
      label: 'Rest Days',
      value: stats.rest_day_count,
      icon: (
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
        </svg>
      ),
      color: 'text-gray-600 bg-gray-100',
    },
  ];

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
      {items.map((item) => (
        <div key={item.label} className="bg-white rounded-xl border border-gray-200 px-4 py-3 flex items-center gap-3">
          <div className={`p-2 rounded-lg ${item.color}`}>
            {item.icon}
          </div>
          <div>
            <p className="text-xs text-gray-500">{item.label}</p>
            <p className="text-lg font-semibold text-gray-900">
              {loading ? (
                <span className="inline-block w-8 h-5 bg-gray-200 rounded animate-pulse" />
              ) : (
                item.value
              )}
            </p>
          </div>
        </div>
      ))}
    </div>
  );
}
