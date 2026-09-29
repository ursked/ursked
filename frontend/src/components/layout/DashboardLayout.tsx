'use client';

import React, { useEffect } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useAuth } from '@/contexts/AuthContext';
import { usePermissions } from '@/contexts/PermissionsContext';
import { SidebarProvider, useSidebar } from '@/contexts/SidebarContext';
import { NavItem, Sidebar, inWorkspace, navItemFor } from './Sidebar';
import { Header } from './Header';
import { PortalBar } from './PortalBar';
import { ForcePasswordChange } from '@/components/auth/ForcePasswordChange';
import { User } from '@/types';
import {
  ADMIN_LOGIN_PATH,
  Workspace,
  hasEmployeeWorkspace,
  isAdminEligible,
  isFinanceEligible,
  workspaceOf,
} from '@/lib/workspace';

function DashboardContent({ children, workspace }: { children: React.ReactNode; workspace: Workspace }) {
  const { isOpen, close, isCollapsed } = useSidebar();

  // h-app is 100dvh with a 100vh fallback (globals.css): 100vh is the height
  // with the mobile browser's toolbars hidden, so the bottom of every page sat
  // under the toolbar until the user scrolled. The right inset keeps content
  // clear of a landscape notch; on desktop the sidebar takes the left one, on
  // a phone (sidebar off-canvas) <main> does.
  return (
    <div className="flex flex-col h-app bg-gray-50 pr-[env(safe-area-inset-right)]">
      {/* Admin and finance sessions: the bar spans the whole window, above
          sidebar and header, so no admin or finance screen can be mistaken
          for an employee one. */}
      {workspace !== 'employee' && <PortalBar portal={workspace} />}
      <div className="flex flex-1 min-h-0">
        {/* Mobile sidebar overlay */}
        {isOpen && (
          <div
            className="fixed inset-0 z-40 bg-black/50 lg:hidden"
            onClick={close}
          />
        )}

        {/* Sidebar */}
        <div
          className={`fixed inset-y-0 left-0 z-50 w-64 transform transition-all duration-300 ease-in-out lg:relative lg:translate-x-0 ${
            isOpen ? 'translate-x-0' : '-translate-x-full'
          } ${isCollapsed ? 'lg:w-16' : 'lg:w-64'}`}
        >
          <Sidebar />
        </div>

        {/* Main content */}
        <div className="flex-1 flex flex-col min-w-0">
          <Header />
          {/* overflow-x-hidden + min-w-0 stop any wide child (tables, tab bars)
              from expanding the page and causing horizontal scroll on mobile.
              Inner containers with their own overflow-x-auto still scroll. */}
          <main className="flex-1 min-w-0 overflow-y-auto overflow-x-hidden p-6 pb-[calc(1.5rem+env(safe-area-inset-bottom))] pl-[calc(1.5rem+env(safe-area-inset-left))] lg:pl-6">
            {children}
          </main>
        </div>
      </div>
    </div>
  );
}

/** A pure administrator account (tenant_admin and nothing else) signed in at
 * the ordinary page: nothing of its own to show, only the way to the admin
 * dashboard. */
function NoEmployeeWorkspace() {
  return (
    <div className="mx-auto max-w-lg rounded-xl border border-gray-200 bg-white p-8 text-center shadow-sm">
      <h1 className="text-xl font-semibold text-gray-900">This account has no employee schedule</h1>
      <p className="mt-2 text-sm text-gray-600">
        It is an administrator account without shifts, leave or payslips of its own. To manage
        the company, use the administrator sign-in.
      </p>
      <Link
        href={ADMIN_LOGIN_PATH}
        className="mt-6 inline-flex min-h-[44px] items-center justify-center rounded-lg bg-gray-900 px-5 py-2.5 text-sm font-semibold text-white hover:bg-gray-800"
      >
        Administrator sign-in
      </Link>
    </div>
  );
}

// Screens a pure administrator account may still open in its employee
// session: its profile (password, two-factor, sessions).
const ALWAYS_OPEN = ['/profile'];

/**
 * Where a screen that does not belong to this session's workspace lives, as
 * the dashboard address that says so (the dashboard reads the query), or null
 * to let the screen judge for itself. The server refuses regardless; this
 * keeps people from landing on a screen of 403s and tells them where the
 * screen is:
 *   * admin session: operational screens (schedules, leave, attendance,
 *     finances, reports, analytics) are done from the regular dashboard by
 *     people with that role (?ops=); the admin's own schedule, leave, time
 *     clock and payslips are in their employee dashboard (?own=).
 *   * finance session: administration is the admin dashboard's (?admin=);
 *     everything else is in the employee dashboard (?own=).
 *   * employee session: Finances is the finance dashboard's (?finance=);
 *     administration is the admin dashboard's, said only to administrators
 *     (?admin=). Other people are not redirected: what they cannot open is
 *     decided by the screens, as before.
 */
