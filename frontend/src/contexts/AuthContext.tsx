'use client';

import React, { createContext, useContext, useEffect, useState, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { User, LoginCredentials } from '@/types';
import { api } from '@/lib/api';
import { clearApiCache, keepApiCacheFor } from '@/components/PWARegistrar';
import { isPublicPath } from '@/lib/publicRoutes';

interface AuthContextType {
  user: User | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  login: (credentials: LoginCredentials) => Promise<{ requires2FA: boolean }>;
  verify2FA: (code: string) => Promise<void>;
  logout: () => Promise<void>;
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

  const isAuthenticated = !!user;

  // Whoever is signed in is the only person whose offline copy may exist on
  // this device (see PWARegistrar / sw.js).
  const signedIn = useCallback((u: User | null) => {
    if (u) void keepApiCacheFor(u.id);
    setUser(u);
  }, []);

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
  // Either way the expired session's cached data goes with it.
  useEffect(() => {
    api.setSessionExpiredHandler(() => {
      void clearApiCache();
      setUser(null);
      if (!isPublicPath(window.location.pathname)) {
        router.replace('/auth/login');
      }
    });
    return () => api.setSessionExpiredHandler(null);
  }, [router]);

  const login = async (credentials: LoginCredentials) => {
    const response = await api.login(credentials);
    if (response.requires_2fa) {
      return { requires2FA: true };
    }
    // Purge any cached API data from a previous session before showing this one.
    await clearApiCache();
    signedIn(response.user);
    return { requires2FA: false };
  };

  const verify2FA = async (code: string) => {
    const response = await api.verify2FA(code);
    await clearApiCache();
    signedIn(response.user);
  };

  const logout = async () => {
    await api.logout();
    // Awaited: the next person must not be able to open this person's offline
    // copy, and navigating away first could cut the deletion short.
    await clearApiCache();
    setUser(null);
    router.replace('/auth/login');
  };

  return (
    <AuthContext.Provider
      value={{ user, isLoading, isAuthenticated, login, verify2FA, logout, refreshUser }}
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
