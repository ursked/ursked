'use client'

import { useState } from 'react'
import DashboardLayout from '@/components/layout/DashboardLayout'
import { useAuth } from '@/contexts/AuthContext'
import { hasAnyRole } from '@/lib/roles'
import HolidaysTab from '@/app/policies/HolidaysTab'
import LeavePoliciesV2 from '@/app/policies/leave/LeavePoliciesV2'
import ChainTester from '@/app/policies/leave/ChainTester'
import ApprovalRulesTab from '@/app/settings/ApprovalRulesTab'
import OvertimeTab from '@/app/settings/OvertimeTab'
import PolicyRulesTab from '@/app/settings/PolicyRulesTab'
import ScheduleFormatsTab from '@/app/settings/ScheduleFormatsTab'

const TABS = [
  { key: 'holidays', label: 'Holidays' },
  { key: 'leave', label: 'Leave Policies' },
  { key: 'approval-rules', label: 'Approval Rules' },
  { key: 'overtime', label: 'Overtime' },
  { key: 'policy-rules', label: 'Policy Rules' },
  { key: 'schedule-formats', label: 'Schedule Formats' },
] as const

type TabKey = (typeof TABS)[number]['key']

export default function PoliciesPage() {
  const { user } = useAuth()
  const [activeTab, setActiveTab] = useState<TabKey>('holidays')

  const isAdmin = user && hasAnyRole(user, ['tenant_admin', 'hr'])

  if (!isAdmin) {
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
              You do not have permission to view this page. Only tenant administrators and HR can access policies.
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
          <h1 className="text-2xl font-bold text-gray-900">Policies</h1>
          <p className="mt-1 text-sm text-gray-500">
            Configure holidays, leave, overtime, schedule formats, and automation rules for your organization.
          </p>
        </div>

        <div className="border-b border-gray-200 overflow-x-auto">
          <nav className="-mb-px flex space-x-8 min-w-max">
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

        {activeTab === 'holidays' && <HolidaysTab />}
        {activeTab === 'leave' && <LeavePoliciesV2 />}
        {activeTab === 'approval-rules' && (
          <div className="space-y-6">
            <ChainTester />
            <ApprovalRulesTab />
          </div>
        )}
        {activeTab === 'overtime' && <OvertimeTab />}
        {activeTab === 'policy-rules' && <PolicyRulesTab />}
        {activeTab === 'schedule-formats' && <ScheduleFormatsTab />}
      </div>
    </DashboardLayout>
  )
}
