'use client';

import { useEffect } from 'react';
import { usePathname } from 'next/navigation';
import { APP_NAME } from '@/lib/brand';

// Screen names for the browser tab, the task switcher and the installed app's
// window list. Every screen used to be titled the same long marketing line.
// Longest prefix wins, so /policies/leave falls back to "Policies".
const TITLES: [string, string][] = [
  ['/dashboard', 'Dashboard'],
  ['/my/schedule', 'My Schedule'],
  ['/my/leave', 'My Leave'],
  ['/my/timeclock', 'Time Clock'],
  ['/my/payslips', 'My Payslips'],
  ['/schedules', 'Schedules'],
  ['/leaves', 'Leave'],
  ['/employees', 'Employees'],
  ['/attendance', 'Attendance'],
  ['/analytics', 'Analytics'],
  ['/organization', 'Organization'],
  ['/finances', 'Finances'],
  ['/policies', 'Policies'],
  ['/data-management', 'Reports & Data'],
  ['/salary-access', 'Salary access'],
  ['/audit-log', 'Audit Log'],
  ['/plugins', 'Plugins'],
  ['/settings', 'Settings'],
  ['/profile', 'Profile'],
  ['/superadmin', 'Platform'],
  ['/auth/login', 'Sign in'],
  ['/admin/login', 'Administrator sign-in'],
  ['/finance/login', 'Finance sign-in'],
  ['/auth/forgot-password', 'Forgot password'],
  ['/auth/reset-password', 'Reset password'],
  ['/auth/activate', 'Activate your account'],
  ['/auth/signup', 'Sign up'],
];

export function titleFor(pathname: string): string | null {
  let best: [string, string] | null = null;
  for (const entry of TITLES) {
    const [prefix] = entry;
    if (pathname === prefix || pathname.startsWith(`${prefix}/`)) {
      if (!best || prefix.length > best[0].length) best = entry;
    }
  }
  return best ? best[1] : null;
}

// Titles this component has written, so a screen that sets its own title
// through Next metadata (it would differ from all of these) is left alone.
const written = new Set<string>([APP_NAME, '']);

// Admin and finance sessions mark every tab ("Admin · Employees · ursked",
// "Finance · Finances · ursked"), so such a tab is told apart from an
// employee one at a glance in the tab strip and the task switcher. Set by the
// session's bar (PortalBar); this component sits outside the auth providers,
// so the marker comes in through here.
let marker: string | null = null;
const MARKER_EVENT = 'routetitle:marker';

export function setTitleMarker(value: string | null) {
  marker = value;
  if (typeof window !== 'undefined') window.dispatchEvent(new Event(MARKER_EVENT));
}

/** Sets document.title from the route. Every screen is a client component, and
 * Next metadata can only be exported from server files, so the name is kept
 * here in one table rather than as a layout file in every route folder. */
export function RouteTitle() {
  const pathname = usePathname();

  useEffect(() => {
    const screen = titleFor(pathname ?? '/');
    const wanted = () => {
      const base = screen ? `${screen} · ${APP_NAME}` : APP_NAME;
      const title = marker ? `${marker} · ${base}` : base;
      written.add(title);
      return title;
    };
    const apply = () => {
      // Only over the default or a title this component wrote; never over a
      // title a screen set for itself.
      const title = wanted();
      if (document.title !== title && written.has(document.title)) document.title = title;
    };
    apply();
    // Next re-renders the metadata <title> ("ursked") after hydration, which
    // put the default straight back; re-apply whenever the title changes.
    const observer = new MutationObserver(apply);
    observer.observe(document.head, { subtree: true, childList: true, characterData: true });
    window.addEventListener(MARKER_EVENT, apply);
    return () => {
      observer.disconnect();
      window.removeEventListener(MARKER_EVENT, apply);
    };
  }, [pathname]);

  return null;
}
