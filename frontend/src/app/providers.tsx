'use client';

import React, { useEffect, useState } from 'react';
import { QueryClient, QueryClientProvider, QueryCache, MutationCache } from '@tanstack/react-query';
import { AuthProvider } from '@/contexts/AuthContext';
import { PermissionsProvider } from '@/contexts/PermissionsContext';
import { ToastProvider, useToast } from '@/components/ui/Toast';
import { ErrorBoundary } from '@/components/ui/ErrorBoundary';
import MaintenanceGuard from '@/components/MaintenanceGuard';
import { ApiError } from '@/lib/api';

/**
 * Bridge between the QueryCache (module scope) and the toast context (React
 * scope). `QueryErrorToasts` registers the context's `showToast` here on mount;
 * the cache's onError reads it.
 */
let toastSink: ((message: string, type: 'error') => void) | null = null;

function QueryErrorToasts() {
  const { showToast } = useToast();
  useEffect(() => {
    toastSink = (message, type) => showToast(message, type);
    return () => {
      toastSink = null;
    };
  }, [showToast]);
  return null;
}

/** Shown when a change could not be sent because the device is offline. */
export const OFFLINE_MUTATION_MESSAGE = 'You are offline — this was not sent.';

function isOffline(): boolean {
  return typeof navigator !== 'undefined' && navigator.onLine === false;
}

/** fetch() rejects with a TypeError whose wording differs per browser when the
 * network is unreachable ("Failed to fetch", "Load failed", "NetworkError when
 * attempting to fetch resource."). Everything the server answers is an ApiError. */
function isNetworkFailure(error: unknown): boolean {
  return error instanceof TypeError && !(error instanceof ApiError);
}

// Query keys whose failure has already been reported and not yet recovered.
// A background refetch that keeps failing (the dashboard polls every minute)
// reports once, not once a minute.
const reportedFailures = new Set<string>();

/**
 * A failed fetch used to be indistinguishable from an empty result. Of 243
 * useQuery call sites across 52 files, four handled `isError`; everywhere else
 * `data` came back undefined, `isLoading` went false, and the page rendered its
 * empty state. A reviewer whose approvals request failed was told "You're all
 * caught up"; an employee was told they had no leave requests.
 *
 * Patching 243 call sites would be a large and risky diff. One cache-level
 * handler makes every failure audible instead: whatever the screen decides to
 * render, the user is told the request failed and can act on it.
 *
 * Not reported:
 * - 401 (the ordinary pre-auth probe on every page load), 403 (the permissions
 *   system working — the UI hides what the role cannot see) and 404 (a record
 *   or an optional feature that is not there; the screens that ask show their
 *   own "not found" state).
 * - Queries marked `meta: { handlesErrors: true }`: the screen already shows
 *   its own error card with a Retry button.
 * - Failures while the device is offline: the offline banner says so once.
 * - The same query failing again before it has succeeded: one toast per
 *   outage, not one per refetch. Identical messages are also collapsed by the
 *   toast container itself.
 */
const queryClient = new QueryClient({
  queryCache: new QueryCache({
    onError: (error, query) => {
      const status = error instanceof ApiError ? error.status : 0;
      if (status === 401 || status === 403 || status === 404) return;
      if (query.meta?.handlesErrors) return;
      if (isOffline()) return;
      if (reportedFailures.has(query.queryHash)) return;
      reportedFailures.add(query.queryHash);
      const detail = isNetworkFailure(error)
        ? 'the server could not be reached.'
        : error instanceof Error ? error.message : 'Unknown error';
      toastSink?.(`Could not load data: ${detail}`, 'error');
    },
    onSuccess: (_data, query) => {
      reportedFailures.delete(query.queryHash);
    },
  }),
  mutationCache: new MutationCache({
    // Runs before every mutation. Offline, fail it at once with a sentence the
    // screen shows through its own onError (time clock, leave requests and the
    // rest all toast err.message). React Query's default was to pause the
    // mutation and replay it whenever the network came back — a clock-in
    // recorded at the wrong time, or a leave request the employee thought had
    // gone through, with nothing on screen to say either way.
    onMutate: () => {
      if (isOffline()) throw new Error(OFFLINE_MUTATION_MESSAGE);
    },
    onError: (error, _vars, _ctx, mutation) => {
      // navigator.onLine can say "online" on a dead connection; the request
      // then fails at the network layer. Give it the same readable message.
      if (isNetworkFailure(error)) {
        (error as Error).message = OFFLINE_MUTATION_MESSAGE;
      }
      // A mutation with no error handler of its own would otherwise fail
      // silently.
      if (!mutation.options.onError && (error as Error).message === OFFLINE_MUTATION_MESSAGE) {
        toastSink?.(OFFLINE_MUTATION_MESSAGE, 'error');
      }
    },
  }),
  defaultOptions: {
    queries: {
      staleTime: 60000,
      refetchOnWindowFocus: false,
      // Try the request even when the browser reports no network, so the
      // service worker can answer from the signed-in user's offline copy (My
      // Schedule, own leave). The default ('online') paused every query and
      // left an offline screen spinning forever.
      networkMode: 'offlineFirst',
    },
    mutations: {
      // Always attempt (and so fail visibly) instead of queueing; see onMutate.
      networkMode: 'always',
    },
  },
});

export function Providers({ children }: { children: React.ReactNode }) {
  // Held in state so React's strict-mode double render does not build a second
  // client and orphan the first one's cache.
  const [client] = useState(() => queryClient);

  return (
    <QueryClientProvider client={client}>
      <AuthProvider>
        <PermissionsProvider>
          <ToastProvider>
            <QueryErrorToasts />
            {/* Previously written, exported, and imported by nothing: a
                render-time throw white-screened the whole app. */}
            <ErrorBoundary>
              <MaintenanceGuard>
                {children}
              </MaintenanceGuard>
            </ErrorBoundary>
          </ToastProvider>
        </PermissionsProvider>
      </AuthProvider>
    </QueryClientProvider>
  );
}
