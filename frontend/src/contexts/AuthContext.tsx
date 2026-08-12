'use client';

import React, { createContext, useContext, useEffect, useState, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { User, LoginCredentials } from '@/types';
import { api } from '@/lib/api';
import { clearApiCache } from '@/components/PWARegistrar';

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

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const router = useRouter();

  const isAuthenticated = !!user;

  const refreshUser = useCallback(async () => {
    try {
      const userData = await api.getCurrentUser();
      setUser(userData);
    } catch {
      setUser(null);
    }
  }, []);

  // Session cookies are httpOnly, so the client cannot inspect them to decide
  // whether it is logged in. Ask the server instead: /auth/me either returns
  // the user or 401s, and the cookie is sent automatically.
  useEffect(() => {
    refreshUser().finally(() => setIsLoading(false));
  }, [refreshUser]);

  // When a refresh attempt fails the session is unrecoverable; drop local state
  // and send the user to the login screen rather than leaving a broken shell.
  // Exception: on public pages (landing, login, signup, activate) a 401 is the
  // NORMAL state for a logged-out visitor — the initial /auth/me probe 401s —
  // so we must not bounce them off the public marketing/auth pages.
  useEffect(() => {
    const PUBLIC_PREFIXES = ['/auth/login', '/auth/signup', '/auth/activate'];
    api.setSessionExpiredHandler(() => {
      setUser(null);
      const path = window.location.pathname;
      const onPublic = path === '/' || PUBLIC_PREFIXES.some((p) => path === p || path.startsWith(`${p}/`));
      if (!onPublic) {
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
    clearApiCache();
    setUser(response.user);
    return { requires2FA: false };
  };

  const verify2FA = async (code: string) => {
    const response = await api.verify2FA(code);
    clearApiCache();
    setUser(response.user);
  };

  const logout = async () => {
    await api.logout();
    clearApiCache();
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
