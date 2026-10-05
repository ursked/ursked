'use client';

import React, { useState, useRef, useEffect } from 'react';
import Link from 'next/link';
import { useAuth } from '@/contexts/AuthContext';
import { useSidebar } from '@/contexts/SidebarContext';
import { hasAnyRole } from '@/lib/roles';
import {
  ADMIN_LOGIN_PATH,
  FINANCE_LOGIN_PATH,
  hasEmployeeWorkspace,
  isAdminEligible,
  isAdminSession,
  isFinanceEligible,
  isFinanceSession,
} from '@/lib/workspace';
import { useInstallPrompt } from '@/hooks/useInstallPrompt';
import { useToast } from '@/components/ui/Toast';
import { NotificationsBell } from './NotificationsBell';

export function Header() {
  const { user, logout, exitAdmin, exitFinance } = useAuth();
  const adminSession = isAdminSession(user);
  const financeSession = isFinanceSession(user);
  const privilegedSession = adminSession || financeSession;
  const { toggle } = useSidebar();
  const { showToast } = useToast();
  const { canInstall, installed, isIOS, promptInstall } = useInstallPrompt();
  // Chrome/Edge/Android hand over a prompt; Safari on iPhone never does, so
  // there the entry explains the two taps instead.
  const showInstall = canInstall || (isIOS && !installed);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setDropdownOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  return (
    // viewport-fit=cover lets the page run under a notch / status bar; the
    // header grows by the top inset (0 where there is none) so the menu and
    // account buttons stay tappable.
    // In an admin or finance session its bar sits above and takes the top inset.
    <header className={`${privilegedSession ? 'h-16' : 'h-[calc(4rem+env(safe-area-inset-top))] pt-[env(safe-area-inset-top)]'} flex-shrink-0 bg-white border-b border-gray-200 flex items-center justify-between px-6 pl-[calc(1.5rem+env(safe-area-inset-left))] lg:pl-6`}>
      {/* Left: mobile menu button */}
      <button
        onClick={toggle}
        className="lg:hidden inline-flex items-center justify-center min-h-[44px] min-w-[44px] -ml-2 text-gray-600 hover:text-gray-900"
        aria-label="Open the navigation menu"
      >
        <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
        </svg>
      </button>

      <div className="lg:flex-1" />

      {/* Right: notifications + user dropdown */}
      <div className="flex items-center gap-4">
        {/* Notification bell */}
        <NotificationsBell />

        {/* User dropdown */}
        <div className="relative" ref={dropdownRef}>
          <button
            onClick={() => setDropdownOpen(!dropdownOpen)}
            className="flex items-center gap-2 min-h-[44px] hover:bg-gray-50 rounded-lg px-2 py-1.5 transition-colors"
            aria-label="Account menu"
            aria-expanded={dropdownOpen}
          >
            <div className="w-8 h-8 rounded-full bg-brand-600 flex items-center justify-center text-white text-sm font-medium">
              {user?.first_name?.[0]}
              {user?.last_name?.[0]}
            </div>
            <svg className="w-4 h-4 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </button>

          {dropdownOpen && (
            <div className="absolute right-0 mt-2 w-56 bg-white rounded-lg shadow-lg border border-gray-200 py-1 z-50">
              <div className="px-4 py-3 border-b border-gray-100">
                <p className="text-sm font-medium text-gray-900">
                  {user?.first_name} {user?.last_name}
                </p>
                <p className="text-xs text-gray-500 truncate">{user?.email}</p>
              </div>
              <Link
                href="/profile"
                onClick={() => setDropdownOpen(false)}
                className="flex items-center gap-2 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                </svg>
                Profile
              </Link>
              {/* Admin mode: the way between the two dashboards. Up is always
                  the administrator sign-in, which asks for the password; down
                  from an admin session needs no password. */}
              {user && isAdminEligible(user) && !adminSession && (
                <Link
                  href={ADMIN_LOGIN_PATH}
                  onClick={() => setDropdownOpen(false)}
                  className="flex items-center gap-2 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
                >
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
                  </svg>
                  Administrator sign-in
                </Link>
              )}
              {/* The finance dashboard works the same way: up through the
                  finance sign-in, down without a password. */}
              {user && isFinanceEligible(user) && !financeSession && (
                <Link
                  href={FINANCE_LOGIN_PATH}
                  onClick={() => setDropdownOpen(false)}
                  className="flex items-center gap-2 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
                >
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  Finance sign-in
                </Link>
              )}
              {user && privilegedSession && hasEmployeeWorkspace(user) && (
                <button
                  type="button"
                  onClick={() => {
                    setDropdownOpen(false);
                    void (adminSession ? exitAdmin() : exitFinance());
                  }}
                  className="flex items-center gap-2 w-full px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
                >
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" />
                  </svg>
                  Go to my employee dashboard
                </button>
              )}
              {user && hasAnyRole(user, ['tenant_admin']) && (
                <Link
                  href="/settings"
                  onClick={() => setDropdownOpen(false)}
                  className="flex items-center gap-2 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
                >
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                  </svg>
                  Settings
                </Link>
              )}
              {showInstall && (
                <button
                  type="button"
                  onClick={async () => {
                    setDropdownOpen(false);
                    if (canInstall) {
                      await promptInstall();
                    } else {
                      showToast('On iPhone or iPad: tap Share, then "Add to Home Screen".', 'info', 8000);
                    }
                  }}
                  className="flex items-center gap-2 w-full px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
                >
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v12m0 0l-4-4m4 4l4-4M5 20h14" />
                  </svg>
                  Install the app
                </button>
              )}
              <div className="border-t border-gray-100 mt-1">
                <button
                  onClick={() => {
                    setDropdownOpen(false);
                    logout();
                  }}
                  className="flex items-center gap-2 w-full px-4 py-2 text-sm text-red-600 hover:bg-red-50"
                >
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
                  </svg>
                  Sign out
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
