'use client';

import React, { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { api } from '@/lib/api';

interface SidebarContextType {
  isOpen: boolean;
  toggle: () => void;
  close: () => void;
  isCollapsed: boolean;
  toggleCollapse: () => void;
}

const SidebarContext = createContext<SidebarContextType | undefined>(undefined);

export function SidebarProvider({ children }: { children: React.ReactNode }) {
  const [isOpen, setIsOpen] = useState(false);
  const [isCollapsed, setIsCollapsed] = useState(() => {
    if (typeof window !== 'undefined') {
      return localStorage.getItem('sidebar_collapsed') === 'true';
    }
    return false;
  });

  const toggle = () => setIsOpen((prev) => !prev);
  const close = () => setIsOpen(false);

  // Sync with API on mount
  useEffect(() => {
    api.getUserPreferences().then((prefs) => {
      const collapsed = prefs?.preferences?.sidebar_collapsed === true;
      setIsCollapsed(collapsed);
      localStorage.setItem('sidebar_collapsed', String(collapsed));
    }).catch(() => {});
  }, []);

  const toggleCollapse = useCallback(() => {
    setIsCollapsed((prev) => {
      const next = !prev;
      localStorage.setItem('sidebar_collapsed', String(next));
      api.updateUserPreferences({ sidebar_collapsed: next }).catch(() => {});
      return next;
    });
  }, []);

  return (
    <SidebarContext.Provider value={{ isOpen, toggle, close, isCollapsed, toggleCollapse }}>
      {children}
    </SidebarContext.Provider>
  );
}

export function useSidebar() {
  const context = useContext(SidebarContext);
  if (context === undefined) {
    throw new Error('useSidebar must be used within a SidebarProvider');
  }
  return context;
}
