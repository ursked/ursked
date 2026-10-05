'use client'

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { useToast } from '@/components/ui/Toast'
import type { ActiveSession, LoginEvent, TwoFactorSetup, TwoFactorStatus } from '@/types'

// My Profile > Security. Two-factor sign-in, active sessions and recent
// sign-ins were built in the API and advertised in the README, but nothing on
// screen reached them (audit W-5).

function describeDevice(ua: string | null): string {
  if (!ua) return 'Unknown device'
  const browser = /Edg\//.test(ua) ? 'Edge' : /Chrome\//.test(ua) ? 'Chrome' : /Firefox\//.test(ua) ? 'Firefox' : /Safari\//.test(ua) ? 'Safari' : 'Browser'
  const os = /iPhone|iPad/.test(ua) ? 'iPhone/iPad' : /Android/.test(ua) ? 'Android' : /Windows/.test(ua) ? 'Windows' : /Mac OS X/.test(ua) ? 'Mac' : /Linux/.test(ua) ? 'Linux' : ''
  return os ? `${browser} on ${os}` : browser
}

function when(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString() : '--'
}

const cardClass = 'bg-white border border-gray-200 rounded-xl shadow-sm'
const secondaryBtn =
  'inline-flex items-center rounded-md bg-white px-4 py-2 text-sm font-semibold text-gray-700 shadow-sm ring-1 ring-inset ring-gray-300 hover:bg-gray-50 transition-colors disabled:opacity-50'
const primaryBtn =
  'inline-flex items-center rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-brand-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors'

