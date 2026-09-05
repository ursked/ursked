'use client'

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Receipt, Printer } from 'lucide-react'
import DashboardLayout from '@/components/layout/DashboardLayout'
import { api } from '@/lib/api'
import { useCurrency } from '@/lib/currency'
import type { MyPayslipSummary, MyPayslipDetail } from '@/types'
import {
  Button,
  Card,
  CardBody,
  Badge,
  Modal,
  EmptyState,
} from '@/components/ui'

const STATUS_TONE: Record<string, 'green' | 'yellow' | 'gray'> = {
  finalized: 'green',
  approved: 'yellow',
}

// Pull the earning/deduction/premium line arrays out of the breakdown blob.
function lines(breakdown: Record<string, unknown>, key: string): Array<Record<string, unknown>> {
  const v = breakdown?.[key]
  return Array.isArray(v) ? (v as Array<Record<string, unknown>>) : []
}

export default function MyPayslipsPage() {
  const { format: peso } = useCurrency()
  const [openId, setOpenId] = useState<number | null>(null)

  const { data: payslips, isLoading } = useQuery<MyPayslipSummary[]>({
    queryKey: ['my-payslips'],
    queryFn: () => api.getMyPayslips(),
  })

  return (
    <DashboardLayout>
      <div className="mx-auto max-w-2xl space-y-5 pb-20">
        <h1 className="text-xl font-bold text-gray-900">My Payslips</h1>

        {isLoading ? (
          <p className="text-sm text-gray-500">Loading…</p>
        ) : (payslips ?? []).length === 0 ? (
          <EmptyState
            icon={Receipt}
            title="No payslips yet"
            description="Your payslips appear here once a pay run covering you is approved."
          />
        ) : (
          <div className="space-y-2">
            {(payslips ?? []).map((p) => (
              <Card key={p.period_id}>
                <CardBody className="flex items-center justify-between p-4">
                  <button
                    className="min-w-0 text-left"
                    onClick={() => setOpenId(p.period_id)}
                  >
                    <div className="truncate text-sm font-medium text-gray-900">
                      {p.period_name}
                    </div>
                    <div className="text-xs text-gray-500">
                      {p.start_date} → {p.end_date}
                      {p.payout_date ? ` · paid ${p.payout_date}` : ''}
                    </div>
                  </button>
                  <div className="flex items-center gap-3">
                    <div className="text-right">
                      <div className="text-sm font-bold text-purple-700">
                        {peso(p.net_pay)}
                      </div>
                      <div className="text-[11px] text-gray-500">net</div>
                    </div>
                    <Badge tone={STATUS_TONE[p.status] ?? 'gray'}>{p.status}</Badge>
                  </div>
                </CardBody>
              </Card>
            ))}
          </div>
        )}
      </div>

      <PayslipModal periodId={openId} onClose={() => setOpenId(null)} />
    </DashboardLayout>
  )
}

function PayslipModal({
  periodId,
  onClose,
}: {
  periodId: number | null
  onClose: () => void
}) {
  const { format: peso } = useCurrency()
  const { data: slip, isError: slipError, isLoading: slipLoading } = useQuery<MyPayslipDetail>({
    queryKey: ['my-payslip', periodId],
    queryFn: () => api.getMyPayslip(periodId as number),
    enabled: periodId != null,
  })

  const earnings = slip ? lines(slip.breakdown, 'earnings') : []
  const overtime = slip ? lines(slip.breakdown, 'overtime') : []
  const premiums = slip ? lines(slip.breakdown, 'premiums') : []
  const deductions = slip ? lines(slip.breakdown, 'deductions') : []

  return (
    <Modal
      open={periodId != null}
      onOpenChange={(o) => !o && onClose()}
      title={slip ? slip.period_name : 'Payslip'}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Close
          </Button>
          <Button onClick={() => window.print()}>
            <Printer className="h-4 w-4" /> Print
          </Button>
        </>
      }
    >
      {slipError ? (
        /* `!slip` alone meant a failed detail fetch left the modal saying
           "Loading…" for as long as it stayed open. */
        <p className="text-sm text-red-700">Could not load this payslip. Close and try again.</p>
      ) : slipLoading || !slip ? (
        <p className="text-sm text-gray-500">Loading…</p>
      ) : (
        <div className="space-y-4 text-sm">
          <div className="rounded-lg bg-gray-50 p-3">
            <div className="font-medium text-gray-900">{slip.employee_name}</div>
            <div className="text-xs text-gray-500">
              {slip.grade_name ? `${slip.grade_name} · ` : ''}
              {slip.start_date} → {slip.end_date}
              {slip.payout_date ? ` · payout ${slip.payout_date}` : ''}
            </div>
          </div>

          <PayRow label="Base pay" value={peso(slip.base_pay)} />
          {overtime.map((o, i) => (
            <PayRow
              key={`ot-${i}`}
              label={`Overtime ${o.date ?? ''}`.trim()}
              value={peso(o.amount as number)}
              muted
            />
          ))}
          {premiums.map((pr, i) => (
            <PayRow
              key={`pr-${i}`}
              label={`${(pr.kind as string) ?? 'Premium'} ${pr.date ?? ''}`.trim()}
              value={peso(pr.amount as number)}
              muted
            />
          ))}
          {earnings.map((e, i) => (
            <PayRow
              key={`e-${i}`}
              label={(e.reason as string) || (e.kind as string) || 'Earning'}
              value={peso(e.amount as number)}
              muted
            />
          ))}

          <div className="border-t border-gray-200 pt-2">
            <PayRow label="Gross pay" value={peso(slip.gross_pay)} bold />
          </div>

          {deductions.map((d, i) => (
            <PayRow
              key={`d-${i}`}
              label={(d.name as string) || (d.code as string) || 'Deduction'}
              value={`-${peso(d.amount as number)}`}
              muted
            />
          ))}
          <PayRow label="Total deductions" value={`-${peso(slip.total_deductions)}`} />

          <div className="border-t border-gray-200 pt-2">
            <PayRow label="Net pay" value={peso(slip.net_pay)} bold />
          </div>
        </div>
      )}
    </Modal>
  )
}

function PayRow({
  label,
  value,
  bold,
  muted,
}: {
  label: string
  value: string
  bold?: boolean
  muted?: boolean
}) {
  return (
    <div className="flex items-center justify-between">
      <span className={muted ? 'text-gray-500' : 'text-gray-700'}>{label}</span>
      <span
        className={
          bold
            ? 'font-bold text-gray-900'
            : muted
              ? 'text-gray-500'
              : 'font-medium text-gray-900'
        }
      >
        {value}
      </span>
    </div>
  )
}
