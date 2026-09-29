'use client'

import DashboardLayout from '@/components/layout/DashboardLayout'
import SalaryAccessTab from '@/app/finances/SalaryAccessTab'

// Salary access used to be a Finances tab. It is not finance work: the people
// who approve it are often administrators, and an administrator never opens
// Finances (administration is not operations). So it has its own screen, in
// the admin dashboard (approvals and the grant history) and in the finance
// dashboard (the person's own request, and the approvals when they approve).
// The screens themselves are the same component the tab used.
export default function SalaryAccessPage() {
  return (
    <DashboardLayout>
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Salary access</h1>
          <p className="mt-1 text-sm text-gray-500">
            Who may see salary figures, who approves it, and every grant, decline and revoke.
          </p>
        </div>
        <SalaryAccessTab />
      </div>
    </DashboardLayout>
  )
}
