/* SchedulePro service worker (hand-rolled, no build step).
 *
 * Strategy:
 *   - App shell / static assets: cache-first, versioned cache.
 *   - A small allowlist of GET API endpoints (schedule, leave balance,
 *     applications): network-first with a 3s timeout, so the "my schedule"
 *     view works offline with a stale copy.
 *   - Everything else (all mutations, auth): network-only, never cached.
 *
 * Auth safety: only 200 responses are cached; the app posts CLEAR_API_CACHE on
 * login/logout so one user's data is never served to the next.
 */
const VERSION = 'v1'
const SHELL_CACHE = `shell-${VERSION}`
const API_CACHE = `api-${VERSION}`

const API_ALLOWLIST = [
  /\/api\/v1\/schedules(\/|\?|$)/,
  /\/api\/v1\/leave\/balance(\/|\?|$)/,
  /\/api\/v1\/leave\/applications(\/|\?|$)/,
]

self.addEventListener('install', (event) => {
  self.skipWaiting()
  event.waitUntil(caches.open(SHELL_CACHE))
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys()
      await Promise.all(
        keys
          .filter((k) => k !== SHELL_CACHE && k !== API_CACHE)
          .map((k) => caches.delete(k))
      )
      await self.clients.claim()
    })()
  )
})

self.addEventListener('message', (event) => {
  if (event.data === 'CLEAR_API_CACHE') {
    caches.delete(API_CACHE)
  }
})

function isApiCacheable(url) {
  return API_ALLOWLIST.some((re) => re.test(url))
}

async function networkFirst(request) {
  const cache = await caches.open(API_CACHE)
  try {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), 3000)
    const resp = await fetch(request, { signal: controller.signal })
    clearTimeout(timer)
    if (resp && resp.status === 200) {
      cache.put(request, resp.clone())
    }
    return resp
  } catch (err) {
    const cached = await cache.match(request)
    if (cached) return cached
    throw err
  }
}

async function cacheFirst(request) {
  const cache = await caches.open(SHELL_CACHE)
  const cached = await cache.match(request)
  if (cached) return cached
  const resp = await fetch(request)
  if (resp && resp.status === 200 && request.method === 'GET') {
    cache.put(request, resp.clone())
  }
  return resp
}

self.addEventListener('fetch', (event) => {
  const { request } = event
  if (request.method !== 'GET') return // never cache mutations

  const url = new URL(request.url)

  // Same-origin API allowlist → network-first.
  if (url.origin === self.location.origin && url.pathname.startsWith('/api/')) {
    if (isApiCacheable(url.pathname)) {
      event.respondWith(networkFirst(request))
    }
    return // other API GETs: default network handling
  }

  // Next static assets and images → cache-first.
  if (
    url.origin === self.location.origin &&
    (url.pathname.startsWith('/_next/static/') ||
      url.pathname.startsWith('/icons/') ||
      url.pathname === '/manifest.webmanifest')
  ) {
    event.respondWith(cacheFirst(request))
  }
})
