'use client';

import PortalSignIn from '@/components/auth/PortalSignIn';

// The finance door. The finance role is dormant in the employee session
// (the ordinary sign-in), so this page is the only way into the finance
// dashboard, where Finances works. It asks for the password (and the second
// factor) every time, like the administrator sign-in.
export default function FinanceLoginPage() {
  return <PortalSignIn portal="finance" />;
}
