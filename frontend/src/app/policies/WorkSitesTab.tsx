'use client'

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { captureLocation, geoFailureMessage } from '@/lib/geolocation'
import type { WorkArrangementRule, WorkSite } from '@/types'
import { useToast } from '@/components/ui/Toast'
import { usePermissions } from '@/contexts/PermissionsContext'

// Where people are expected to clock in, and what each work arrangement
// expects of a punch's location. The time clock has supported both since it
// shipped, but with no screen to set them up no site existed and the on-site
// check never ran for anyone.

interface SiteForm {
  name: string
  code: string
  latitude: string
  longitude: string
  radius_m: string
  address: string
}

const EMPTY: SiteForm = { name: '', code: '', latitude: '', longitude: '', radius_m: '200', address: '' }

const MODE_LABEL: Record<WorkArrangementRule['geofence_mode'], string> = {
  require_site: 'Must be at a work site (flagged if not)',
  any_location: 'Anywhere; record the location only',
  record_only: 'Record the location if given, no expectation',
}

function siteProblems(f: SiteForm): string[] {
  const out: string[] = []
  if (!f.name.trim()) out.push('Give the site a name.')
  const lat = Number(f.latitude)
  const lng = Number(f.longitude)
  if (f.latitude.trim() === '' || !Number.isFinite(lat) || lat < -90 || lat > 90) out.push('Latitude must be a number from -90 to 90.')
  if (f.longitude.trim() === '' || !Number.isFinite(lng) || lng < -180 || lng > 180) out.push('Longitude must be a number from -180 to 180.')
  const r = Number(f.radius_m)
  if (!Number.isInteger(r) || r < 10 || r > 100000) out.push('The radius must be a whole number of metres from 10 to 100,000.')
  return out
}

