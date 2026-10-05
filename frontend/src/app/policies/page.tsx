'use client'

import { useState } from 'react'
import DashboardLayout from '@/components/layout/DashboardLayout'
import { usePermissions } from '@/contexts/PermissionsContext'
import HolidaysTab from '@/app/policies/HolidaysTab'
import ShiftStatusTypesTab from '@/app/policies/ShiftStatusTypesTab'
import LeavePoliciesV2 from '@/app/policies/leave/LeavePoliciesV2'
import ChainTester from '@/app/policies/leave/ChainTester'
import WorkSitesTab from '@/app/policies/WorkSitesTab'
import ApprovalRulesTab from '@/app/settings/ApprovalRulesTab'
import OvertimeTab from '@/app/settings/OvertimeTab'
import PolicyRulesTab from '@/app/settings/PolicyRulesTab'
import ScheduleFormatsTab from '@/app/settings/ScheduleFormatsTab'

type Check = (module: string, action: string) => boolean

// Each tab shows when the caller can at least READ what its API serves, and
// each tab's own buttons follow the matching create/edit/delete permission.
// The page used to be hard-coded to admin and HR: it hid the tabs from roles
// the Permissions screen allowed, and showed HR tabs whose saves all 403.
//
// Policies are configuration, so every tab opens in an admin session too. An
// admin session has settings (all) and leave edit/delete (leave
// CONFIGURATION) but no schedules and no leave view (reviewing other people's
// leave is not administration), so the leave tabs also open on leave:edit.
const TABS: { key: string; label: string; visible: (can: Check) => boolean }[] = [
  { key: 'holidays', label: 'Holidays', visible: (can) => can('schedules', 'view') || can('settings', 'view') },
  // The list is readable by every signed-in user (the grid draws with it), so
  // it shows beside Holidays to anyone who works with the schedule or company
  // settings; the tab's own add/edit/delete follow the API's tenant_admin gate.
  { key: 'status-types', label: 'Shift Status Types', visible: (can) => can('schedules', 'view') || can('settings', 'view') },
  { key: 'leave', label: 'Leave Policies', visible: (can) => can('leave', 'view') || can('leave', 'edit') },
  { key: 'approval-rules', label: 'Approval Rules', visible: (can) => can('leave', 'view') || can('leave', 'edit') },
  { key: 'overtime', label: 'Overtime', visible: (can) => can('leave', 'view') || can('leave', 'edit') || can('settings', 'view') },
  { key: 'policy-rules', label: 'Policy Rules', visible: (can) => can('settings', 'view') },
  { key: 'schedule-formats', label: 'Schedule Formats', visible: (can) => can('settings', 'view') },
  { key: 'work-sites', label: 'Work Sites', visible: (can) => can('settings', 'view') },
]

export default function PoliciesPage() {
  const { hasPermission, isLoading } = usePermissions()
  const visible = TABS.filter((t) => t.visible(hasPermission))
  const [chosen, setChosen] = useState<string | null>(null)
  const activeTab = visible.find((t) => t.key === chosen)?.key ?? visible[0]?.key

  if (isLoading) {
    return (
      <DashboardLayout>
        <div className="py-12 text-center text-sm text-gray-500">Loading…</div>
      </DashboardLayout>
    )
  }

  if (!visible.length) {
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
              Your role cannot see any company policies. Ask an administrator to grant it on the Permissions screen.
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
            Configure holidays, shift status types, leave, overtime, schedule formats, work sites and automation rules for your organization.
          </p>
        </div>

        <div className="overflow-x-auto">
          <nav className="flex space-x-8 w-max min-w-full shadow-[inset_0_-1px_0_0_#e5e7eb]" role="tablist">
            {visible.map((tab) => (
              <button
                key={tab.key}
                role="tab"
                aria-selected={activeTab === tab.key}
                onClick={() => setChosen(tab.key)}
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
        {activeTab === 'status-types' && <ShiftStatusTypesTab />}
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
        {activeTab === 'work-sites' && <WorkSitesTab />}
      </div>
    </DashboardLayout>
  )
}
