'use client';

import { Suspense, useEffect, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import Link from 'next/link';
import Image from 'next/image';
import { Landmark, ShieldCheck } from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import { workspaceOf } from '@/lib/workspace';

// The administrator and finance doors. The ordinary sign-in page always opens
// an employee session, administrators and Finance included; these pages are
// the only way into the admin and finance dashboards, and they always ask for
// the password (and the second factor when the account has one). They look
// deliberately unlike the employee sign-in, and unlike each other (amber for
// administration, emerald for finance), so nobody arrives at one by accident.

type Portal = 'admin' | 'finance';

const COPY: Record<Portal, {
  badge: string;
  heading: string;
  intro: string;
  submit: string;
  switches: string;
  ended: string;
  endedWhy: string;
  Icon: typeof ShieldCheck;
  accentText: string;
  accentBorder: string;
  accentFocus: string;
  button: string;
  endedBox: string;
  endedTitle: string;
  endedText: string;
}> = {
  admin: {
    badge: 'Admin',
    heading: 'Administrator sign-in',
    intro: 'For managing the company. Your own schedule, leave and payslips are on the',
    submit: 'Sign in to the admin dashboard',
    switches: 'Signing in here switches this browser to the admin dashboard.',
    ended: 'Your admin session ended.',
    endedWhy: 'Admin sessions end after 30 minutes without activity, and after 8 hours at most.',
    Icon: ShieldCheck,
    accentText: 'text-amber-300',
    accentBorder: 'border-amber-400/60',
    accentFocus: 'focus:border-amber-400 focus:ring-amber-400/40',
    button: 'bg-amber-400 hover:bg-amber-300',
    endedBox: 'border-amber-400/50 bg-amber-400/10',
    endedTitle: 'text-amber-200',
    endedText: 'text-amber-100/80',
  },
  finance: {
    badge: 'Finance',
    heading: 'Finance sign-in',
    intro: 'For payroll and the rest of Finances. Your own schedule, leave and payslips are on the',
    submit: 'Sign in to the finance dashboard',
    switches: 'Signing in here switches this browser to the finance dashboard.',
    ended: 'Your finance session ended.',
    endedWhy: 'Finance sessions end after 30 minutes without activity, and after 8 hours at most.',
    Icon: Landmark,
    accentText: 'text-emerald-300',
    accentBorder: 'border-emerald-400/60',
    accentFocus: 'focus:border-emerald-400 focus:ring-emerald-400/40',
    button: 'bg-emerald-400 hover:bg-emerald-300',
    endedBox: 'border-emerald-400/50 bg-emerald-400/10',
    endedTitle: 'text-emerald-200',
    endedText: 'text-emerald-100/80',
  },
};

export default function PortalSignIn({ portal }: { portal: Portal }) {
  return (
    <Suspense>
      <PortalSignInInner portal={portal} />
    </Suspense>
  );
}

function PortalSignInInner({ portal }: { portal: Portal }) {
  const { user, isLoading: authLoading, login, verify2FA } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const ended = searchParams.get('ended') === '1';
  const copy = COPY[portal];
  const Icon = copy.Icon;
  const id = (name: string) => `${portal}-${name}`;

  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [show2FA, setShow2FA] = useState(false);
  const [code, setCode] = useState('');

  // Already in this kind of session in this browser: nothing to do here.
  useEffect(() => {
    if (!authLoading && user && workspaceOf(user) === portal) router.replace('/dashboard');
  }, [authLoading, user, router, portal]);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const result = await login({ username, password }, portal);
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
      // The challenge cookie remembers which door the password was given at.
      await verify2FA(code);
      router.replace('/dashboard');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'That code is not correct.');
    } finally {
      setLoading(false);
    }
  };

  if (authLoading) return null;

  const inputCls = `w-full rounded-lg border border-gray-600 bg-gray-900 px-4 py-3 text-white placeholder-gray-500 outline-none focus:ring-2 ${copy.accentFocus}`;
  const buttonCls = `flex min-h-[44px] w-full items-center justify-center rounded-lg py-3 font-semibold text-gray-950 transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${copy.button}`;

  return (
    <div className="min-h-app flex items-center justify-center bg-gray-950 px-4 py-10 pt-[calc(2.5rem+env(safe-area-inset-top))] pb-[calc(2.5rem+env(safe-area-inset-bottom))]">
      <div className="w-full max-w-md">
        <div className="mb-8 flex flex-col items-center gap-3 text-center">
          <span className="inline-flex items-center rounded-md bg-white px-2 py-1">
            <Image src="/logo/ursked-logo.svg" alt="ursked" width={294} height={64} priority className="h-7 w-auto" />
          </span>
          <span className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-semibold uppercase tracking-wider ${copy.accentBorder} ${copy.accentText}`}>
            <Icon className="h-4 w-4" aria-hidden="true" />
            {copy.badge}
          </span>
        </div>

        <div className="rounded-xl border border-gray-800 bg-gray-900/80 p-6 sm:p-8 shadow-xl">
          <h1 className="text-2xl font-bold text-white">{copy.heading}</h1>
          <p className="mt-1 text-sm text-gray-300">
            {copy.intro}{' '}
            <Link href="/auth/login" className={`font-medium underline-offset-2 hover:underline ${copy.accentText}`}>
              employee sign-in
            </Link>
            .
          </p>

          {ended && !show2FA && (
            <div role="status" className={`mt-5 rounded-lg border p-3 ${copy.endedBox}`}>
              <p className={`text-sm font-medium ${copy.endedTitle}`}>{copy.ended}</p>
              <p className={`mt-0.5 text-xs ${copy.endedText}`}>{copy.endedWhy}</p>
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
                <label htmlFor={id('username')} className="mb-1 block text-sm font-medium text-gray-200">
                  Email or username
                </label>
                <input
                  id={id('username')}
                  type="text"
                  autoComplete="username"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  required
                  className={inputCls}
                />
              </div>
              <div>
                <label htmlFor={id('password')} className="mb-1 block text-sm font-medium text-gray-200">
                  Password
                </label>
                <input
                  id={id('password')}
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  className={inputCls}
                />
              </div>
              <button type="submit" disabled={loading} className={buttonCls}>
                {loading ? 'Signing in…' : copy.submit}
              </button>
              <p className="text-xs text-gray-400">{copy.switches}</p>
            </form>
          ) : (
            <form onSubmit={onVerify} className="mt-6 space-y-4">
              <div>
                <label htmlFor={id('code')} className="mb-1 block text-sm font-medium text-gray-200">
                  Code from your authenticator app
                </label>
                <input
                  id={id('code')}
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
              <button type="submit" disabled={loading || code.length < 6} className={buttonCls}>
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
