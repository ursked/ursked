'use client';

import React, { createContext, useContext, useEffect, useRef, useState, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { useQueryClient } from '@tanstack/react-query';
import { User, LoginCredentials } from '@/types';
import { api } from '@/lib/api';
import { clearApiCache, keepApiCacheFor } from '@/components/PWARegistrar';
import { isPublicPath } from '@/lib/publicRoutes';
import { Workspace, signInPathFor, workspaceOf } from '@/lib/workspace';

interface AuthContextType {
  user: User | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  /** `portal` picks the door: 'employee' is the ordinary sign-in page,
   * 'admin' the administrator sign-in page, 'finance' the finance one. */
  login: (credentials: LoginCredentials, portal?: Workspace) => Promise<{ requires2FA: boolean }>;
  verify2FA: (code: string) => Promise<void>;
  logout: () => Promise<void>;
  /** End the admin session and continue in the employee dashboard. */
  exitAdmin: () => Promise<void>;
  /** End the finance session and continue in the employee dashboard. */
  exitFinance: () => Promise<void>;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

/** The readable half of the session: the server sets the CSRF cookie with the
 * refresh token's lifetime and deletes it on sign-out (the auth cookies
 * themselves are httpOnly). No cookie means no session on this device. */
function hasSessionMarker(): boolean {
  return typeof document !== 'undefined' && /(?:^|;\s*)csrf_token=/.test(document.cookie);
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const router = useRouter();
  const queryClient = useQueryClient();
  // Which door the current session came through, for handlers registered
  // once (the session-expiry handler) that must not read a stale `user`.
  const workspaceRef = useRef<Workspace>('employee');

  const isAuthenticated = !!user;

  // Whoever is signed in is the only person whose offline copy may exist on
  // this device (see PWARegistrar / sw.js).
  const signedIn = useCallback((u: User | null) => {
    if (u) {
      void keepApiCacheFor(u.id);
      workspaceRef.current = workspaceOf(u);
    }
    setUser(u);
  }, []);

  // A new session (another door, or another person) must not be shown the
  // previous one's answers: the admin dashboard's company figures and the
  // employee dashboard's personal ones share query keys.
  const startFresh = useCallback(async () => {
    queryClient.clear();
    await clearApiCache();
  }, [queryClient]);

  const refreshUser = useCallback(async () => {
    try {
      const userData = await api.getCurrentUser();
      signedIn(userData);
    } catch {
      setUser(null);
    }
  }, [signedIn]);

  // Session cookies are httpOnly, so the client cannot inspect them to decide
  // whether it is logged in. Ask the server instead: /auth/me either returns
  // the user or 401s, and the cookie is sent automatically.
  //
  // Before asking: with no session on this device, nobody's offline copy may
  // survive. Otherwise a session that expired while the app was closed would
  // leave the last user's schedule answering /auth/me the next time the app
  // opened offline, for whoever picked the phone up.
  useEffect(() => {
    let active = true;
    // Defer so the loading-state update does not run synchronously inside the
    // effect body (react-hooks/set-state-in-effect).
    void Promise.resolve().then(async () => {
      if (!active) return;
      if (!hasSessionMarker()) await clearApiCache();
      if (!active) return;
      refreshUser().finally(() => {
        if (active) setIsLoading(false);
      });
    });
    return () => {
      active = false;
    };
  }, [refreshUser]);

  // When a refresh attempt fails the session is unrecoverable; drop local state
  // and send the user to the login screen rather than leaving a broken shell.
  // Exception: on public pages (landing, login, password reset, activate) a 401
  // is the NORMAL state for a logged-out visitor — the initial /auth/me probe
  // 401s — so we must not bounce them off those pages.
  //
  // An admin or finance session goes back to its own sign-in page, saying
  // why: both end on their own after 30 idle minutes or 8 hours. The server
  // names the one that ended (X-Session-Ended); the door this tab came
  // through answers when it does not.
  //
  // Either way the expired session's cached data goes with it.
  useEffect(() => {
    api.setSessionExpiredHandler((endedPortal) => {
      const ended: Workspace =
        endedPortal === 'admin' || endedPortal === 'finance' ? endedPortal : workspaceRef.current;
      workspaceRef.current = 'employee';
      queryClient.clear();
      void clearApiCache();
      setUser(null);
      if (!isPublicPath(window.location.pathname)) {
        router.replace(ended === 'employee' ? signInPathFor('employee') : `${signInPathFor(ended)}?ended=1`);
      }
    });
    return () => api.setSessionExpiredHandler(null);
  }, [router, queryClient]);

  const login = async (credentials: LoginCredentials, portal: Workspace = 'employee') => {
    const response =
      portal === 'admin'
        ? await api.adminLogin(credentials)
        : portal === 'finance'
          ? await api.financeLogin(credentials)
          : await api.login(credentials);
    if (response.requires_2fa) {
      return { requires2FA: true };
    }
    // Purge any cached API data from a previous session before showing this one.
    await startFresh();
    signedIn(response.user);
    return { requires2FA: false };
  };

  const verify2FA = async (code: string) => {
    const response = await api.verify2FA(code);
    await startFresh();
    signedIn(response.user);
  };

  const exitAdmin = async () => {
    const response = await api.exitAdminSession();
    await startFresh();
    signedIn(response.user);
    router.replace('/dashboard');
  };

  const exitFinance = async () => {
    const response = await api.exitFinanceSession();
    await startFresh();
    signedIn(response.user);
    router.replace('/dashboard');
  };

  const logout = async () => {
    const workspace = workspaceRef.current;
    await api.logout();
    // Awaited: the next person must not be able to open this person's offline
    // copy, and navigating away first could cut the deletion short.
    await startFresh();
    workspaceRef.current = 'employee';
    setUser(null);
    router.replace(signInPathFor(workspace));
  };

  return (
    <AuthContext.Provider
      value={{ user, isLoading, isAuthenticated, login, verify2FA, logout, exitAdmin, exitFinance, refreshUser }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
