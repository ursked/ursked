'use client';

import React, { useEffect } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useAuth } from '@/contexts/AuthContext';
import { usePermissions } from '@/contexts/PermissionsContext';
import { SidebarProvider, useSidebar } from '@/contexts/SidebarContext';
import { Sidebar, inWorkspace, navItemFor } from './Sidebar';
import { Header } from './Header';
import { AdminBar } from './AdminBar';
import { ForcePasswordChange } from '@/components/auth/ForcePasswordChange';
import {
  ADMIN_LOGIN_PATH,
  hasEmployeeWorkspace,
  isAdminEligible,
  workspaceOf,
} from '@/lib/workspace';

function DashboardContent({ children, adminSession }: { children: React.ReactNode; adminSession: boolean }) {
  const { isOpen, close, isCollapsed } = useSidebar();

  // h-app is 100dvh with a 100vh fallback (globals.css): 100vh is the height
  // with the mobile browser's toolbars hidden, so the bottom of every page sat
  // under the toolbar until the user scrolled. The right inset keeps content
  // clear of a landscape notch; on desktop the sidebar takes the left one, on
  // a phone (sidebar off-canvas) <main> does.
  return (
    <div className="flex flex-col h-app bg-gray-50 pr-[env(safe-area-inset-right)]">
      {/* Admin mode: the bar spans the whole window, above sidebar and header,
          so no admin screen can be mistaken for an employee one. */}
      {adminSession && <AdminBar />}
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

  // Admin mode routing. The server refuses regardless; this only keeps people
  // from landing on a screen of 403s, and says where the screen lives:
  //   * in an employee session, an administrator opening a screen that only
  //     their admin role would allow goes to their dashboard, which offers
  //     the administrator sign-in;
  //   * in an admin session, the admin's own schedule, leave, time clock and
  //     payslips are in their employee dashboard, and the admin dashboard
  //     says so.
  // Users without the administrator role are not redirected: what they cannot
  // open is decided by the screens, as before.
  let redirectTo: string | null = null;
  if (user && navItem && navItem.href !== '/dashboard' && !permissionsLoading && !user.must_change_password) {
    if (workspace === 'employee' && isAdminEligible(user)) {
      const allowed =
        inWorkspace(navItem, 'employee') && navItem.visible({ user, can: hasPermission });
      if (!allowed) redirectTo = `/dashboard?admin=${encodeURIComponent(pathname)}`;
    } else if (workspace === 'admin' && !inWorkspace(navItem, 'admin') && navItem.href !== '/profile') {
      redirectTo = `/dashboard?own=${encodeURIComponent(pathname)}`;
    }
  }

  useEffect(() => {
    if (redirectTo) router.replace(redirectTo);
  }, [redirectTo, router]);

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
      <DashboardContent adminSession={workspace === 'admin'}>
        {pureAdminInEmployeeSession ? <NoEmployeeWorkspace /> : redirectTo ? null : children}
      </DashboardContent>
    </SidebarProvider>
  );
}
