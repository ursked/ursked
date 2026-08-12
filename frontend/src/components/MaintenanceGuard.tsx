'use client';

import { useEffect, useState } from 'react';
import { usePathname } from 'next/navigation';
import { useAuth } from '@/contexts/AuthContext';
import { api } from '@/lib/api';
import MaintenancePage from './MaintenancePage';

// Paths that should always be accessible (superadmin needs to toggle maintenance off)
const EXEMPT_PATHS = ['/superadmin', '/auth/login'];

export default function MaintenanceGuard({ children }: { children: React.ReactNode }) {
  const { user, isLoading } = useAuth();
  const pathname = usePathname();
  const [maintenance, setMaintenance] = useState(false);
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api.getSiteStatus()
      .then((status) => {
        if (!cancelled) {
          setMaintenance(status.maintenance_mode);
          setChecked(true);
        }
      })
      .catch(() => {
        if (!cancelled) setChecked(true);
      });
    return () => { cancelled = true; };
  }, []);

  // Still loading auth or site status
  if (!checked || isLoading) return null;

  // Superadmin users can always access the app
  const isSuperadmin = user?.is_superadmin === true;

  // Exempt paths (login page, superadmin page)
  const isExempt = EXEMPT_PATHS.some((p) => pathname.startsWith(p));

  if (maintenance && !isSuperadmin && !isExempt) {
    return <MaintenancePage />;
  }

  return <>{children}</>;
}
