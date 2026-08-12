'use client'

import { useState } from 'react'
import DashboardLayout from '@/components/layout/DashboardLayout'
import { useAuth } from '@/contexts/AuthContext'
import { hasAnyRole } from '@/lib/roles'
import MyLeaveTab from './MyLeaveTab'
import ApprovalsTab from './ApprovalsTab'
import TeamOverviewTab from './TeamOverviewTab'

const REVIEWER_ROLES = ['tenant_admin', 'hr', 'manager', 'leave_approver'] as const
const TEAM_ROLES = ['tenant_admin', 'hr', 'manager'] as const

type TabKey = 'my-leave' | 'approvals' | 'team'

export default function LeavePage() {
  const { user } = useAuth()
  const [activeTab, setActiveTab] = useState<TabKey>('my-leave')

  const isReviewer = user && hasAnyRole(user, [...REVIEWER_ROLES])
  const isTeamViewer = user && hasAnyRole(user, [...TEAM_ROLES])

  const tabs: { key: TabKey; label: string; visible: boolean }[] = [
    { key: 'my-leave', label: 'My Leave', visible: true },
    { key: 'approvals', label: 'Approvals', visible: !!isReviewer },
    { key: 'team', label: 'Team Overview', visible: !!isTeamViewer },
  ]

  const visibleTabs = tabs.filter((t) => t.visible)

  return (
    <DashboardLayout>
      <div className="space-y-6">
        {/* Page header */}
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Leave Management</h1>
          <p className="mt-1 text-sm text-gray-500">
            Apply for leave, track your balance, and manage approvals.
          </p>
        </div>

        {/* Tab navigation */}
        <div className="border-b border-gray-200">
          <nav className="-mb-px flex space-x-8">
            {visibleTabs.map((tab) => (
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
        {activeTab === 'my-leave' && <MyLeaveTab />}
        {activeTab === 'approvals' && isReviewer && <ApprovalsTab />}
        {activeTab === 'team' && isTeamViewer && <TeamOverviewTab />}
      </div>
    </DashboardLayout>
  )
}
