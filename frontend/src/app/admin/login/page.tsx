'use client';

import { Suspense, useEffect, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import Link from 'next/link';
import Image from 'next/image';
import { ShieldCheck } from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import { isAdminSession } from '@/lib/workspace';

// Admin mode: the administrator door. The ordinary sign-in page always opens
// an employee session, administrators included; this page is the only way
// into the admin dashboard, and it always asks for the password (and the
// second factor when the account has one). It looks deliberately unlike the
// employee sign-in so nobody arrives here by accident.
export default function AdminLoginPage() {
  return (
    <Suspense>
      <AdminLoginInner />
    </Suspense>
  );
}

function AdminLoginInner() {
  const { user, isLoading: authLoading, login, verify2FA } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const ended = searchParams.get('ended') === '1';

  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [show2FA, setShow2FA] = useState(false);
  const [code, setCode] = useState('');

  // Already in an admin session in this browser: nothing to do here.
  useEffect(() => {
    if (!authLoading && isAdminSession(user)) router.replace('/dashboard');
  }, [authLoading, user, router]);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const result = await login({ username, password }, 'admin');
      if (result.requires2FA) {
        setShow2FA(true);
      } else {
        router.replace('/dashboard');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign-in failed.');
    } finally {
      setLoading(false);
    }
  };

  const onVerify = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await verify2FA(code);
      router.replace('/dashboard');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'That code is not correct.');
    } finally {
      setLoading(false);
    }
  };

  if (authLoading) return null;

  const inputCls =
    'w-full rounded-lg border border-gray-600 bg-gray-900 px-4 py-3 text-white placeholder-gray-500 outline-none focus:border-amber-400 focus:ring-2 focus:ring-amber-400/40';

  return (
    <div className="min-h-app flex items-center justify-center bg-gray-950 px-4 py-10 pt-[calc(2.5rem+env(safe-area-inset-top))] pb-[calc(2.5rem+env(safe-area-inset-bottom))]">
      <div className="w-full max-w-md">
        <div className="mb-8 flex flex-col items-center gap-3 text-center">
          <span className="inline-flex items-center rounded-md bg-white px-2 py-1">
            <Image src="/logo/urskedlogo.png" alt="ursked" width={1311} height={359} priority className="h-7 w-auto" />
          </span>
          <span className="inline-flex items-center gap-2 rounded-full border border-amber-400/60 px-3 py-1 text-xs font-semibold uppercase tracking-wider text-amber-300">
            <ShieldCheck className="h-4 w-4" aria-hidden="true" />
            Admin
          </span>
        </div>

        <div className="rounded-xl border border-gray-800 bg-gray-900/80 p-6 sm:p-8 shadow-xl">
          <h1 className="text-2xl font-bold text-white">Administrator sign-in</h1>
          <p className="mt-1 text-sm text-gray-300">
            For managing the company. Your own schedule, leave and payslips are on the{' '}
            <Link href="/auth/login" className="font-medium text-amber-300 underline-offset-2 hover:underline">
              employee sign-in
            </Link>
            .
          </p>

          {ended && !show2FA && (
            <div role="status" className="mt-5 rounded-lg border border-amber-400/50 bg-amber-400/10 p-3">
              <p className="text-sm font-medium text-amber-200">Your admin session ended.</p>
              <p className="mt-0.5 text-xs text-amber-100/80">
                Admin sessions end after 30 minutes without activity, and after 8 hours at most.
              </p>
            </div>
          )}

          {error && (
            <div role="alert" className="mt-5 rounded-lg border border-red-400/50 bg-red-500/10 p-3">
              <p className="text-sm text-red-200">{error}</p>
            </div>
          )}

          {!show2FA ? (
            <form onSubmit={onSubmit} className="mt-6 space-y-4">
              <div>
                <label htmlFor="admin-username" className="mb-1 block text-sm font-medium text-gray-200">
                  Email or username
                </label>
                <input
                  id="admin-username"
                  type="text"
                  autoComplete="username"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  required
                  className={inputCls}
                />
              </div>
              <div>
                <label htmlFor="admin-password" className="mb-1 block text-sm font-medium text-gray-200">
                  Password
                </label>
                <input
                  id="admin-password"
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  className={inputCls}
                />
              </div>
              <button
                type="submit"
                disabled={loading}
                className="flex min-h-[44px] w-full items-center justify-center rounded-lg bg-amber-400 py-3 font-semibold text-gray-950 transition-colors hover:bg-amber-300 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {loading ? 'Signing in…' : 'Sign in to the admin dashboard'}
              </button>
              <p className="text-xs text-gray-400">
                Signing in here switches this browser to the admin dashboard.
              </p>
            </form>
          ) : (
            <form onSubmit={onVerify} className="mt-6 space-y-4">
              <div>
                <label htmlFor="admin-code" className="mb-1 block text-sm font-medium text-gray-200">
                  Code from your authenticator app
                </label>
                <input
                  id="admin-code"
                  type="text"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  value={code}
                  onChange={(e) => setCode(e.target.value.replace(/\s/g, '').slice(0, 12))}
                  required
                  autoFocus
                  className={`${inputCls} text-center font-mono text-xl tracking-[0.4em]`}
                  placeholder="000000"
                />
              </div>
              <button
                type="submit"
                disabled={loading || code.length < 6}
                className="flex min-h-[44px] w-full items-center justify-center rounded-lg bg-amber-400 py-3 font-semibold text-gray-950 transition-colors hover:bg-amber-300 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {loading ? 'Verifying…' : 'Verify'}
              </button>
              <button
                type="button"
                onClick={() => {
                  setShow2FA(false);
                  setCode('');
                  setError('');
                }}
                className="w-full py-2 text-sm text-gray-400 hover:text-gray-200"
              >
                Back
              </button>
            </form>
          )}
        </div>

        <p className="mt-6 text-center text-sm">
          <Link href="/auth/forgot-password" className="text-gray-400 hover:text-gray-200">
            Forgot your password?
          </Link>
        </p>
      </div>
    </div>
  );
}
