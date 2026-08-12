'use client';

import { useState } from 'react';
import Image from 'next/image';
import { api } from '@/lib/api';
import { useAuth } from '@/contexts/AuthContext';

/**
 * Shown in place of the app when the signed-in user still has
 * must_change_password set (e.g. a self-hosted first administrator, or an
 * admin-forced reset). Until they set a new password there is no way past this
 * screen — every authenticated page renders through DashboardLayout, which
 * gates on this.
 */
export function ForcePasswordChange() {
  const { refreshUser, logout } = useAuth();
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const strongEnough = (pw: string) =>
    pw.length >= 8 && /[a-z]/.test(pw) && /[A-Z]/.test(pw) && /[0-9]/.test(pw);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    if (next !== confirm) {
      setError('New passwords do not match.');
      return;
    }
    if (!strongEnough(next)) {
      setError('Password must be at least 8 characters and include upper, lower, and a number.');
      return;
    }
    if (next === current) {
      setError('Choose a password different from your current one.');
      return;
    }
    setBusy(true);
    try {
      await api.changePassword({ current_password: current, new_password: next });
      // The flag is now cleared server-side; refresh so the app unlocks.
      await refreshUser();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not change password.');
      setBusy(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-slate-50 via-white to-slate-100 px-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <Image src="/logo/urskedlogo.png" alt="ursked" width={1311} height={359} priority className="mx-auto h-10 w-auto" />
        </div>
        <div className="bg-white rounded-xl shadow-lg p-8">
          <h1 className="text-xl font-semibold text-gray-900">Set a new password</h1>
          <p className="mt-1 text-sm text-gray-500">
            For security, you must choose a new password before continuing.
          </p>

          {error && (
            <div className="mt-4 rounded-md bg-red-50 border border-red-200 p-3 text-sm text-red-700">
              {error}
            </div>
          )}

          <form onSubmit={submit} className="mt-6 space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Current password</label>
              <input
                type="password"
                value={current}
                onChange={(e) => setCurrent(e.target.value)}
                required
                autoComplete="current-password"
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-teal-500 focus:ring-teal-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">New password</label>
              <input
                type="password"
                value={next}
                onChange={(e) => setNext(e.target.value)}
                required
                autoComplete="new-password"
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-teal-500 focus:ring-teal-500"
              />
              <p className="mt-1 text-xs text-gray-500">
                At least 8 characters, with uppercase, lowercase, and a number.
              </p>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Confirm new password</label>
              <input
                type="password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                required
                autoComplete="new-password"
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-teal-500 focus:ring-teal-500"
              />
            </div>
            <button
              type="submit"
              disabled={busy}
              className="w-full rounded-md bg-teal-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-teal-700 disabled:opacity-50"
            >
              {busy ? 'Saving…' : 'Set password & continue'}
            </button>
          </form>

          <button
            onClick={() => logout()}
            className="mt-4 w-full text-center text-sm text-gray-500 hover:text-gray-700"
          >
            Sign out
          </button>
        </div>
      </div>
    </div>
  );
}
