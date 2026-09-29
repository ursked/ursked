'use client';

import PortalSignIn from '@/components/auth/PortalSignIn';

// Admin mode: the administrator door. The ordinary sign-in page always opens
// an employee session, administrators included; this page is the only way
// into the admin dashboard. Shared with the finance door (PortalSignIn).
export default function AdminLoginPage() {
  return <PortalSignIn portal="admin" />;
}
