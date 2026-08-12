'use client'

import { useMemo, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight, CalendarDays } from 'lucide-react'
import DashboardLayout from '@/components/layout/DashboardLayout'
import { useAuth } from '@/contexts/AuthContext'
import { api } from '@/lib/api'
import type { Shift, ShiftStatusType, UserPreferences } from '@/types'
import { Card, CardBody, Badge, Button, EmptyState } from '@/components/ui'
import ChangeRequestModal from '@/app/schedules/ChangeRequestModal'
import { buildStatusMaps } from '@/app/schedules/scheduleHelpers'
import { convertShiftTime, COMMON_TIMEZONES } from '@/lib/scheduleTimezone'
import { useToast } from '@/components/ui/Toast'

interface GridEmployee {
  employee_id: number
  employee_name: string
  shifts: Shift[]
}
interface GridResponse {
  employees: GridEmployee[]
  dates: string[]
  date_remarks: { date: string; title?: string; is_holiday?: boolean }[]
}

function startOfWeek(d: Date) {
  const copy = new Date(d)
  const day = (copy.getDay() + 6) % 7 // Monday = 0
  copy.setDate(copy.getDate() - day)
  copy.setHours(0, 0, 0, 0)
  return copy
}
function iso(d: Date) {
  return d.toISOString().slice(0, 10)
}
function addDays(d: Date, n: number) {
  const c = new Date(d)
  c.setDate(c.getDate() + n)
  return c
}
function startOfMonth(d: Date) {
  return new Date(d.getFullYear(), d.getMonth(), 1)
}
function endOfMonth(d: Date) {
  return new Date(d.getFullYear(), d.getMonth() + 1, 0)
}

const STATUS_TONE: Record<string, 'purple' | 'green' | 'yellow' | 'gray' | 'blue'> = {
  scheduled: 'purple',
  worked: 'green',
  absent: 'yellow',
  rest_day: 'gray',
  leave: 'blue',
}

type ViewMode = 'week' | 'month'

