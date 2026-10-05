'use client'

import { Suspense } from 'react'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import DashboardLayout from '@/components/layout/DashboardLayout'
import { usePermissions } from '@/contexts/PermissionsContext'
import SalaryGradesTab from './SalaryGradesTab'
import EmployeeSalariesTab from './EmployeeSalariesTab'
import DeductionsTab from './DeductionsTab'
import CompensationTab from './CompensationTab'
import PayoutScheduleTab from './PayoutScheduleTab'
import PayRulesTab from './PayRulesTab'
import PayrollTab from './PayrollTab'
import { FiguresOnly } from './financeUi'

const TABS = [
  { key: 'salary-grades', label: 'Salary Grades' },
  { key: 'employee-salaries', label: 'Employee Salaries' },
  { key: 'compensation', label: 'Bonuses & Allowances' },
  { key: 'deductions', label: 'Deductions' },
  { key: 'payout-schedule', label: 'Payout Schedule' },
  { key: 'pay-rules', label: 'Pay rules' },
  { key: 'payroll', label: 'Payroll' },
] as const

type TabKey = (typeof TABS)[number]['key']

function isTab(v: string | null): v is TabKey {
  return !!v && TABS.some((t) => t.key === v)
}

function FinancesContent() {
  const { hasPermission, isLoading } = usePermissions()
  const params = useSearchParams()
  const router = useRouter()
  const pathname = usePathname()
  // The tab lives in the URL, so a link such as /finances?tab=pay-rules opens
  // the right tab instead of always landing on Payroll. Salary access has
  // its own screen now (/salary-access); DashboardLayout forwards the old
  // /finances?tab=salary-access links there.
  const requested = params.get('tab')
  const activeTab: TabKey = isTab(requested) ? requested : 'payroll'
  const setActiveTab = (key: TabKey) => {
    const next = new URLSearchParams(params.toString())
    next.set('tab', key)
    router.replace(`${pathname}?${next.toString()}`, { scroll: false })
  }

  if (isLoading) {
    return <div className="py-12 text-center text-sm text-gray-500">Loading…</div>
  }

  // The same gate the API uses (finances:view), so a role the Permissions
  // screen grants finances to sees the page, and one it does not, does not.
  if (!hasPermission('finances', 'view')) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="text-center">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-red-100">
            <svg className="h-6 w-6 text-red-600" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636" />
            </svg>
          </div>
          <h3 className="mt-4 text-lg font-semibold text-gray-900">Access Denied</h3>
          <p className="mt-2 text-sm text-gray-500">
            Finances are managed from the finance dashboard, by people with the Finance role. If that is
            you, use the finance sign-in.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Finances</h1>
        <p className="mt-1 text-sm text-gray-500">
          Manage salary grades, deductions, and payroll processing. Salary figures are shown only
          to people another person has approved for salary access.
        </p>
      </div>

      <div className="overflow-x-auto">
        <nav className="flex space-x-8 w-max min-w-full shadow-[inset_0_-1px_0_0_#e5e7eb]" role="tablist">
          {TABS.map((tab) => (
            <button
              key={tab.key}
              role="tab"
              aria-selected={activeTab === tab.key}
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

      {/* Structure tabs (grades, deductions, payout schedule, pay rules, the
          payroll calendar) are for anyone with finances:view; the two tabs
          that are nothing but figures are for salary viewers only. */}
      {activeTab === 'salary-grades' && <SalaryGradesTab />}
      {activeTab === 'employee-salaries' && (
        <FiguresOnly what="employee salaries"><EmployeeSalariesTab /></FiguresOnly>
      )}
      {activeTab === 'compensation' && (
        <FiguresOnly what="bonuses and allowances"><CompensationTab /></FiguresOnly>
      )}
      {activeTab === 'deductions' && <DeductionsTab />}
      {activeTab === 'payout-schedule' && <PayoutScheduleTab />}
      {activeTab === 'pay-rules' && <PayRulesTab />}
      {activeTab === 'payroll' && <PayrollTab />}
    </div>
  )
}

export default function FinancesPage() {
  return (
    <DashboardLayout>
      <Suspense fallback={null}>
        <FinancesContent />
      </Suspense>
    </DashboardLayout>
  )
}
