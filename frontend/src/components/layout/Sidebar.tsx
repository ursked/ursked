'use client';

import React from 'react';
import Link from 'next/link';
import Image from 'next/image';
import { usePathname } from 'next/navigation';
import { useAuth } from '@/contexts/AuthContext';
import { useSidebar } from '@/contexts/SidebarContext';
import { RoleCode } from '@/types';
import { hasAnyRole, getPrimaryRole } from '@/lib/roles';

interface NavItem {
  name: string;
  href: string;
  icon: React.ReactNode;
  roles: RoleCode[];
}

const navItems: NavItem[] = [
  {
    name: 'Dashboard',
    href: '/dashboard',
    icon: (
      <svg className="w-5 h-5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" />
      </svg>
    ),
    roles: ['employee', 'tenant_admin', 'hr', 'manager', 'leave_approver', 'schedule_editor', 'finance'],
  },
  {
    name: 'Employees',
    href: '/employees',
    icon: (
      <svg className="w-5 h-5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z" />
      </svg>
    ),
    roles: ['tenant_admin', 'hr', 'manager'],
  },
  {
    name: 'Schedules',
    href: '/schedules',
    icon: (
      <svg className="w-5 h-5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
      </svg>
    ),
    roles: ['employee', 'tenant_admin', 'hr', 'manager', 'schedule_editor'],
  },
  {
    name: 'Leave',
    href: '/leaves',
    icon: (
      <svg className="w-5 h-5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01" />
      </svg>
    ),
    roles: ['employee', 'tenant_admin', 'hr', 'manager', 'leave_approver'],
  },
  {
    name: 'My Payslips',
    href: '/my/payslips',
    icon: (
      <svg className="w-5 h-5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 14h6m-6-4h6m2 10H7a2 2 0 01-2-2V4a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V18a2 2 0 01-2 2z" />
      </svg>
    ),
    roles: ['employee', 'tenant_admin', 'hr', 'manager', 'leave_approver', 'schedule_editor', 'finance'],
  },
  {
    name: 'Attendance',
    href: '/attendance',
    icon: (
      <svg className="w-5 h-5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
      </svg>
    ),
    roles: ['tenant_admin', 'hr', 'manager', 'schedule_editor', 'leave_approver'],
  },
  {
    name: 'Analytics',
    href: '/analytics',
    icon: (
      <svg className="w-5 h-5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
      </svg>
    ),
    roles: ['tenant_admin', 'hr', 'manager'],
  },
  {
    name: 'Organization',
    href: '/organization',
    icon: (
      <svg className="w-5 h-5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
      </svg>
    ),
    roles: ['tenant_admin', 'hr'],
  },
  {
    name: 'Finances',
    href: '/finances',
    icon: (
      <svg className="w-5 h-5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    ),
    roles: ['tenant_admin', 'finance'],
  },
  {
    name: 'Policies',
    href: '/policies',
    icon: (
      <svg className="w-5 h-5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h3.75M9 15h3.75M9 18h3.75m3 .75H18a2.25 2.25 0 002.25-2.25V6.108c0-1.135-.845-2.098-1.976-2.192a48.424 48.424 0 00-1.123-.08m-5.801 0c-.065.21-.1.433-.1.664 0 .414.336.75.75.75h4.5a.75.75 0 00.75-.75 2.25 2.25 0 00-.1-.664m-5.8 0A2.251 2.251 0 0113.5 2.25H15c1.012 0 1.867.668 2.15 1.586m-5.8 0c-.376.023-.75.05-1.124.08C9.095 4.01 8.25 4.973 8.25 6.108V8.25m0 0H4.875c-.621 0-1.125.504-1.125 1.125v11.25c0 .621.504 1.125 1.125 1.125h9.75c.621 0 1.125-.504 1.125-1.125V9.375c0-.621-.504-1.125-1.125-1.125H8.25zM6.75 12h.008v.008H6.75V12zm0 3h.008v.008H6.75V15zm0 3h.008v.008H6.75V18z" />
      </svg>
    ),
    roles: ['tenant_admin'],
  },
  {
    name: 'Data Management',
    href: '/data-management',
    icon: (
      <svg className="w-5 h-5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20.25 6.375c0 2.278-3.694 4.125-8.25 4.125S3.75 8.653 3.75 6.375m16.5 0c0-2.278-3.694-4.125-8.25-4.125S3.75 4.097 3.75 6.375m16.5 0v11.25c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125V6.375m16.5 0v3.75m-16.5-3.75v3.75m16.5 0v3.75C20.25 16.153 16.556 18 12 18s-8.25-1.847-8.25-4.125v-3.75m16.5 0c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125" />
      </svg>
    ),
    roles: ['tenant_admin'],
  },
  {
    name: 'Settings',
    href: '/settings',
    icon: (
      <svg className="w-5 h-5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
      </svg>
    ),
    roles: ['employee', 'tenant_admin', 'hr', 'manager', 'leave_approver', 'schedule_editor', 'finance'],
  },
];

export function Sidebar() {
  const pathname = usePathname();
  const { user } = useAuth();
  const { close, isCollapsed, toggleCollapse } = useSidebar();

  const filteredItems = navItems.filter(
    (item) => user && hasAnyRole(user, item.roles)
  );

  // `isCollapsed` is a DESKTOP-only preference (persisted). The mobile drawer is
  // always full-width (w-64), so collapse styling must never hide labels there.
  // We express "collapsed" only at the `lg:` breakpoint so mobile always shows
  // full labels/padding regardless of the saved desktop preference.
  // labelCls: show a label on mobile always; hide on desktop only when collapsed.
  const labelCls = isCollapsed ? 'inline lg:hidden' : 'inline';
  // blockLabelCls: same idea for block-level (div) content.
  const blockLabelCls = isCollapsed ? 'lg:hidden' : '';
  // rowJustify: normal gap on mobile; center icons on desktop only when collapsed.
  const rowJustify = isCollapsed ? 'gap-3 lg:justify-center lg:gap-0' : 'gap-3';

  return (
    <div className="flex flex-col h-full bg-gray-900 text-white overflow-hidden">
      {/* Logo */}
      <div className={`flex items-center justify-between h-16 border-b border-gray-800 ${isCollapsed ? 'px-6 lg:px-3' : 'px-6'}`}>
        <Link href="/dashboard" className={`flex items-center ${isCollapsed ? 'lg:justify-center lg:w-full' : ''}`}>
          {/* The wordmark's darker half would disappear on the dark sidebar, so
              it sits on a small white chip. Collapsed rail shows just the icon. */}
          <span className="inline-flex items-center rounded-md bg-white px-2 py-1">
            <Image
              src="/logo/urskedlogo.png"
              alt="ursked"
              width={1311}
              height={359}
              priority
              className={`h-6 w-auto ${isCollapsed ? 'lg:hidden' : ''}`}
            />
            {isCollapsed && (
              <Image
                src="/logo/urskedicon.png"
                alt="ursked"
                width={350}
                height={358}
                className="hidden h-6 w-auto lg:block"
              />
            )}
          </span>
        </Link>
        {/* Close button for mobile */}
        <button
          onClick={close}
          className="lg:hidden text-gray-400 hover:text-white"
        >
          <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
        {filteredItems.map((item) => {
          const isActive = pathname === item.href || pathname.startsWith(item.href + '/');
          return (
            <Link
              key={item.href}
              href={item.href}
              onClick={close}
              title={isCollapsed ? item.name : undefined}
              className={`flex items-center ${rowJustify} px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                isActive
                  ? 'bg-gray-700 text-white'
                  : 'text-gray-300 hover:bg-gray-800 hover:text-white'
              }`}
            >
              {item.icon}
              <span className={`whitespace-nowrap ${labelCls}`}>{item.name}</span>
            </Link>
          );
        })}

      </nav>

      {/* Collapse toggle - desktop only */}
      <div className="hidden lg:flex items-center justify-center px-3 py-2 border-t border-gray-800">
        <button
          onClick={toggleCollapse}
          className="flex items-center justify-center w-full py-1.5 rounded-lg text-gray-400 hover:text-white hover:bg-gray-800 transition-colors"
          title={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          <svg
            className={`w-4 h-4 transition-transform duration-300 ${isCollapsed ? 'rotate-180' : ''}`}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 19l-7-7 7-7m8 14l-7-7 7-7" />
          </svg>
        </button>
      </div>

      {/* User info at bottom */}
      {user && (
        <div className={`p-4 border-t border-gray-800 ${isCollapsed ? 'lg:flex lg:justify-center' : ''}`}>
          <div className={`flex items-center ${rowJustify}`}>
            <div className="w-8 h-8 rounded-full bg-purple-600 flex items-center justify-center text-sm font-medium flex-shrink-0">
              {user.first_name[0]}
              {user.last_name[0]}
            </div>
            <div className={`flex-1 min-w-0 ${blockLabelCls}`}>
              <p className="text-sm font-medium text-white truncate">
                {user.first_name} {user.last_name}
              </p>
              <p className="text-xs text-gray-400 truncate capitalize">{getPrimaryRole(user)}</p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
