'use client'

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ArrowRight, User as UserIcon } from 'lucide-react'
import { api } from '@/lib/api'
import type { User, PaginatedResponse } from '@/types'
import { Card, CardBody, CardHeader, CardTitle, Select, Badge, EmptyState } from '@/components/ui'
import { CHAIN_SOURCE_LABEL } from '@/lib/copy/policies'

export default function ChainTester() {
  const [employeeId, setEmployeeId] = useState<number | null>(null)

  const { data: users } = useQuery<PaginatedResponse<User>>({
    queryKey: ['users', 'chain-tester'],
    // Backend caps per_page at 100.
    queryFn: () => api.getUsers({ per_page: '100' }),
  })

  const { data: preview, isFetching } = useQuery({
    queryKey: ['approval-chain-preview', employeeId],
    queryFn: () => api.previewApprovalChain(employeeId as number),
    enabled: employeeId !== null,
  })

  return (
    <Card>
      <CardHeader>
        <CardTitle>Test an approval chain</CardTitle>
        <p className="mt-1 text-sm text-gray-500">
          Pick an employee to see exactly who would approve their leave request, and why.
        </p>
      </CardHeader>
      <CardBody className="space-y-4">
        <div className="max-w-sm">
          <Select
            value={employeeId ?? ''}
            onChange={(e) => setEmployeeId(e.target.value ? Number(e.target.value) : null)}
          >
            <option value="">Select an employee…</option>
            {(users?.items ?? []).map((u) => (
              <option key={u.id} value={u.id}>
                {u.first_name} {u.last_name} ({u.email})
              </option>
            ))}
          </Select>
        </div>

        {employeeId === null ? null : isFetching ? (
          <div className="text-sm text-gray-400">Resolving…</div>
        ) : !preview || preview.chain.length === 0 ? (
          <EmptyState
            icon={UserIcon}
            title="No approval chain"
            description="This employee has no policy or no resolvable approvers. Requests would broadcast to all reviewers."
          />
        ) : (
          <div className="flex flex-wrap items-center gap-2">
            {preview.chain.map((step, i) => (
              <div key={`${step.approver_id}-${i}`} className="flex items-center gap-2">
                <div className="rounded-lg border border-gray-200 bg-white px-3 py-2">
                  <div className="text-sm font-medium text-gray-900">
                    {step.approver_name}
                  </div>
                  <Badge tone="gray" className="mt-1">
                    {CHAIN_SOURCE_LABEL[step.source] ?? step.source}
                  </Badge>
                </div>
                {i < preview.chain.length - 1 && (
                  <ArrowRight className="h-4 w-4 text-gray-400" />
                )}
              </div>
            ))}
          </div>
        )}
      </CardBody>
    </Card>
  )
}
