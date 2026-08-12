'use client';

import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider } from '@/contexts/AuthContext';
import { PermissionsProvider } from '@/contexts/PermissionsContext';
import { ToastProvider } from '@/components/ui/Toast';
import MaintenanceGuard from '@/components/MaintenanceGuard';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60000,
      refetchOnWindowFocus: false,
    },
  },
});

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <PermissionsProvider>
          <ToastProvider>
            <MaintenanceGuard>
              {children}
            </MaintenanceGuard>
          </ToastProvider>
        </PermissionsProvider>
      </AuthProvider>
    </QueryClientProvider>
  );
}
