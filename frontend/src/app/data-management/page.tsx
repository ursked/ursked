'use client'

import DashboardLayout from '@/components/layout/DashboardLayout'
import { usePermissions } from '@/contexts/PermissionsContext'
import ExportBuilder from './ExportBuilder'
import SchedulePanel from './SchedulePanel'

export default function DataManagementPage() {
  // The page follows the Reports row of the Permissions screen, the same check
  // the API makes: reports:create runs reports. It used to be administrators
  // only on screen while the API let HR and Finance export everything.
  const { hasPermission, isLoading } = usePermissions()
  const canRun = hasPermission('reports', 'create')

  if (isLoading) {
    return (
      <DashboardLayout>
        <div className="flex min-h-[60vh] items-center justify-center text-sm text-gray-600">Loading…</div>
      </DashboardLayout>
    )
  }

  if (!canRun) {
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
            <p className="mt-2 text-sm text-gray-600">
              Running reports is not part of your role. An administrator can allow it on the
              Permissions screen, under Reports.
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
          <h1 className="text-2xl font-bold text-gray-900">Reports</h1>
          <p className="mt-1 text-sm text-gray-600">
            Build a report by looking at your data and changing it. Everything you do shows up
            straight away, and nothing is saved until you say so.
          </p>
        </div>

        <ExportBuilder
          canSave={hasPermission('reports', 'edit')}
          canDelete={hasPermission('reports', 'delete')}
        />
        <SchedulePanel
          canEdit={hasPermission('reports', 'edit')}
          canDelete={hasPermission('reports', 'delete')}
        />
      </div>
    </DashboardLayout>
  )
}
