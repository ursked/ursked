'use client';

import React, { useEffect, useState } from 'react';
import { QueryClient, QueryClientProvider, QueryCache } from '@tanstack/react-query';
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
 * 401 and 403 are excluded on purpose. A 401 is the ordinary pre-auth probe on
 * every page load, and a 403 is the permissions system working — the UI already
 * hides what the role cannot see, and surfacing those would train people to
 * dismiss the toast without reading it.
 */
const queryClient = new QueryClient({
  queryCache: new QueryCache({
    onError: (error) => {
      const status = error instanceof ApiError ? error.status : 0;
      if (status === 401 || status === 403) return;
      const detail = error instanceof Error ? error.message : 'Unknown error';
      toastSink?.(`Could not load data: ${detail}`, 'error');
    },
  }),
  defaultOptions: {
    queries: {
      staleTime: 60000,
      refetchOnWindowFocus: false,
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
