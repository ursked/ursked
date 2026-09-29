'use client';

import React, { useEffect, useState } from 'react';
import { ShieldCheck } from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import { api } from '@/lib/api';
import { hasEmployeeWorkspace } from '@/lib/workspace';
import { setTitleMarker } from './RouteTitle';

// How often the bar re-reads the session from the server. The idle limit
// slides whenever the person does something, so the end time moves; reading it
// back keeps the countdown honest. Made while idle, these reads carry the
// idle header (lib/api.ts) and so do not themselves keep the session alive.
const SESSION_POLL_MS = 60_000;

function minutesLeft(expiresAt: string | null | undefined, now: number): number | null {
  if (!expiresAt) return null;
  const ms = new Date(expiresAt).getTime() - now;
  return Math.max(0, Math.ceil(ms / 60_000));
}

/**
 * The unmistakable marker of an admin session: a dark bar with an amber accent
 * across the top of every admin screen, the time left before the session ends,
 * and the way back to the employee dashboard. Also marks the browser tab.
 *
 * Rendered only in an admin session. The server is what enforces the limits;
 * when the countdown runs out the bar asks the server, and a 401 there sends
 * the person to the administrator sign-in with "Your admin session ended".
 */
export function AdminBar() {
  const { user, exitAdmin, logout } = useAuth();
  const [now, setNow] = useState(() => Date.now());
  const [leaving, setLeaving] = useState(false);
  // The latest end time the server reported. Kept here rather than by
  // refreshing the signed-in user, which would re-read permissions and
  // re-render the whole app every minute.
  const [polledEnd, setPolledEnd] = useState<string | null>(null);
  const expiresAt = polledEnd ?? user?.expires_at ?? null;

  useEffect(() => {
    setTitleMarker('Admin');
    return () => setTitleMarker(null);
  }, []);

  useEffect(() => {
    // A 401 here (the session ended) reaches the api client's session-expiry
    // handler, which sends the person to the administrator sign-in.
    const readEnd = () =>
      api.getCurrentUser().then((u) => setPolledEnd(u.expires_at ?? null)).catch(() => {});
    const tick = setInterval(() => setNow(Date.now()), 15_000);
    const poll = setInterval(readEnd, SESSION_POLL_MS);
    return () => {
      clearInterval(tick);
      clearInterval(poll);
    };
  }, []);

  const left = minutesLeft(expiresAt, now);

  // Out of time by the last reading: ask the server, which either reports a
  // later end (the person was active in another tab) or refuses, and the
  // session-expiry handler takes over.
  useEffect(() => {
    if (left !== 0) return;
    api.getCurrentUser().then((u) => setPolledEnd(u.expires_at ?? null)).catch(() => {});
  }, [left]);

  if (!user) return null;

  const onExit = async () => {
    setLeaving(true);
    try {
      await exitAdmin();
    } finally {
      setLeaving(false);
    }
  };

  const capAt = user.admin_expires_at ? new Date(user.admin_expires_at) : null;
  const leftLabel =
    left === null ? '' : left <= 1 ? 'Ends in under a minute' : `Ends in ${left} min`;

  return (
    <div
      role="region"
      aria-label="Admin mode"
      className="flex-shrink-0 bg-gray-950 text-white border-b-2 border-amber-400 pt-[env(safe-area-inset-top)] pl-[env(safe-area-inset-left)]"
    >
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 px-4 py-2 lg:px-6">
        <div className="flex min-w-0 items-center gap-2">
          <ShieldCheck className="h-4 w-4 flex-shrink-0 text-amber-300" aria-hidden="true" />
          <span className="text-sm font-semibold text-amber-300">Admin mode</span>
          {leftLabel && (
            <span
              className="truncate text-xs text-gray-300"
              title={capAt ? `Ends after 30 minutes without activity, and at ${capAt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} at the latest.` : undefined}
            >
              {leftLabel}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {hasEmployeeWorkspace(user) ? (
            <button
              type="button"
              onClick={onExit}
              disabled={leaving}
              className="min-h-[36px] rounded-md bg-amber-400 px-3 py-1.5 text-xs font-semibold text-gray-950 hover:bg-amber-300 disabled:opacity-60"
            >
              {leaving ? 'Switching…' : 'Go to my employee dashboard'}
            </button>
          ) : (
            <button
              type="button"
              onClick={() => void logout()}
              className="min-h-[36px] rounded-md bg-amber-400 px-3 py-1.5 text-xs font-semibold text-gray-950 hover:bg-amber-300"
            >
              Sign out
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