export default function MySchedulePage() {
  const { user } = useAuth()
  const [view, setView] = useState<ViewMode>('week')
  const [anchor, setAnchor] = useState(() => new Date())
  const [changeShift, setChangeShift] = useState<{ shift: Shift; date: string } | null>(null)

  const weekStart = startOfWeek(anchor)
  const { start, end } = useMemo(() => {
    if (view === 'month') {
      return { start: startOfMonth(anchor), end: endOfMonth(anchor) }
    }
    return { start: weekStart, end: addDays(weekStart, 6) }
  }, [view, anchor, weekStart])

  const startStr = iso(start)
  const endStr = iso(end)

  const { data, isLoading } = useQuery<GridResponse>({
    queryKey: ['my-schedule', startStr, endStr],
    queryFn: () =>
      // Employees only ever see PUBLISHED shifts (drafts stay hidden).
      api.getScheduleGrid({ start_date: startStr, end_date: endStr, published_only: 'true' }) as Promise<GridResponse>,
  })

  const { data: statusTypes } = useQuery<ShiftStatusType[]>({
    queryKey: ['status-types'],
    queryFn: () => api.getStatusTypes(),
    staleTime: 5 * 60_000,
  })
  const statusOptions = useMemo(
    () => (statusTypes ? buildStatusMaps(statusTypes).allStatuses : []),
    [statusTypes],
  )

  // Display timezone: tenant tz is the source of truth; the employee can view
  // their schedule converted to their own tz (display only).
  const { showToast } = useToast()
  const queryClient = useQueryClient()
  const { data: prefs } = useQuery<UserPreferences>({
    queryKey: ['user-preferences'],
    queryFn: () => api.getUserPreferences(),
    staleTime: 5 * 60_000,
  })
  const orgTz = prefs?.org_timezone || 'UTC'
  const myTz = (prefs?.preferences?.schedule_timezone as string) || orgTz
  const tzMut = useMutation({
    mutationFn: (tz: string) => api.updateUserPreferences({ schedule_timezone: tz }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['user-preferences'] })
      showToast('Timezone updated', 'success')
    },
    onError: (e: Error) => showToast(e.message, 'error'),
  })
  const tzDiffers = myTz !== orgTz

  /** Format a shift's time range in the viewer's tz, with a +1d marker if the
   *  local day rolls over. Falls back to the stored time when tz matches. */
  const fmtTime = (dateStr: string, s: Shift): string => {
    if (!s.start_time) return s.status
    const cs = convertShiftTime(dateStr, s.start_time, orgTz, myTz)
    const ce = s.end_time ? convertShiftTime(dateStr, s.end_time, orgTz, myTz) : null
    const startT = cs ? cs.time : s.start_time.slice(0, 5)
    const endT = ce ? ce.time : (s.end_time ? s.end_time.slice(0, 5) : '')
    const roll = cs && cs.dayShift ? (cs.dayShift > 0 ? ' (+1d)' : ' (-1d)') : ''
    return endT ? `${startT}–${endT}${roll}` : `${startT}${roll}`
  }

  const myRow = useMemo(
    () => data?.employees.find((e) => e.employee_id === user?.id) ?? data?.employees[0],
    [data, user?.id]
  )
  const holidayByDate = useMemo(() => {
    const m = new Map<string, string>()
    ;(data?.date_remarks ?? []).forEach((r) => {
      if (r.is_holiday) m.set(r.date, r.title ?? 'Holiday')
    })
    return m
  }, [data])

  const shiftsByDate = useMemo(() => {
    const m = new Map<string, Shift[]>()
    ;(myRow?.shifts ?? []).forEach((s) => {
      const arr = m.get(s.date) ?? []
      arr.push(s)
      m.set(s.date, arr)
    })
    return m
  }, [myRow])

  const todayIso = iso(new Date())

  const navigate = (dir: number) => {
    if (view === 'month') {
      setAnchor((prev) => new Date(prev.getFullYear(), prev.getMonth() + dir, 1))
    } else {
      setAnchor((prev) => addDays(prev, dir * 7))
    }
  }

  const label = view === 'month'
    ? anchor.toLocaleDateString(undefined, { month: 'long', year: 'numeric' })
    : `${weekStart.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })} – ${addDays(weekStart, 6).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}`

  return (
    <DashboardLayout>
      <div className="mx-auto max-w-2xl space-y-4 pb-20">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-bold text-gray-900">My Schedule</h1>
          {/* View toggle */}
          <div className="inline-flex rounded-lg border border-gray-200 bg-white p-0.5">
            {(['week', 'month'] as ViewMode[]).map((v) => (
              <button
                key={v}
                onClick={() => setView(v)}
                className={`rounded-md px-3 py-1 text-xs font-medium capitalize transition-colors ${
                  view === v ? 'bg-purple-600 text-white' : 'text-gray-600 hover:bg-gray-50'
                }`}
              >
                {v}
              </button>
            ))}
          </div>
        </div>

        {/* Navigator */}
        <div className="flex items-center justify-between rounded-lg border border-gray-200 bg-white px-2 py-2">
          <Button variant="ghost" size="icon" onClick={() => navigate(-1)}>
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <span className="text-sm font-medium text-gray-700">{label}</span>
          <Button variant="ghost" size="icon" onClick={() => navigate(1)}>
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>

        {/* Display timezone */}
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-gray-200 bg-white px-3 py-2">
          <label className="text-xs text-gray-500">
            Show times in
          </label>
          <div className="flex items-center gap-2">
            <select
              value={myTz}
              onChange={(e) => tzMut.mutate(e.target.value)}
              disabled={tzMut.isPending}
              className="rounded-md border border-gray-300 px-2 py-1 text-xs text-gray-700"
            >
              {/* Ensure the current + org tz are always options. */}
              {Array.from(new Set([myTz, orgTz, ...COMMON_TIMEZONES])).map((tz) => (
                <option key={tz} value={tz}>
                  {tz === orgTz ? `${tz} (organization)` : tz}
                </option>
              ))}
            </select>
          </div>
          {tzDiffers && (
            <p className="w-full text-[11px] text-amber-600">
              Times converted from the organization timezone (<span className="font-medium">{orgTz}</span>) to <span className="font-medium">{myTz}</span>.
            </p>
          )}
        </div>

        {isLoading ? (
          <div className="text-sm text-gray-400">Loading…</div>
        ) : view === 'month' ? (
          <MonthGrid anchor={anchor} shiftsByDate={shiftsByDate} holidayByDate={holidayByDate} todayIso={todayIso} fmtTime={fmtTime} />
        ) : (
          <WeekList
            weekStart={weekStart}
            shiftsByDate={shiftsByDate}
            holidayByDate={holidayByDate}
            todayIso={todayIso}
            fmtTime={fmtTime}
            onRequestChange={(shift, date) => setChangeShift({ shift, date })}
          />
        )}

        {!isLoading && (myRow?.shifts ?? []).length === 0 && (
          <EmptyState
            icon={CalendarDays}
            title={`Nothing scheduled this ${view}`}
            description="Your shifts will appear here once published."
          />
        )}
      </div>

      {changeShift && (
        <ChangeRequestModal
          isOpen
          onClose={() => setChangeShift(null)}
          shift={changeShift.shift}
          dateStr={changeShift.date}
          statusOptions={statusOptions}
          orgTz={orgTz}
          viewerTz={myTz}
        />
      )}
    </DashboardLayout>
  )
}

