'use client'

import React, { createContext, useContext, useState, useEffect, useCallback } from 'react'
import { useAuth } from '@/contexts/AuthContext'
import { api } from '@/lib/api'
import { hasRole } from '@/lib/roles'

interface PermissionsContextType {
  permissions: Record<string, Record<string, boolean>>
  extra: Record<string, boolean>
  isLoading: boolean
  hasPermission: (module: string, action: string) => boolean
  hasExtraPermission: (key: string) => boolean
  refreshPermissions: () => Promise<void>
}

const PermissionsContext = createContext<PermissionsContextType>({
  permissions: {},
  extra: {},
  isLoading: true,
  hasPermission: () => false,
  hasExtraPermission: () => false,
  refreshPermissions: async () => {},
})

export function PermissionsProvider({ children }: { children: React.ReactNode }) {
  const { user, isAuthenticated } = useAuth()
  const [permissions, setPermissions] = useState<Record<string, Record<string, boolean>>>({})
  const [extra, setExtra] = useState<Record<string, boolean>>({})
  const [isLoading, setIsLoading] = useState(true)

  const fetchPermissions = useCallback(async () => {
    if (!isAuthenticated || !user) {
      setPermissions({})
      setExtra({})
      setIsLoading(false)
      return
    }

    try {
      const result = await api.getMyPermissions()
      setPermissions(result.permissions)
      setExtra(result.extra)
    } catch {
      setPermissions({})
      setExtra({})
    } finally {
      setIsLoading(false)
    }
  }, [isAuthenticated, user])

  useEffect(() => {
    fetchPermissions()
  }, [fetchPermissions])

  const hasPermission = useCallback(
    (module: string, action: string): boolean => {
      if (!user) return false
      // tenant_admin always has all permissions (client-side shortcut)
      if (hasRole(user, 'tenant_admin')) return true
      return permissions[module]?.[action] === true
    },
    [user, permissions]
  )

  const hasExtraPermission = useCallback(
    (key: string): boolean => {
      if (!user) return false
      if (hasRole(user, 'tenant_admin')) return true
      return extra[key] === true
    },
    [user, extra]
  )

  return (
    <PermissionsContext.Provider
      value={{
        permissions,
        extra,
        isLoading,
        hasPermission,
        hasExtraPermission,
        refreshPermissions: fetchPermissions,
      }}
    >
      {children}
    </PermissionsContext.Provider>
  )
}

export function usePermissions() {
  return useContext(PermissionsContext)
}