function redirectFor(
  workspace: Workspace,
  item: NavItem,
  user: User,
  can: (module: string, action: string) => boolean,
  pathname: string,
): string | null {
  const here = inWorkspace(item, workspace);
  if ((here && item.visible({ user, can })) || item.openAnywhere) return null;
  const q = encodeURIComponent(pathname);
  if (workspace === 'admin') {
    if (here) return null;
    return pathname.startsWith('/my/') ? `/dashboard?own=${q}` : `/dashboard?ops=${q}`;
  }
  if (workspace === 'finance') {
    if (here) return null;
    if (inWorkspace(item, 'admin') && !inWorkspace(item, 'employee')) return `/dashboard?admin=${q}`;
    return `/dashboard?own=${q}`;
  }
  if (!here) {
    if (inWorkspace(item, 'finance') && !inWorkspace(item, 'admin')) return `/dashboard?finance=${q}`;
    return isAdminEligible(user) ? `/dashboard?admin=${q}` : null;
  }
  // In the employee workspace but not for this person's roles here. An
  // administrator has it (Employees, Organization, Policies) in the admin
  // dashboard; someone in Finance may have it (reports, analytics) in theirs.
  if (inWorkspace(item, 'admin') && isAdminEligible(user)) return `/dashboard?admin=${q}`;
  if (inWorkspace(item, 'finance') && isFinanceEligible(user)) return `/dashboard?finance=${q}`;
  return null;
}

/** The old address of the salary-access screen (/finances?tab=salary-access),
 * still in emails already sent. Read from the address bar: only ever
 * consulted once the session is known, on the client. */
function isOldSalaryAccessLink(pathname: string): boolean {
  return (
    pathname === '/finances' &&
    typeof window !== 'undefined' &&
    new URLSearchParams(window.location.search).get('tab') === 'salary-access'
  );
}

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, isLoading, user } = useAuth();
  const { hasPermission, isLoading: permissionsLoading } = usePermissions();
  const router = useRouter();
  const pathname = usePathname() ?? '/';

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.push('/auth/login');
    }
  }, [isLoading, isAuthenticated, router]);

  const workspace = workspaceOf(user);
  const navItem = navItemFor(pathname);

  // Workspace routing (see redirectFor). The dashboard and the profile are in
  // every workspace.
  let redirectTo: string | null = null;
  if (user && !permissionsLoading && !user.must_change_password) {
    if (isOldSalaryAccessLink(pathname)) {
      redirectTo = '/salary-access';
    } else if (navItem && navItem.href !== '/dashboard' && !ALWAYS_OPEN.includes(navItem.href)) {
      redirectTo = redirectFor(workspace, navItem, user, hasPermission, pathname);
    }
  }

  // A full navigation, not router.replace. Pages keep their own state and
  // effects above this layout (it wraps them; it cannot stop them), and some
  // write their filters into the address on mount — the schedule grid adds
  // ?date=&range=&view=. That client navigation superseded router.replace, so
  // an admin session opening /schedules stayed on it. Landing in the wrong
  // workspace is rare (a deep link), so a real page load is a fair price for a
  // redirect nothing can override.
  useEffect(() => {
    if (redirectTo) window.location.replace(redirectTo);
  }, [redirectTo]);

  if (isLoading) {
    return (
      <div className="min-h-app flex items-center justify-center bg-gray-50">
        <div className="text-center">
          <div className="w-12 h-12 border-4 border-purple-200 border-t-purple-600 rounded-full animate-spin mx-auto mb-4" />
          <p className="text-gray-500">Loading...</p>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return null;
  }

  // A signed-in user who must still change their password (a self-hosted first
  // admin, or an admin-forced reset) is held here until they do — no app screen
  // renders behind this gate.
  if (user?.must_change_password) {
    return <ForcePasswordChange />;
  }

  const pureAdminInEmployeeSession =
    workspace === 'employee' && !hasEmployeeWorkspace(user) && !ALWAYS_OPEN.includes(pathname);

  return (
    <SidebarProvider>
      <DashboardContent workspace={workspace}>
        {pureAdminInEmployeeSession ? (
          <NoEmployeeWorkspace />
        ) : redirectTo || permissionsLoading ? (
          // Hold the screen back until we know whether it belongs to this
          // session. Rendering it while permissions load let a page run its
          // own effects first: the schedule grid writes its date and view
          // into the address, and that navigation landed after the redirect,
          // leaving an admin session on the grid instead of the dashboard.
          null
        ) : (
          children
        )}
      </DashboardContent>
    </SidebarProvider>
  );
}
