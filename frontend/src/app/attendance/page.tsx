'use client'

import { useState } from 'react'
import DashboardLayout from '@/components/layout/DashboardLayout'
import { usePermissions } from '@/contexts/PermissionsContext'
import AttendanceTab from './AttendanceTab'
import OvertimeTab from './OvertimeTab'
import TardinessTab from './TardinessTab'

const TABS = [
  { key: 'attendance', label: 'Attendance' },
  { key: 'overtime', label: 'Overtime' },
  { key: 'tardiness', label: 'Tardiness' },
] as const

type TabKey = (typeof TABS)[number]['key']

export default function AttendancePage() {
  const { hasPermission, isLoading } = usePermissions()
  const [activeTab, setActiveTab] = useState<TabKey>('attendance')

  if (isLoading) {
    return (
      <DashboardLayout>
        <div className="flex items-center justify-center min-h-[60vh]">
          <svg className="h-8 w-8 animate-spin text-purple-600" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
        </div>
      </DashboardLayout>
    )
  }

  if (!hasPermission('schedules', 'view')) {
    return (
      <DashboardLayout>
        <div className="flex items-center justify-center min-h-[60vh]">
          <div className="text-center">
            <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-red-100">
              <svg className="h-6 w-6 text-red-600" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636" />
              </svg>
            </div>
            <h3 className="mt-4 text-lg font-semibold text-gray-900">Access Denied</h3>
            <p className="mt-2 text-sm text-gray-500">
              You do not have permission to view attendance records.
            </p>
          </div>
        </div>
      </DashboardLayout>
    )
  }

  return (
    <DashboardLayout>
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Attendance</h1>
          <p className="mt-1 text-sm text-gray-500">
            Record and manage employee attendance, overtime, and tardiness.
          </p>
        </div>

        <div className="border-b border-gray-200">
          <nav className="-mb-px flex space-x-8">
            {TABS.map((tab) => (
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

        {activeTab === 'attendance' && <AttendanceTab />}
        {activeTab === 'overtime' && <OvertimeTab />}
        {activeTab === 'tardiness' && <TardinessTab />}
      </div>
    </DashboardLayout>
  )
}