function WeekList({
  weekStart, shiftsByDate, holidayByDate, todayIso, fmtTime, onRequestChange,
}: {
  weekStart: Date
  shiftsByDate: Map<string, Shift[]>
  holidayByDate: Map<string, string>
  todayIso: string
  fmtTime: (dateStr: string, s: Shift) => string
  onRequestChange: (shift: Shift, date: string) => void
}) {
  const days = Array.from({ length: 7 }, (_, i) => addDays(weekStart, i))
  return (
    <div className="space-y-2">
      {days.map((d) => {
        const key = iso(d)
        const shifts = shiftsByDate.get(key) ?? []
        const holiday = holidayByDate.get(key)
        const isToday = key === todayIso
        return (
          <Card key={key} className={isToday ? 'ring-1 ring-purple-400' : ''}>
            <CardBody className="flex items-start gap-4 p-4">
              <div className="w-12 shrink-0 text-center">
                <div className="text-xs uppercase text-gray-400">
                  {d.toLocaleDateString(undefined, { weekday: 'short' })}
                </div>
                <div className={'text-lg font-semibold ' + (isToday ? 'text-purple-700' : 'text-gray-800')}>
                  {d.getDate()}
                </div>
              </div>
              <div className="flex-1 space-y-1">
                {holiday && <Badge tone="red">{holiday}</Badge>}
                {shifts.length === 0 && !holiday ? (
                  <div className="text-sm text-gray-400">No shift</div>
                ) : (
                  shifts.map((s) => (
                    <div key={s.id} className="flex items-center justify-between gap-2">
                      <span className="text-sm text-gray-800">
                        {fmtTime(key, s)}
                        {s.role_name ? ` · ${s.role_name}` : ''}
                      </span>
                      <div className="flex items-center gap-2">
                        <Badge tone={STATUS_TONE[s.status] ?? 'gray'}>{s.status}</Badge>
                        <button
                          onClick={() => onRequestChange(s, key)}
                          className="rounded border border-gray-300 px-2 py-0.5 text-[11px] font-medium text-gray-600 hover:bg-gray-50"
                          title="Request a change to this shift"
                        >
                          Request change
                        </button>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </CardBody>
          </Card>
        )
      })}
    </div>
  )
}

function MonthGrid({
  anchor, shiftsByDate, holidayByDate, todayIso, fmtTime,
}: {
  anchor: Date
  shiftsByDate: Map<string, Shift[]>
  holidayByDate: Map<string, string>
  todayIso: string
  fmtTime: (dateStr: string, s: Shift) => string
}) {
  const monthStart = startOfMonth(anchor)
  const last = endOfMonth(anchor)
  // Leading blanks so the 1st sits under the right weekday (Mon-first).
  const leadBlanks = (monthStart.getDay() + 6) % 7
  const cells: (Date | null)[] = [
    ...Array.from({ length: leadBlanks }, () => null),
    ...Array.from({ length: last.getDate() }, (_, i) => new Date(anchor.getFullYear(), anchor.getMonth(), i + 1)),
  ]
  const weekdayHeaders = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-2">
      <div className="grid grid-cols-7 gap-1">
        {weekdayHeaders.map((w) => (
          <div key={w} className="text-center text-[10px] font-medium uppercase text-gray-400 py-1">{w}</div>
        ))}
        {cells.map((d, i) => {
          if (!d) return <div key={`b${i}`} />
          const key = iso(d)
          const shifts = shiftsByDate.get(key) ?? []
          const holiday = holidayByDate.get(key)
          const isToday = key === todayIso
          const first = shifts[0]
          return (
            <div
              key={key}
              className={`min-h-[52px] rounded-md border p-1 ${
                isToday ? 'border-purple-400 bg-purple-50/40' : 'border-gray-100'
              }`}
            >
              <div className={`text-[10px] font-semibold ${isToday ? 'text-purple-700' : 'text-gray-500'}`}>
                {d.getDate()}
              </div>
              {holiday && <div className="mt-0.5 truncate text-[8px] text-red-500">{holiday}</div>}
              {first && (
                <div
                  className="mt-0.5 truncate rounded px-1 text-[9px] font-medium text-white"
                  style={{ backgroundColor: first.color || '#7c3aed' }}
                  title={`${first.status}${first.start_time ? ` ${fmtTime(key, first)}` : ''}`}
                >
                  {first.start_time ? fmtTime(key, first) : first.status}
                </div>
              )}
              {shifts.length > 1 && (
                <div className="text-[8px] text-gray-400">+{shifts.length - 1}</div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
