'use client'

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { TimePunch } from '@/types'
import { UserPicker } from '@/components/ui'

// Who clocked in and out, where, and how far from the site they were expected
// at. The time clock recorded all of this, but there was no screen to see it,
// so an "outside the geofence" or an automatically closed punch was never
// reviewed by anyone.

const LOCATION_LABEL: Record<string, string> = {
  captured: 'Captured',
  recaptured: 'Added later',
  denied: 'Refused by the browser',
  unavailable: 'Unavailable',
  timeout: 'Timed out',
  insecure_context: 'Not on HTTPS',
  not_required: 'Not asked',
}

function isoDaysAgo(days: number): string {
  const d = new Date()
  d.setDate(d.getDate() - days)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

function GeofenceCell({ p }: { p: TimePunch }) {
  const where = p.work_site_name ? ` ${p.work_site_name}` : ''
  const dist = p.distance_m != null ? `${Math.round(p.distance_m)} m from${where || ' the site'}` : null
  if (p.geofence_status === 'inside') {
    return <span className="text-green-800">At{where || ' site'}{p.distance_m != null ? ` (${Math.round(p.distance_m)} m)` : ''}</span>
  }
  if (p.geofence_status === 'outside') {
    return <span className="font-medium text-red-700">Outside: {dist ?? 'away from the site'}</span>
  }
  if (p.geofence_status === 'unverified') {
    return <span className="text-amber-800">Expected on site, no location to check</span>
  }
  return <span className="text-gray-500">No site expected</span>
}

export default function PunchesTab() {
  const [start, setStart] = useState(isoDaysAgo(6))
  const [end, setEnd] = useState(isoDaysAgo(0))
  const [employeeId, setEmployeeId] = useState<number | null>(null)
  const [flaggedOnly, setFlaggedOnly] = useState(false)

  const { data: punches, isLoading, error } = useQuery<TimePunch[]>({
    queryKey: ['punches', start, end, employeeId, flaggedOnly],
    queryFn: () =>
      api.listPunches({
        start_date: start || undefined,
        end_date: end || undefined,
        employee_id: employeeId ?? undefined,
        flagged_only: flaggedOnly || undefined,
      }),
  })

  return (
    <div className="bg-white shadow-sm ring-1 ring-gray-900/5 rounded-xl">
      <div className="border-b border-gray-200 px-6 py-4">
        <h2 className="text-lg font-semibold text-gray-900">Time clock punches</h2>
        <p className="mt-1 text-sm text-gray-500">
          Every clock-in and clock-out, with where it was made. Flagged punches need a look: no location,
          outside the expected site, a device clock far from the server&apos;s, or closed automatically because
          nobody clocked out.
        </p>
      </div>

      <div className="flex flex-wrap items-end gap-4 border-b border-gray-100 px-6 py-4">
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-gray-500">From</span>
          <input type="date" className="input" value={start} onChange={(e) => setStart(e.target.value)} />
        </label>
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-gray-500">To</span>
          <input type="date" className="input" value={end} onChange={(e) => setEnd(e.target.value)} />
        </label>
        <div className="w-72">
          <UserPicker label="Employee" value={employeeId} onChange={(id) => setEmployeeId(id)} placeholder="Everyone" />
        </div>
        <label className="flex items-center gap-2 pb-2 text-sm text-gray-700">
          <input type="checkbox" checked={flaggedOnly} onChange={(e) => setFlaggedOnly(e.target.checked)} />
          Flagged only
        </label>
      </div>

      <div className="px-6 py-6">
        {isLoading ? (
          <p className="text-sm text-gray-500">Loading…</p>
        ) : error ? (
          <p className="text-sm text-red-700">Could not load punches: {(error as Error).message}</p>
        ) : !punches?.length ? (
          <p className="py-8 text-center text-sm text-gray-500">No punches in this range.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200 text-sm">
              <thead className="text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
                <tr>
                  <th className="px-3 py-2">Employee</th>
                  <th className="px-3 py-2">Day</th>
                  <th className="px-3 py-2">Punch</th>
                  <th className="px-3 py-2">Time</th>
                  <th className="px-3 py-2">Location</th>
                  <th className="px-3 py-2">Site</th>
                  <th className="px-3 py-2">Flags</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {punches.map((p) => {
                  const skew = p.clock_skew_seconds ?? 0
                  return (
                    <tr key={p.id} className={p.geofence_status === 'outside' || p.auto_closed ? 'bg-amber-50/40' : ''}>
                      <td className="px-3 py-2 text-gray-900">{p.employee_name || `#${p.employee_id}`}</td>
                      <td className="px-3 py-2 text-gray-700">{p.business_date}</td>
                      <td className="px-3 py-2 text-gray-700">{p.punch_type === 'in' ? 'Clock in' : 'Clock out'}</td>
                      <td className="px-3 py-2 text-gray-700">{p.local_time.slice(0, 5)}</td>
                      <td className="px-3 py-2 text-gray-700">
                        {LOCATION_LABEL[p.location_status] ?? p.location_status}
                        {p.latitude != null && p.longitude != null && (
                          <a
                            className="ml-2 text-brand-700 underline"
                            href={`https://www.openstreetmap.org/?mlat=${p.latitude}&mlon=${p.longitude}#map=17/${p.latitude}/${p.longitude}`}
                            target="_blank"
                            rel="noreferrer noopener"
                          >
                            map
                          </a>
                        )}
                        {p.accuracy_m != null && <span className="block text-xs text-gray-500">within {Math.round(p.accuracy_m)} m</span>}
                      </td>
                      <td className="px-3 py-2"><GeofenceCell p={p} /></td>
                      <td className="px-3 py-2">
                        <div className="flex flex-wrap gap-1">
                          {p.auto_closed && (
                            <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[11px] font-medium text-amber-900" title={p.notes ?? undefined}>
                              Closed automatically
                            </span>
                          )}
                          {Math.abs(skew) > 300 && (
                            <span className="rounded bg-red-100 px-1.5 py-0.5 text-[11px] font-medium text-red-800">
                              Device clock {Math.round(Math.abs(skew) / 60)} min {skew > 0 ? 'ahead' : 'behind'}
                            </span>
                          )}
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