export default function SecuritySection() {
  const queryClient = useQueryClient()
  const { showToast } = useToast()

  const { data: tfa, isLoading: tfaLoading } = useQuery<TwoFactorStatus>({
    queryKey: ['2fa-status'],
    queryFn: () => api.getTwoFactorStatus(),
  })
  const { data: sessions = [] } = useQuery<ActiveSession[]>({
    queryKey: ['my-sessions'],
    queryFn: () => api.getMySessions(),
  })
  const { data: events } = useQuery<{ items: LoginEvent[]; total: number }>({
    queryKey: ['my-login-events'],
    queryFn: () => api.getMyLoginEvents(10),
  })

  const [setup, setSetup] = useState<TwoFactorSetup | null>(null)
  const [code, setCode] = useState('')
  const [codesSaved, setCodesSaved] = useState(false)
  const [disabling, setDisabling] = useState(false)
  const [password, setPassword] = useState('')

  const refresh2fa = () => queryClient.invalidateQueries({ queryKey: ['2fa-status'] })

  const start = useMutation({
    mutationFn: () => api.setupTwoFactor(),
    onSuccess: (data) => { setSetup(data); setCode(''); setCodesSaved(false) },
    onError: (err: Error) => showToast(err.message, 'error'),
  })
  const confirm = useMutation({
    mutationFn: () => api.confirmTwoFactor(code),
    onSuccess: () => { setSetup(null); refresh2fa(); showToast('Two-factor sign-in is on', 'success') },
    onError: (err: Error) => showToast(err.message, 'error'),
  })
  const disable = useMutation({
    mutationFn: () => api.disableTwoFactor(password),
    onSuccess: () => { setDisabling(false); setPassword(''); refresh2fa(); showToast('Two-factor sign-in is off', 'success') },
    onError: (err: Error) => showToast(err.message, 'error'),
  })
  const signOut = useMutation({
    mutationFn: (id: number) => api.revokeSession(id),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['my-sessions'] }); showToast('Signed out that session', 'success') },
    onError: (err: Error) => showToast(err.message, 'error'),
  })

  const copyCodes = async () => {
    if (!setup) return
    try {
      await navigator.clipboard.writeText(setup.backup_codes.join('\n'))
      showToast('Recovery codes copied', 'success')
    } catch {
      showToast('Could not copy; write the codes down instead', 'error')
    }
  }

  return (
    <div className={cardClass}>
      <div className="px-6 py-5 border-b border-gray-200">
        <h3 className="text-lg font-semibold text-gray-900">Security</h3>
        <p className="text-sm text-gray-500">Two-factor sign-in, where you are signed in, and recent sign-ins.</p>
      </div>

      {/* Two-factor */}
      <section className="px-6 py-5 border-b border-gray-100 space-y-4" aria-labelledby="sec-2fa">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div>
            <h4 id="sec-2fa" className="text-sm font-semibold text-gray-900">Two-factor sign-in</h4>
            <p className="text-sm text-gray-500">
              {tfaLoading
                ? 'Checking…'
                : tfa?.enabled
                  ? `On. You have ${tfa.recovery_codes_remaining} unused recovery ${tfa.recovery_codes_remaining === 1 ? 'code' : 'codes'}.`
                  : 'Off. Turn it on to ask for a code from an authenticator app when you sign in.'}
            </p>
          </div>
          {!tfaLoading && !setup && (
            tfa?.enabled ? (
              !disabling && <button type="button" className={secondaryBtn} onClick={() => setDisabling(true)}>Turn off</button>
            ) : (
              <button type="button" className={primaryBtn} onClick={() => start.mutate()} disabled={start.isPending}>
                {start.isPending ? 'Starting…' : 'Turn on'}
              </button>
            )
          )}
        </div>

        {setup && (
          <div className="rounded-lg border border-gray-200 bg-gray-50 p-4 space-y-4">
            <ol className="list-decimal space-y-4 pl-5 text-sm text-gray-700">
              <li>
                Scan this code with an authenticator app (Google Authenticator, Microsoft Authenticator, 1Password…).
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={setup.qr_code_base64} alt="QR code for your authenticator app" className="mt-2 h-44 w-44 rounded bg-white p-1" />
                <p className="mt-2 text-xs text-gray-500">
                  Cannot scan? Enter this key instead: <code className="break-all rounded bg-white px-1 py-0.5 font-mono text-gray-900">{setup.secret}</code>
                </p>
              </li>
              <li>
                Save these recovery codes somewhere safe. Each works once if you lose your phone. They are shown only now.
                <div className="mt-2 grid grid-cols-2 sm:grid-cols-3 gap-2 font-mono text-sm">
                  {setup.backup_codes.map((c) => (
                    <span key={c} className="rounded bg-white px-2 py-1 text-gray-900 ring-1 ring-gray-200">{c}</span>
                  ))}
                </div>
                <div className="mt-2 flex flex-wrap items-center gap-3">
                  <button type="button" className={secondaryBtn} onClick={copyCodes}>Copy codes</button>
                  <label className="inline-flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={codesSaved} onChange={(e) => setCodesSaved(e.target.checked)} className="h-4 w-4 rounded border-gray-300 text-brand-600" />
                    I have saved my recovery codes
                  </label>
                </div>
              </li>
              <li>
                Enter the 6-digit code the app shows now.
                <form
                  className="mt-2 flex flex-wrap items-center gap-2"
                  onSubmit={(e) => { e.preventDefault(); confirm.mutate() }}
                >
                  <label htmlFor="tfa-code" className="sr-only">Code from your authenticator app</label>
                  <input
                    id="tfa-code"
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    maxLength={8}
                    value={code}
                    onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
                    className="w-32 rounded-md border border-gray-300 px-3 py-2 text-sm font-mono tracking-widest"
                  />
                  <button type="submit" className={primaryBtn} disabled={code.length < 6 || !codesSaved || confirm.isPending}>
                    {confirm.isPending ? 'Checking…' : 'Confirm and turn on'}
                  </button>
                  <button type="button" className={secondaryBtn} onClick={() => setSetup(null)}>Cancel</button>
                </form>
              </li>
            </ol>
          </div>
        )}

        {disabling && (
          <form
            className="rounded-lg border border-gray-200 bg-gray-50 p-4 flex flex-wrap items-end gap-3"
            onSubmit={(e) => { e.preventDefault(); disable.mutate() }}
          >
            <div>
              <label htmlFor="tfa-pw" className="block text-sm font-medium text-gray-700 mb-1">Your password</label>
              <input id="tfa-pw" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)}
                className="w-64 max-w-full rounded-md border border-gray-300 px-3 py-2 text-sm" />
            </div>
            <button type="submit" className="inline-flex items-center rounded-md bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-700 disabled:opacity-50" disabled={!password || disable.isPending}>
              Turn off two-factor
            </button>
            <button type="button" className={secondaryBtn} onClick={() => { setDisabling(false); setPassword('') }}>Cancel</button>
          </form>
        )}
      </section>

      {/* Sessions */}
      <section className="px-6 py-5 border-b border-gray-100" aria-labelledby="sec-sessions">
        <h4 id="sec-sessions" className="text-sm font-semibold text-gray-900">Where you are signed in</h4>
        {sessions.length === 0 ? (
          <p className="mt-2 text-sm text-gray-500">No other active sessions.</p>
        ) : (
          <ul className="mt-2 divide-y divide-gray-100">
            {sessions.map((s) => (
              <li key={s.id} className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 py-3">
                <div className="min-w-0">
                  <p className="text-sm text-gray-900">
                    {describeDevice(s.user_agent)}
                    {s.is_current && <span className="ml-2 rounded-full bg-green-50 px-2 py-0.5 text-xs font-medium text-green-700">This device</span>}
                  </p>
                  <p className="text-xs text-gray-500">Signed in {when(s.login_at)}{s.ip_address ? ` from ${s.ip_address}` : ''}</p>
                </div>
                {!s.is_current && (
                  <button type="button" className={secondaryBtn} onClick={() => signOut.mutate(s.id)} disabled={signOut.isPending}>
                    Sign out
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Recent sign-ins */}
      <section className="px-6 py-5" aria-labelledby="sec-events">
        <h4 id="sec-events" className="text-sm font-semibold text-gray-900">Recent sign-ins</h4>
        <p className="text-xs text-gray-500">If you do not recognise one, change your password and turn on two-factor sign-in.</p>
        {!events || events.items.length === 0 ? (
          <p className="mt-2 text-sm text-gray-500">No sign-ins recorded yet.</p>
        ) : (
          <ul className="mt-2 divide-y divide-gray-100">
            {events.items.map((e) => (
              <li key={e.id} className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-1 py-2 text-sm">
                <span className={e.action === 'login_success' ? 'text-gray-900' : 'text-red-700'}>
                  {e.action === 'login_success' ? 'Signed in' : 'Failed attempt'} &middot; {describeDevice(e.user_agent)}
                </span>
                <span className="text-xs text-gray-500">{when(e.created_at)}{e.ip_address ? ` · ${e.ip_address}` : ''}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
