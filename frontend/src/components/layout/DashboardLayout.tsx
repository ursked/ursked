'use client';

import React, { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/contexts/AuthContext';
import { SidebarProvider, useSidebar } from '@/contexts/SidebarContext';
import { Sidebar } from './Sidebar';
import { Header } from './Header';
import { ForcePasswordChange } from '@/components/auth/ForcePasswordChange';

function DashboardContent({ children }: { children: React.ReactNode }) {
  const { isOpen, close, isCollapsed } = useSidebar();

  // h-app is 100dvh with a 100vh fallback (globals.css): 100vh is the height
  // with the mobile browser's toolbars hidden, so the bottom of every page sat
  // under the toolbar until the user scrolled. The right inset keeps content
  // clear of a landscape notch; on desktop the sidebar takes the left one, on
  // a phone (sidebar off-canvas) <main> does.
  return (
    <div className="flex h-app bg-gray-50 pr-[env(safe-area-inset-right)]">
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
  );
}

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, isLoading, user } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.push('/auth/login');
    }
  }, [isLoading, isAuthenticated, router]);

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

  return (
    <SidebarProvider>
      <DashboardContent>{children}</DashboardContent>
    </SidebarProvider>
  );
}