export default function WorkSitesTab() {
  const qc = useQueryClient()
  const { showToast } = useToast()
  const { hasPermission } = usePermissions()
  const canCreate = hasPermission('settings', 'create')
  const canEdit = hasPermission('settings', 'edit')
  const canDelete = hasPermission('settings', 'delete')

  const [form, setForm] = useState<SiteForm | null>(null)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [locating, setLocating] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState<number | null>(null)

  const sitesQ = useQuery<WorkSite[]>({ queryKey: ['work-sites'], queryFn: () => api.listWorkSites() })
  const rulesQ = useQuery<WorkArrangementRule[]>({ queryKey: ['arrangement-rules'], queryFn: () => api.listArrangementRules() })

  const sites = sitesQ.data ?? []
  const active = sites.filter((s) => s.is_active)
  const removed = sites.filter((s) => !s.is_active)

  const saveSite = useMutation({
    mutationFn: async (f: SiteForm) => {
      const payload = {
        name: f.name.trim(),
        code: f.code.trim() || null,
        latitude: Number(f.latitude),
        longitude: Number(f.longitude),
        radius_m: Number(f.radius_m),
        address: f.address.trim() || null,
      }
      return editingId ? api.updateWorkSite(editingId, payload) : api.createWorkSite(payload)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['work-sites'] })
      showToast(editingId ? 'Work site saved' : 'Work site added', 'success')
      setForm(null)
      setEditingId(null)
    },
    onError: (e: Error) => showToast(e.message, 'error'),
  })

  const setActive = useMutation({
    mutationFn: (v: { id: number; is_active: boolean }) => api.updateWorkSite(v.id, { is_active: v.is_active }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['work-sites'] }),
    onError: (e: Error) => showToast(e.message, 'error'),
  })

  const removeSite = useMutation({
    mutationFn: (id: number) => api.deleteWorkSite(id),
    onSuccess: () => {
      setConfirmDelete(null)
      qc.invalidateQueries({ queryKey: ['work-sites'] })
      showToast('Work site removed. If punches refer to it, it is kept in the removed list.', 'success')
    },
    onError: (e: Error) => showToast(e.message, 'error'),
  })

  const saveRule = useMutation({
    mutationFn: (v: { id: number; data: Partial<WorkArrangementRule> }) => api.updateArrangementRule(v.id, v.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['arrangement-rules'] })
      showToast('Arrangement saved', 'success')
    },
    onError: (e: Error) => showToast(e.message, 'error'),
  })

  const useMyLocation = async () => {
    setLocating(true)
    const geo = await captureLocation()
    setLocating(false)
    if (!geo.ok) {
      showToast(geoFailureMessage(geo.reason), 'error')
      return
    }
    setForm((f) => (f ? { ...f, latitude: geo.latitude.toFixed(6), longitude: geo.longitude.toFixed(6) } : f))
    if (geo.accuracy_m && geo.accuracy_m > 100) {
      showToast(`Your device placed you within ${Math.round(geo.accuracy_m)} m. Check the point before saving.`, 'info')
    }
  }

  const startEdit = (s: WorkSite) => {
    setEditingId(s.id)
    setForm({
      name: s.name, code: s.code ?? '', latitude: String(s.latitude), longitude: String(s.longitude),
      radius_m: String(s.radius_m), address: s.address ?? '',
    })
  }

  const problems = form ? siteProblems(form) : []

  return (
    <div className="space-y-8">
      <section className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Work sites</h2>
            <p className="text-sm text-gray-500">
              Places people clock in at. A punch counts as on site within the radius; a shift can name the site it expects.
            </p>
          </div>
          {canCreate && !form && (
            <button type="button" onClick={() => { setEditingId(null); setForm(EMPTY) }}
              className="rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700">
              Add work site
            </button>
          )}
        </div>

        {form && (
          <form
            className="space-y-3 rounded-lg border border-gray-200 bg-white p-4"
            onSubmit={(e) => { e.preventDefault(); if (!problems.length) saveSite.mutate(form) }}
          >
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <label className="block">
                <span className="mb-1 block text-sm font-medium text-gray-700">Name</span>
                <input className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
              </label>
              <label className="block">
                <span className="mb-1 block text-sm font-medium text-gray-700">Code (optional)</span>
                <input className="input" value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} />
              </label>
              <label className="block">
                <span className="mb-1 block text-sm font-medium text-gray-700">Latitude</span>
                <input className="input" inputMode="decimal" value={form.latitude} onChange={(e) => setForm({ ...form, latitude: e.target.value })} placeholder="e.g. 14.554729" />
              </label>
              <label className="block">
                <span className="mb-1 block text-sm font-medium text-gray-700">Longitude</span>
                <input className="input" inputMode="decimal" value={form.longitude} onChange={(e) => setForm({ ...form, longitude: e.target.value })} placeholder="e.g. 121.024445" />
              </label>
              <label className="block">
                <span className="mb-1 block text-sm font-medium text-gray-700">Radius (metres)</span>
                <input className="input" type="number" min="10" value={form.radius_m} onChange={(e) => setForm({ ...form, radius_m: e.target.value })} />
                <span className="mt-1 block text-xs text-gray-500">Phones indoors are often 100-200 m out; 200 m is a safe start.</span>
              </label>
              <label className="block">
                <span className="mb-1 block text-sm font-medium text-gray-700">Address (optional)</span>
                <input className="input" value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} />
              </label>
            </div>
            <button type="button" onClick={useMyLocation} disabled={locating}
              className="rounded-md border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50">
              {locating ? 'Finding you…' : 'Use my current location'}
            </button>
            {problems.length > 0 && (form.name || form.latitude || form.longitude) && (
              <ul className="list-disc space-y-0.5 rounded-md bg-red-50 py-2 pl-8 pr-3 text-sm text-red-800">
                {problems.map((p) => <li key={p}>{p}</li>)}
              </ul>
            )}
            <div className="flex justify-end gap-2">
              <button type="button" onClick={() => { setForm(null); setEditingId(null) }}
                className="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50">Cancel</button>
              <button type="submit" disabled={problems.length > 0 || saveSite.isPending}
                className="rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-50">
                {editingId ? 'Save site' : 'Add site'}
              </button>
            </div>
          </form>
        )}

        {sitesQ.isLoading ? (
          <p className="text-sm text-gray-500">Loading…</p>
        ) : sitesQ.error ? (
          <p className="text-sm text-red-700">Could not load work sites: {(sitesQ.error as Error).message}</p>
        ) : active.length === 0 ? (
          <div className="rounded-lg border border-dashed border-gray-300 p-6 text-center text-sm text-gray-500">
            No work sites yet. Without one, &quot;must be at a work site&quot; punches cannot be checked and are marked unverified.
          </div>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-gray-200">
            <table className="min-w-full divide-y divide-gray-200 text-sm">
              <thead className="bg-gray-50 text-left text-xs font-medium uppercase text-gray-500">
                <tr>
                  <th className="px-4 py-2">Site</th>
                  <th className="px-4 py-2">Location</th>
                  <th className="px-4 py-2">Radius</th>
                  <th className="px-4 py-2 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {active.map((s) => (
                  <tr key={s.id}>
                    <td className="px-4 py-2">
                      <div className="font-medium text-gray-900">{s.name}</div>
                      {(s.code || s.address) && <div className="text-xs text-gray-500">{[s.code, s.address].filter(Boolean).join(' · ')}</div>}
                    </td>
                    <td className="px-4 py-2 text-gray-600">
                      {s.latitude.toFixed(5)}, {s.longitude.toFixed(5)}
                      <a className="ml-2 text-brand-700 underline" target="_blank" rel="noreferrer noopener"
                        href={`https://www.openstreetmap.org/?mlat=${s.latitude}&mlon=${s.longitude}#map=17/${s.latitude}/${s.longitude}`}>map</a>
                    </td>
                    <td className="px-4 py-2 text-gray-600">{s.radius_m} m</td>
                    <td className="px-4 py-2 text-right space-x-2">
                      {canEdit && <button type="button" onClick={() => startEdit(s)} className="text-sm text-brand-600 hover:text-brand-800">Edit</button>}
                      {canDelete && (confirmDelete === s.id ? (
                        <>
                          <button type="button" onClick={() => removeSite.mutate(s.id)} disabled={removeSite.isPending} className="text-sm font-medium text-red-600 hover:text-red-800">Confirm remove</button>
                          <button type="button" onClick={() => setConfirmDelete(null)} className="text-sm text-gray-500 hover:text-gray-700">Cancel</button>
                        </>
                      ) : (
                        <button type="button" onClick={() => setConfirmDelete(s.id)} className="text-sm text-red-600 hover:text-red-800">Remove</button>
                      ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {removed.length > 0 && (
          <div className="rounded-lg border border-gray-200 p-3 text-sm">
            <p className="font-medium text-gray-700">Removed sites (kept because punches refer to them)</p>
            <ul className="mt-1 space-y-1">
              {removed.map((s) => (
                <li key={s.id} className="flex items-center justify-between text-gray-600">
                  <span>{s.name}</span>
                  {canEdit && (
                    <button type="button" onClick={() => setActive.mutate({ id: s.id, is_active: true })}
                      className="text-sm text-brand-600 hover:text-brand-800">Turn back on</button>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>

      <section className="space-y-3">
        <div>
          <h2 className="text-lg font-semibold text-gray-900">Work arrangements</h2>
          <p className="text-sm text-gray-500">
            What each shift arrangement expects of a punch&apos;s location. An arrangement not listed here never flags anyone.
            A punch is never refused because of its location; it is only flagged for review.
          </p>
        </div>
        {rulesQ.isLoading ? (
          <p className="text-sm text-gray-500">Loading…</p>
        ) : rulesQ.error ? (
          <p className="text-sm text-red-700">Could not load arrangements: {(rulesQ.error as Error).message}</p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-gray-200">
            <table className="min-w-full divide-y divide-gray-200 text-sm">
              <thead className="bg-gray-50 text-left text-xs font-medium uppercase text-gray-500">
                <tr>
                  <th className="px-4 py-2">Code</th>
                  <th className="px-4 py-2">Label</th>
                  <th className="px-4 py-2">Location expectation</th>
                  <th className="px-4 py-2">Active</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {(rulesQ.data ?? []).map((r) => (
                  <RuleRow key={r.id} rule={r} canEdit={canEdit}
                    onSave={(data) => saveRule.mutate({ id: r.id, data })} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}

function RuleRow({ rule, canEdit, onSave }: {
  rule: WorkArrangementRule
  canEdit: boolean
  onSave: (data: Partial<WorkArrangementRule>) => void
}) {
  const [label, setLabel] = useState(rule.label)
  return (
    <tr>
      <td className="px-4 py-2 font-mono text-gray-700">{rule.code}</td>
      <td className="px-4 py-2">
        <input className="input" aria-label={`Label for ${rule.code}`} value={label} disabled={!canEdit}
          onChange={(e) => setLabel(e.target.value)}
          onBlur={() => { if (label.trim() && label !== rule.label) onSave({ label: label.trim() }) }} />
      </td>
      <td className="px-4 py-2">
        <select className="input" aria-label={`Location expectation for ${rule.code}`} value={rule.geofence_mode} disabled={!canEdit}
          onChange={(e) => onSave({ geofence_mode: e.target.value as WorkArrangementRule['geofence_mode'] })}>
          {(Object.keys(MODE_LABEL) as WorkArrangementRule['geofence_mode'][]).map((m) => (
            <option key={m} value={m}>{MODE_LABEL[m]}</option>
          ))}
        </select>
      </td>
      <td className="px-4 py-2">
        <input type="checkbox" aria-label={`${rule.code} active`} checked={rule.is_active} disabled={!canEdit}
          onChange={(e) => onSave({ is_active: e.target.checked })} />
      </td>
    </tr>
  )
}
