'use client'

import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { MapPin, AlertTriangle, Clock, ShieldCheck, ShieldAlert } from 'lucide-react'
import DashboardLayout from '@/components/layout/DashboardLayout'
import { api } from '@/lib/api'
import { captureLocation, canCaptureLocation, geoFailureMessage } from '@/lib/geolocation'
import type { TimeclockToday, TimePunch } from '@/types'
import { useToast } from '@/components/ui/Toast'
import { Button, Card, CardBody, Badge, EmptyState } from '@/components/ui'

const ARRANGEMENT_LABEL: Record<string, string> = {
  onsite: 'On-site',
  wfh: 'Work From Home',
  hybrid: 'Hybrid',
  ob: 'Official Business',
}

function hhmm(t?: string | null) {
  return t ? t.slice(0, 5) : '--:--'
}

/** Minutes left before a punch can no longer be given a location. */
function graceRemaining(punch: TimePunch, now: number): number | null {
  if (!punch.recapture_deadline || punch.latitude != null) return null
  const left = new Date(punch.recapture_deadline).getTime() - now
  return left > 0 ? Math.ceil(left / 60000) : null
}

function LocationBadge({ punch }: { punch: TimePunch }) {
  const s = punch.location_status
  if (s === 'captured') {
    return <Badge tone="green">Location captured</Badge>
  }
  if (s === 'recaptured') {
    // Never shown as an ordinary tick. A location supplied after the fact is
    // weaker evidence than one given at the moment of the punch, and a reviewer
    // has to be able to tell them apart.
    return <Badge tone="yellow">Location added later</Badge>
  }
  if (s === 'not_required') return null
  return <Badge tone="gray">No location</Badge>
}

function GeofenceBadge({ punch }: { punch: TimePunch }) {
  if (punch.geofence_status === 'inside') {
    return (
      <Badge tone="green">
        <ShieldCheck className="w-3 h-3 mr-1 inline" />
        At site{punch.distance_m != null ? ` (${Math.round(punch.distance_m)}m)` : ''}
      </Badge>
    )
  }
  if (punch.geofence_status === 'outside') {
    return (
      <Badge tone="red">
        <ShieldAlert className="w-3 h-3 mr-1 inline" />
        {punch.distance_m != null ? `${Math.round(punch.distance_m)}m from site` : 'Away from site'}
      </Badge>
    )
  }
  return null
}

