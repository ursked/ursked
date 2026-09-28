'use client'

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ArrowRight, User as UserIcon } from 'lucide-react'
import { api } from '@/lib/api'
import { Card, CardBody, CardHeader, CardTitle, Badge, EmptyState, UserPicker } from '@/components/ui'
import { CHAIN_SOURCE_LABEL } from '@/lib/copy/policies'

export default function ChainTester() {
  const [employeeId, setEmployeeId] = useState<number | null>(null)

  // The same resolver filing uses, so what this shows is what would happen.
  const { data: preview, isFetching, error } = useQuery({
    queryKey: ['approval-chain-preview', employeeId],
    queryFn: () => api.previewApprovalChain(employeeId as number),
    enabled: employeeId !== null,
  })

  return (
    <Card>
      <CardHeader>
        <CardTitle>Test an approval chain</CardTitle>
        <p className="mt-1 text-sm text-gray-500">
          Pick an employee to see exactly who would approve their leave request if they filed it now, and why.
        </p>
      </CardHeader>
      <CardBody className="space-y-4">
        <div className="max-w-sm">
          <UserPicker label="Employee" value={employeeId} onChange={(id) => setEmployeeId(id)} />
        </div>

        {employeeId === null ? null : isFetching ? (
          <div className="text-sm text-gray-400">Resolving…</div>
        ) : error ? (
          <p className="text-sm text-red-700">{(error as Error).message}</p>
        ) : !preview || preview.chain.length === 0 ? (
          <EmptyState icon={UserIcon} title="No approval chain" description="Could not work out an approver." />
        ) : (
          <div className="flex flex-wrap items-center gap-2">
            {preview.chain.map((step, i) => (
              <div key={`${step.approver_id}-${i}`} className="flex items-center gap-2">
                <div className="rounded-lg border border-gray-200 bg-white px-3 py-2">
                  <div className="text-sm font-medium text-gray-900">
                    {step.step_order}. {step.approver_name}
                  </div>
                  <Badge tone={step.source === 'self_approval' ? 'yellow' : 'gray'} className="mt-1">
                    {CHAIN_SOURCE_LABEL[step.source] ?? step.source}
                  </Badge>
                </div>
                {i < preview.chain.length - 1 && <ArrowRight className="h-4 w-4 text-gray-400" aria-hidden />}
              </div>
            ))}
          </div>
        )}
      </CardBody>
    </Card>
  )
}
