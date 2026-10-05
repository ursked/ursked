'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
// Loaded here, from the root layout, so its install-prompt listener is in place
// before the browser fires the event (see the module).
import '@/hooks/useInstallPrompt'

/*
 * Service worker registration, the update prompt, and the page's side of the
 * offline cache. The worker itself is public/sw.js; the names below must match
 * the ones it uses.
 */

// Build stamp (next.config.js). It versions the worker's URL, so every deploy
// installs a new worker, and the worker names and prunes its caches by it.
const BUILD_ID = process.env.NEXT_PUBLIC_BUILD_ID || 'dev'

// Per-user cache of the signed-in person's own reads (see sw.js). The user id
// in the name is what keeps one person's offline copy from ever being shown
// to the next person on the same device.
const API_CACHE_PREFIX = 'api-v2-u'
const PAGE_CACHE_PREFIX = 'pages-'

/** Message the worker posts when it answered from the offline copy. */
export const OFFLINE_COPY_MESSAGE = 'ursked:offline-copy'
/** Message the worker posts when a fresh response replaced the offline copy. */
export const FRESH_MESSAGE = 'ursked:fresh'

function hasCacheStorage(): boolean {
  // Cache Storage exists only in secure contexts (HTTPS or localhost).
  return typeof window !== 'undefined' && 'caches' in window
}

/**
 * Delete every cached personal response (and the cached page shells) on this
 * device. Called on sign-out, on session expiry, and on load when there is no
 * session.
 *
 * Works through the Cache Storage API directly, so it does not depend on a
 * worker controlling the page — it used to be a postMessage to the controller,
 * which silently did nothing on the first visit, after a hard reload, or while
 * a new worker was waiting. The worker is told as well, so a copy it is in the
 * middle of writing is dropped too.
 */
export async function clearApiCache(): Promise<void> {
  if (typeof navigator !== 'undefined' && navigator.serviceWorker?.controller) {
    navigator.serviceWorker.controller.postMessage({ type: 'CLEAR_API_CACHE' })
  }
  if (!hasCacheStorage()) return
  try {
    const keys = await caches.keys()
    await Promise.all(
      keys
        .filter((k) => k.startsWith(API_CACHE_PREFIX) || k.startsWith(PAGE_CACHE_PREFIX))
        .map((k) => caches.delete(k)),
    )
  } catch {
    /* Storage can be unavailable (private mode quota); nothing to clear then. */
  }
}

/**
 * Make `userId` the only person with an offline copy on this device: any other
 * user's cache is deleted and this user's is created, which is what allows the
 * worker to start keeping their reads.
 */
export async function keepApiCacheFor(userId: number): Promise<void> {
  if (!hasCacheStorage()) return
  const mine = `${API_CACHE_PREFIX}${userId}`
  try {
    const keys = await caches.keys()
    await Promise.all(
      keys
        .filter((k) => k.startsWith(API_CACHE_PREFIX) && k !== mine)
        .map((k) => caches.delete(k)),
    )
    await caches.open(mine)
  } catch {
    /* see clearApiCache */
  }
  navigator.serviceWorker?.controller?.postMessage({ type: 'SET_USER', userId })
}

/**
 * Registers the worker (production builds only) and offers updates.
 *
 * It used to reload the page whenever a worker took control — on the very
 * first visit, and mid-edit after every deploy, throwing away whatever had been
 * typed. Now a first install never reloads, and a new version waits until the
 * user chooses "Reload" in a small prompt (or simply opens the app again later).
 */
export default function PWARegistrar() {
  const [waiting, setWaiting] = useState<ServiceWorker | null>(null)
  const [dismissed, setDismissed] = useState(false)
  const accepted = useRef(false)

  useEffect(() => {
    if (typeof window === 'undefined' || !('serviceWorker' in navigator)) return

    // Development: a worker caching `next dev` output only gets in the way.
    // Remove one left over from a production build on the same origin.
    if (process.env.NODE_ENV !== 'production') {
      navigator.serviceWorker.getRegistrations()
        .then((regs) => regs.forEach((r) => r.unregister()))
        .catch(() => {})
      return
    }

    // Reload only when the user asked for the new version.
    const onControllerChange = () => {
      if (accepted.current) window.location.reload()
    }
    navigator.serviceWorker.addEventListener('controllerchange', onControllerChange)

    let registration: ServiceWorkerRegistration | null = null
    const offer = (worker: ServiceWorker | null) => {
      // No controller means this is the first install: nothing to replace.
      if (worker && navigator.serviceWorker.controller) setWaiting(worker)
    }
    const checkForUpdate = () => {
      if (document.visibilityState === 'visible') registration?.update().catch(() => {})
    }

    navigator.serviceWorker
      .register(`/sw.js?v=${encodeURIComponent(BUILD_ID)}`, { scope: '/', updateViaCache: 'none' })
      .then((reg) => {
        registration = reg
        offer(reg.waiting)
        reg.addEventListener('updatefound', () => {
          const incoming = reg.installing
          incoming?.addEventListener('statechange', () => {
            if (incoming.state === 'installed') offer(incoming)
          })
        })
      })
      .catch(() => {
        /* The worker is progressive enhancement; the app works without it. */
      })

    // An installed app can stay open for days; look for a new version when
    // it comes back to the foreground.
    document.addEventListener('visibilitychange', checkForUpdate)

    return () => {
      navigator.serviceWorker.removeEventListener('controllerchange', onControllerChange)
      document.removeEventListener('visibilitychange', checkForUpdate)
    }
  }, [])

  const reload = useCallback(() => {
    if (!waiting) return
    accepted.current = true
    waiting.postMessage({ type: 'SKIP_WAITING' })
  }, [waiting])

  if (!waiting || dismissed) return null

  return (
    <div
      role="status"
      aria-live="polite"
      className="fixed z-[65] left-4 right-4 top-[calc(4.5rem+env(safe-area-inset-top))] sm:top-auto sm:right-auto sm:left-4 sm:bottom-[calc(1rem+env(safe-area-inset-bottom))] sm:max-w-sm"
    >
      <div className="flex items-center gap-3 rounded-lg border border-brand-200 bg-white p-3 pl-4 shadow-lg">
        <p className="flex-1 text-sm text-gray-800">A new version of ursked is available.</p>
        <button
          type="button"
          onClick={reload}
          className="rounded-md bg-brand-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-700"
        >
          Reload
        </button>
        <button
          type="button"
          onClick={() => setDismissed(true)}
          aria-label="Not now"
          className="inline-flex h-8 w-8 items-center justify-center rounded-md text-gray-400 hover:bg-gray-100 hover:text-gray-600"
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>
    </div>
  )
}