export default function TimeclockPage() {
  const qc = useQueryClient()
  const { showToast } = useToast()
  const [now, setNow] = useState(() => Date.now())
  const [busy, setBusy] = useState(false)

  // Drives the grace countdown.
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 30_000)
    return () => clearInterval(t)
  }, [])

  const { data, isLoading } = useQuery<TimeclockToday>({
    queryKey: ['timeclock-today'],
    queryFn: () => api.getMyTimeclockToday(),
    // The app registers a service worker, and a cached shell showing "Clock in"
    // when you are already clocked in would be actively misleading.
    staleTime: 0,
    refetchOnWindowFocus: true,
    refetchInterval: 60_000,
  })

  const punchMut = useMutation({
    mutationFn: async (type: 'in' | 'out') => {
      // Never block the punch on the sensor: capture is attempted, and whatever
      // comes back (including a refusal) travels with the punch.
      const geo = await captureLocation()
      return api.punchClock({
        punch_type: type,
        client_time: new Date().toISOString(),
        ...(geo.ok
          ? { latitude: geo.latitude, longitude: geo.longitude, accuracy_m: geo.accuracy_m }
          : { location_error: geo.reason }),
      })
    },
    onSuccess: (punch) => {
      qc.invalidateQueries({ queryKey: ['timeclock-today'] })
      const verb = punch.punch_type === 'in' ? 'Clocked in' : 'Clocked out'
      showToast(`${verb} at ${hhmm(punch.local_time)}`, 'success')
      if (punch.location_status !== 'captured' && punch.location_status !== 'not_required') {
        showToast(geoFailureMessage(punch.location_status as never), 'info')
      }
    },
    onError: (e: unknown) => {
      const msg = e instanceof Error ? e.message : 'Could not record that punch.'
      showToast(msg, 'error')
      // A 409 means our idea of the state is stale; refetch rather than argue.
      qc.invalidateQueries({ queryKey: ['timeclock-today'] })
    },
    onSettled: () => setBusy(false),
  })

  const recaptureMut = useMutation({
    mutationFn: async (punchId: number) => {
      const geo = await captureLocation()
      if (!geo.ok) throw new Error(geoFailureMessage(geo.reason))
      return api.attachPunchLocation(punchId, {
        latitude: geo.latitude,
        longitude: geo.longitude,
        accuracy_m: geo.accuracy_m,
      })
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['timeclock-today'] })
      showToast('Location added to your punch.', 'success')
    },
    onError: (e: unknown) => {
      showToast(e instanceof Error ? e.message : 'Could not add a location.', 'error')
    },
  })

  const insecure = typeof window !== 'undefined' && !canCaptureLocation()

  if (isLoading) {
    return (
      <DashboardLayout>
        <div className="p-4 sm:p-6 text-sm text-gray-500">Loading…</div>
      </DashboardLayout>
    )
  }

  if (!data?.timeclock_enabled) {
    return (
      <DashboardLayout>
        <div className="p-4 sm:p-6 max-w-2xl">
          <h1 className="text-2xl font-bold text-gray-900 mb-1">Time Clock</h1>
          <EmptyState
            title="The time clock is switched off"
            description="An administrator can enable it under Settings → General → Time Clock."
          />
        </div>
      </DashboardLayout>
    )
  }

  const nextIn = data.next_action === 'clock_in'
  const pending = data.punches.filter((p) => graceRemaining(p, now) !== null)

  return (
    <DashboardLayout>
      <div className="p-4 sm:p-6 max-w-2xl space-y-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Time Clock</h1>
          <p className="text-sm text-gray-500">
            {new Date(data.business_date + 'T00:00:00').toLocaleDateString(undefined, {
              weekday: 'long', day: 'numeric', month: 'long',
            })}
          </p>
        </div>

        {/* Said BEFORE anything is pressed, not after a mysterious failure. */}
        {insecure && data.require_location && (
          <div className="flex gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
            <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
            <div>
              This site is not served over HTTPS, so your browser will not share your
              location. Your time is still recorded and the punch is marked as having
              no location. Ask your administrator about enabling HTTPS.
            </div>
          </div>
        )}

        <Card>
          <CardBody className="text-center py-8">
            <div className="text-xs uppercase tracking-wide text-gray-400 mb-1">
              {nextIn ? 'Not clocked in' : 'Clocked in since'}
            </div>
            <div className="text-3xl font-semibold text-gray-900 mb-5">
              {nextIn ? '--:--' : hhmm(data.open_punch?.local_time)}
            </div>
            <Button
              size="lg"
              variant={nextIn ? 'primary' : 'danger'}
              disabled={busy || punchMut.isPending}
              onClick={() => {
                setBusy(true)
                punchMut.mutate(nextIn ? 'in' : 'out')
              }}
              className="w-full sm:w-64"
            >
              <Clock className="w-4 h-4 mr-2 inline" />
              {punchMut.isPending ? 'Recording…' : nextIn ? 'Clock In' : 'Clock Out'}
            </Button>
            {data.hours_today != null && (
              <p className="mt-3 text-xs text-gray-500">
                {data.hours_today.toFixed(2)} hours recorded today
              </p>
            )}
          </CardBody>
        </Card>

        {pending.length > 0 && (
          <Card>
            <CardBody className="space-y-2">
              <div className="text-sm font-semibold text-gray-900">Add a location</div>
              {pending.map((p) => (
                <div key={p.id} className="flex items-center justify-between gap-2 text-xs">
                  <span className="text-gray-600">
                    {p.punch_type === 'in' ? 'Clock in' : 'Clock out'} at {hhmm(p.local_time)} —{' '}
                    {graceRemaining(p, now)} min left
                  </span>
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={insecure || recaptureMut.isPending}
                    onClick={() => recaptureMut.mutate(p.id)}
                  >
                    <MapPin className="w-3 h-3 mr-1 inline" />
                    Add
                  </Button>
                </div>
              ))}
            </CardBody>
          </Card>
        )}

        {data.shifts.length > 0 && (
          <Card>
            <CardBody>
              <div className="text-sm font-semibold text-gray-900 mb-2">Today&apos;s schedule</div>
              <div className="space-y-1.5">
                {data.shifts.map((s) => (
                  <div key={s.shift_id} className="flex items-center justify-between text-xs">
                    <span className="text-gray-700">
                      {hhmm(s.start_time)} – {hhmm(s.end_time)}
                    </span>
                    <span className="flex items-center gap-2">
                      {s.work_arrangement && (
                        <Badge tone="blue">
                          {ARRANGEMENT_LABEL[s.work_arrangement] ?? s.work_arrangement}
                        </Badge>
                      )}
                      {s.geofence_mode === 'require_site' && (
                        <span className="text-gray-400">on-site expected</span>
                      )}
                    </span>
                  </div>
                ))}
              </div>
            </CardBody>
          </Card>
        )}

        <Card>
          <CardBody>
            <div className="text-sm font-semibold text-gray-900 mb-2">Today&apos;s punches</div>
            {data.punches.length === 0 ? (
              <p className="text-xs text-gray-500">Nothing recorded yet.</p>
            ) : (
              <div className="space-y-2">
                {data.punches.map((p) => (
                  <div key={p.id} className="flex flex-wrap items-center gap-2 text-xs">
                    <span className="font-medium text-gray-900 w-24">
                      {p.punch_type === 'in' ? 'Clock in' : 'Clock out'}
                    </span>
                    <span className="text-gray-600 w-14">{hhmm(p.local_time)}</span>
                    <LocationBadge punch={p} />
                    <GeofenceBadge punch={p} />
                  </div>
                ))}
              </div>
            )}
          </CardBody>
        </Card>
      </div>
    </DashboardLayout>
  )
}
