'use client';

import { useEffect, useState } from 'react';
import { WifiOff } from 'lucide-react';
import { OFFLINE_COPY_MESSAGE, FRESH_MESSAGE } from '@/components/PWARegistrar';

function hhmm(iso: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

/**
 * App-wide connection notice.
 *
 * Offline used to look exactly like online: screens spun or showed stale data
 * with nothing to say so, and changes queued silently. This says when the
 * device is offline, and when what is on screen is the saved copy the service
 * worker kept (it marks those responses and tells the page the time the copy
 * was saved).
 */
export function OfflineBanner() {
  const [online, setOnline] = useState(true);
  const [copyAt, setCopyAt] = useState<string | null>(null);

  useEffect(() => {
    const update = () => {
      setOnline(navigator.onLine);
      if (navigator.onLine) setCopyAt(null);
    };
    // Deferred so the first state update does not run synchronously in the
    // effect body (react-hooks/set-state-in-effect).
    void Promise.resolve().then(update);
    window.addEventListener('online', update);
    window.addEventListener('offline', update);

    const onMessage = (event: MessageEvent) => {
      const data = event.data as { type?: string; cachedAt?: string } | null;
      if (data?.type === OFFLINE_COPY_MESSAGE) setCopyAt(data.cachedAt ?? '');
      else if (data?.type === FRESH_MESSAGE) setCopyAt(null);
    };
    const sw = typeof navigator !== 'undefined' ? navigator.serviceWorker : undefined;
    sw?.addEventListener('message', onMessage);

    return () => {
      window.removeEventListener('online', update);
      window.removeEventListener('offline', update);
      sw?.removeEventListener('message', onMessage);
    };
  }, []);

  if (online && copyAt === null) return null;

  const savedAt = hhmm(copyAt);
  const message = !online
    ? savedAt
      ? `You are offline. Showing an offline copy from ${savedAt}; changes will not be sent.`
      : 'You are offline. Changes you make will not be sent.'
    : `The server could not be reached. Showing an offline copy${savedAt ? ` from ${savedAt}` : ''}.`;

  // Just below the 4rem header, so the menu and account buttons stay visible.
  return (
    <div
      role="status"
      aria-live="polite"
      className="fixed left-1/2 -translate-x-1/2 top-[calc(4.5rem+env(safe-area-inset-top))] z-[70] w-max max-w-[calc(100vw-2rem)] sm:max-w-md pointer-events-none"
    >
      <div className="flex items-center gap-2 rounded-full bg-gray-900/90 px-4 py-2 text-xs sm:text-sm font-medium text-white shadow-lg">
        <WifiOff className="h-4 w-4 flex-shrink-0 text-amber-300" aria-hidden="true" />
        <span>{message}</span>
      </div>
    </div>
  );
}
