'use client'

import { useEffect, useState } from 'react'
import DashboardLayout from '@/components/layout/DashboardLayout'
import { useAuth } from '@/contexts/AuthContext'
import { hasAnyRole } from '@/lib/roles'
import { api } from '@/lib/api'
import GeneralSettingsTab from './GeneralSettingsTab'
import PermissionsTab from './PermissionsTab'
import ScheduleVisibilityTab from './ScheduleVisibilityTab'
import SmtpTab from './SmtpTab'

// NOTE: "Employee Types" now lives under Employees, and "Schedule Formats" under
// Policies — each next to the domain it configures. The tab components still
// reside in this folder and are imported from those pages.
type TabKey = 'general' | 'email' | 'permissions' | 'visibility'

export default function SettingsPage() {
  const { user } = useAuth()
  const [activeTab, setActiveTab] = useState<TabKey>('general')
  // The Email (self-host SMTP) tab is only meaningful on Community. On the
  // hosted SaaS, SMTP is managed by the operator console and the /smtp-settings
  // writes are refused for tenant admins, so hide the tab there.
  const [showEmailTab, setShowEmailTab] = useState(false)

  useEffect(() => {
    api.getCapabilities()
      .then((caps) => setShowEmailTab(caps.edition === 'community'))
      .catch(() => setShowEmailTab(false))
  }, [])

  const TABS = [
    { key: 'general', label: 'General' },
    ...(showEmailTab ? [{ key: 'email', label: 'Email' }] : []),
    { key: 'permissions', label: 'Permissions' },
    { key: 'visibility', label: 'Schedule Visibility' },
  ] as const

  const isAdmin = user && hasAnyRole(user, ['tenant_admin'])

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
              You do not have permission to view this page. Only tenant administrators can access settings.
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
          <h1 className="text-2xl font-bold text-gray-900">Settings</h1>
          <p className="mt-1 text-sm text-gray-500">
            Manage your organization&apos;s preferences and configuration.
          </p>
        </div>

        <div className="border-b border-gray-200">
          <nav className="-mb-px flex space-x-8">
            {TABS.map((tab) => (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab.key as TabKey)}
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

        {activeTab === 'general' && <GeneralSettingsTab />}
        {activeTab === 'email' && showEmailTab && <SmtpTab />}
        {activeTab === 'permissions' && <PermissionsTab />}
        {activeTab === 'visibility' && <ScheduleVisibilityTab />}
      </div>
    </DashboardLayout>
  )
}
