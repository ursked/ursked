'use client'

import { useEffect } from 'react'

/** Registers the service worker on mount and reloads once when a new SW takes
 * control (so users get shell updates after a deploy). */
export default function PWARegistrar() {
  useEffect(() => {
    if (typeof window === 'undefined' || !('serviceWorker' in navigator)) return

    let refreshing = false
    navigator.serviceWorker.addEventListener('controllerchange', () => {
      if (refreshing) return
      refreshing = true
      window.location.reload()
    })

    navigator.serviceWorker.register('/sw.js').catch(() => {
      /* SW is progressive enhancement; ignore failures. */
    })
  }, [])

  return null
}

/** Purge cached API responses. Call on login and logout so cached personal data
 * (e.g. a schedule) is never served to a different session. */
export function clearApiCache() {
  if (typeof navigator !== 'undefined' && navigator.serviceWorker?.controller) {
    navigator.serviceWorker.controller.postMessage('CLEAR_API_CACHE')
  }
}
