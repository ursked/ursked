'use client'

import { useState } from 'react'
import DashboardLayout from '@/components/layout/DashboardLayout'
import { useAuth } from '@/contexts/AuthContext'
import { hasAnyRole } from '@/lib/roles'
import SalaryGradesTab from './SalaryGradesTab'
import EmployeeSalariesTab from './EmployeeSalariesTab'
import DeductionsTab from './DeductionsTab'
import CompensationTab from './CompensationTab'
import PayoutScheduleTab from './PayoutScheduleTab'
import PayrollTab from './PayrollTab'
import SalaryAccessTab from './SalaryAccessTab'

const TABS = [
  { key: 'salary-grades', label: 'Salary Grades' },
  { key: 'employee-salaries', label: 'Employee Salaries' },
  { key: 'compensation', label: 'Bonuses & Allowances' },
  { key: 'deductions', label: 'Deductions' },
  { key: 'payout-schedule', label: 'Payout Schedule' },
  { key: 'payroll', label: 'Payroll' },
  { key: 'salary-access', label: 'Salary Access' },
] as const

type TabKey = (typeof TABS)[number]['key']

export default function FinancesPage() {
  const { user } = useAuth()
  const [activeTab, setActiveTab] = useState<TabKey>('payroll')

  const hasAccess = user && hasAnyRole(user, ['tenant_admin', 'finance'])

  if (!hasAccess) {
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
              You do not have permission to view this page. Only administrators and finance users can access finances.
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
          <h1 className="text-2xl font-bold text-gray-900">Finances</h1>
          <p className="mt-1 text-sm text-gray-500">
            Manage salary grades, deductions, and payroll processing.
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

        {activeTab === 'salary-grades' && <SalaryGradesTab />}
        {activeTab === 'employee-salaries' && <EmployeeSalariesTab />}
        {activeTab === 'compensation' && <CompensationTab />}
        {activeTab === 'deductions' && <DeductionsTab />}
        {activeTab === 'payout-schedule' && <PayoutScheduleTab />}
        {activeTab === 'payroll' && <PayrollTab />}
        {activeTab === 'salary-access' && <SalaryAccessTab />}
      </div>
    </DashboardLayout>
  )
}
