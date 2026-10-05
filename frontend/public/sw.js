/* ursked service worker (hand-rolled, no build step).
 *
 * What it keeps, and why so little:
 *
 *   - Next's hashed build files (/_next/static): cache-first. Their names
 *     change whenever their content does.
 *   - Icons, logo, favicon and the manifest: stale-while-revalidate, so a new
 *     icon reaches an installed app on the next launch instead of never.
 *   - The offline page (/offline): precached, and shown when a navigation fails
 *     for lack of a network.
 *   - The signed-in person's OWN reads needed for an offline "My Schedule" and
 *     "My Leave" (PERSONAL_API below), plus those two page shells.
 *
 * Everything else — team grids, approvals, other people's leave, exports, every
 * write — goes straight to the network and is never stored. The old worker
 * cached every /schedules and /leave/applications GET under one shared name, so
 * team schedules and approvals outlived the session on the device, and it gave
 * up on the network after 3 seconds (the app itself allows 30), silently
 * showing a stale grid whenever the server was slow.
 *
 * Rules for the personal cache:
 *   - One cache per user: `api-v2-u<userId>`. The page creates it at sign-in and
 *     deletes every cache of this kind at sign-out, on session expiry and on
 *     load with no session (components/PWARegistrar.tsx). With none present,
 *     nothing is kept. When /auth/me answers with a different user than the
 *     cache belongs to, every personal cache is dropped first.
 *   - Network first, always. The copy is used ONLY when the request fails at
 *     the network layer (offline, DNS, connection refused) — never because the
 *     server is slow, and never for an HTTP error.
 *   - A response served from the copy carries `X-Ursked-Offline-Copy: <saved
 *     at>` and the page is told (message `ursked:offline-copy`), so the screen
 *     can say "offline copy from 14:05" instead of passing it off as current.
 *
 * Versioning: the page registers /sw.js?v=<build id> (next.config.js stamps the
 * id), so each deploy installs a new worker; activate deletes every cache that
 * is not this build's. The new worker waits until the user accepts the "new
 * version" prompt (SKIP_WAITING) — it never takes over a page mid-edit.
 */
const VERSION = new URL(self.location.href).searchParams.get('v') || 'dev'
const SHELL_CACHE = `shell-${VERSION}` // /_next/static + the offline page
const ASSET_CACHE = `assets-${VERSION}` // icons, logo, manifest
const PAGE_CACHE = `pages-${VERSION}` // the My Schedule / My Leave shells
const API_CACHE_PREFIX = 'api-v2-u' // + user id; see PWARegistrar.tsx

const OFFLINE_URL = '/offline'
const CACHED_AT = 'X-Ursked-Cached-At'
const OFFLINE_COPY = 'X-Ursked-Offline-Copy'
const MAX_API_ENTRIES = 60

// Page shells kept for offline use. They are client-rendered and carry no
// personal data; the data comes from the personal API cache.
const OFFLINE_PAGES = ['/my/schedule', '/my/leave']

const PRECACHE_ASSETS = [
  '/logo/ursked-logo.svg',
  '/favicon.ico',
  '/icons/ursked-192.png',
  '/manifest.webmanifest',
]

// The only API reads ever stored, each limited to the caller's own data.
const PERSONAL_API = {
  '/api/v1/auth/me': () => true,
  '/api/v1/permissions/me': () => true,
  '/api/v1/settings/preferences': () => true,
  // The company's shift legend, needed to draw My Schedule.
  '/api/v1/settings/status-types': () => true,
  // mine=true: the server returns the caller's row only. Never actuals.
  '/api/v1/schedules/grid': (q) => q.get('mine') === 'true' && !q.has('include_actuals'),
  // Without employee_id it is the caller's own balance.
  '/api/v1/leave/balance': (q) => !q.has('employee_id'),
  '/api/v1/leave/applications': (q) => q.get('scope') === 'mine',
}

function isPersonalApi(url) {
  const rule = PERSONAL_API[url.pathname]
  return !!rule && rule(url.searchParams)
}

// ── Cache housekeeping ───────────────────────────────────────────────────────

// Message handlers and cache writes run one at a time, so a sign-out's clear
// cannot interleave with the next user's cache being created.
let chain = Promise.resolve()
function serial(task) {
  chain = chain.then(task, task)
  return chain
}

async function userCaches() {
  return (await caches.keys()).filter((k) => k.startsWith(API_CACHE_PREFIX))
}

/** The one user cache in use, or null. More than one is never expected; if it
 * happens nobody can be sure whose data is whose, so all are dropped. */
async function currentUserCache() {
  const names = await userCaches()
  if (names.length === 1) return names[0]
  if (names.length > 1) await Promise.all(names.map((n) => caches.delete(n)))
  return null
}

async function clearPersonal() {
  const keys = await caches.keys()
  await Promise.all(
    keys
      .filter((k) => k.startsWith(API_CACHE_PREFIX) || k.startsWith('pages-'))
      .map((k) => caches.delete(k))
  )
}

async function switchUser(userId) {
  const mine = `${API_CACHE_PREFIX}${userId}`
  const others = (await userCaches()).filter((n) => n !== mine)
  if (others.length) {
    // A different person signed in: nothing of the previous one survives,
    // page shells included.
    await clearPersonal()
  }
  await caches.open(mine)
  return mine
}

/** Fetch the My Schedule / My Leave shells and the build files they load, so
 * they open offline even if this person has only ever reached them through
 * in-app navigation (which never requests the page itself). */
async function warmShells() {
  const pages = await caches.open(PAGE_CACHE)
  const shell = await caches.open(SHELL_CACHE)
  for (const path of OFFLINE_PAGES) {
    if (await pages.match(path)) continue
    try {
      const resp = await fetch(path, { credentials: 'same-origin', cache: 'no-store' })
      // Redirected means no session (sign-in page): keep nothing.
      if (resp.status !== 200 || resp.redirected) continue
      const html = await resp.clone().text()
      await pages.put(path, resp)
      const files = new Set(html.match(/\/_next\/static\/[^"'\s\\)]+/g) || [])
      await Promise.all(
        [...files].map(async (f) => {
          if (!(await shell.match(f))) await shell.add(f).catch(() => {})
        })
      )
    } catch (_) {
      /* offline right now; the next sign-in or visit fills it */
    }
  }
}

// ── Lifecycle ────────────────────────────────────────────────────────────────

self.addEventListener('install', (event) => {
  // No skipWaiting(): a first install has nothing to replace and activates on
  // its own; an update waits for the user (see the message handler).
  event.waitUntil(precache())
})

async function precache() {
  const shell = await caches.open(SHELL_CACHE)
  try {
    const resp = await fetch(OFFLINE_URL, { cache: 'no-store' })
    if (resp.ok && !resp.redirected) await shell.put(OFFLINE_URL, resp)
  } catch (_) {
    /* Installing offline: the page is fetched again on the next update. */
  }
  const assets = await caches.open(ASSET_CACHE)
  await Promise.all(PRECACHE_ASSETS.map((u) => assets.add(u).catch(() => {})))
}

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      const keep = new Set([SHELL_CACHE, ASSET_CACHE, PAGE_CACHE])
      const keys = await caches.keys()
      await Promise.all(
        keys
          // Personal caches are not build-specific; everything else from an
          // older build (and the old worker's shell-v1 / api-v1) goes.
          .filter((k) => !keep.has(k) && !k.startsWith(API_CACHE_PREFIX))
          .map((k) => caches.delete(k))
      )
      if (self.registration.navigationPreload) {
        await self.registration.navigationPreload.enable().catch(() => {})
      }
      await self.clients.claim()
    })()
  )
})

self.addEventListener('message', (event) => {
  const data = event.data || {}
  const type = typeof data === 'string' ? data : data.type
  if (type === 'CLEAR_API_CACHE') {
    event.waitUntil(serial(clearPersonal))
  } else if (type === 'SET_USER' && Number.isInteger(data.userId)) {
    event.waitUntil(serial(() => switchUser(data.userId).then(warmShells)))
  } else if (type === 'SKIP_WAITING') {
    // The user chose "Reload" on the new-version prompt.
    self.skipWaiting()
  }
})

// ── Fetch ────────────────────────────────────────────────────────────────────

self.addEventListener('fetch', (event) => {
  const { request } = event
  if (request.method !== 'GET') return // writes are never cached or queued

  const url = new URL(request.url)
  if (url.origin !== self.location.origin) return

  if (request.mode === 'navigate') {
    event.respondWith(navigate(event, url))
    return
  }

  if (url.pathname.startsWith('/api/')) {
    if (isPersonalApi(url)) event.respondWith(personalApi(event, url))
    return // every other API read: network only, never stored
  }

  if (url.pathname.startsWith('/_next/static/')) {
    event.respondWith(cacheFirst(request))
    return
  }

  if (
    url.pathname.startsWith('/icons/') ||
    url.pathname.startsWith('/logo/') ||
    url.pathname === '/favicon.ico' ||
    url.pathname === '/manifest.webmanifest'
  ) {
    event.respondWith(staleWhileRevalidate(event, request))
  }
})

async function navigate(event, url) {
  const keepShell = OFFLINE_PAGES.includes(url.pathname)
  try {
    const resp = (await event.preloadResponse) || (await fetch(event.request))
    // Only a real page: not a redirect to sign-in, not an error page.
    if (keepShell && resp.status === 200 && resp.type === 'basic' && !resp.redirected) {
      const copy = resp.clone()
      event.waitUntil(
        serial(async () => {
          // Kept only while someone is signed in on this device.
          if (await currentUserCache()) await (await caches.open(PAGE_CACHE)).put(url.pathname, copy)
        })
      )
    }
    return resp
  } catch (err) {
    if (keepShell) {
      const shell = await caches.match(url.pathname, { cacheName: PAGE_CACHE })
      if (shell && (await currentUserCache())) return shell
    }
    const offline = await caches.match(OFFLINE_URL, { cacheName: SHELL_CACHE })
    if (offline) return offline
    return new Response('<!doctype html><title>Offline</title><p>You are offline.</p>', {
      status: 503,
      headers: { 'Content-Type': 'text/html; charset=utf-8' },
    })
  }
}

async function personalApi(event, url) {
  const { request } = event
  let resp
  try {
    // No timeout: a slow server is still the server. The app's own request
    // timeout (30 s) decides when to give up. no-store: the browser's HTTP
    // cache is keyed by URL, not by who is signed in, so it must never answer
    // for the network here.
    resp = await fetch(request, { cache: 'no-store' })
  } catch (err) {
    const name = await currentUserCache()
    const cached = name ? await (await caches.open(name)).match(request) : undefined
    if (!cached) throw err
    const savedAt = cached.headers.get(CACHED_AT) || ''
    notify(event, { type: 'ursked:offline-copy', cachedAt: savedAt, url: url.pathname })
    const headers = new Headers(cached.headers)
    headers.set(OFFLINE_COPY, savedAt || 'unknown')
    return new Response(cached.body, { status: cached.status, statusText: cached.statusText, headers })
  }
  if (resp.status === 200) {
    // Cloned now: by the time the queued write runs, the page has read resp.
    const copy = resp.clone()
    event.waitUntil(serial(() => store(request, url, copy)))
    notify(event, { type: 'ursked:fresh' })
  }
  return resp
}

async function store(request, url, resp) {
  let name
  if (url.pathname === '/api/v1/auth/me') {
    // The server says who this session is; make the cache theirs.
    const me = await resp.clone().json().catch(() => null)
    if (!me || !Number.isInteger(me.id)) return
    name = await switchUser(me.id)
  } else {
    name = await currentUserCache()
  }
  if (!name) return // nobody signed in on this device: keep nothing
  const headers = new Headers(resp.headers)
  headers.set(CACHED_AT, new Date().toISOString())
  const body = await resp.blob()
  if (!(await caches.has(name))) return // cleared while reading the body
  const cache = await caches.open(name)
  await cache.put(request, new Response(body, { status: 200, statusText: 'OK', headers }))
  // Oldest first: keys() keeps insertion order.
  const keys = await cache.keys()
  for (let i = 0; i < keys.length - MAX_API_ENTRIES; i++) await cache.delete(keys[i])
}

async function notify(event, message) {
  const id = event.clientId || event.resultingClientId
  if (!id) return
  const client = await self.clients.get(id)
  if (client) client.postMessage(message)
}

async function cacheFirst(request) {
  const cache = await caches.open(SHELL_CACHE)
  const cached = await cache.match(request)
  if (cached) return cached
  const resp = await fetch(request)
  if (resp && resp.status === 200) cache.put(request, resp.clone())
  return resp
}

async function staleWhileRevalidate(event, request) {
  const cache = await caches.open(ASSET_CACHE)
  const cached = await cache.match(request)
  const refresh = fetch(request)
    .then((resp) => {
      if (resp && resp.status === 200) return cache.put(request, resp.clone()).then(() => resp)
      return resp
    })
    .catch(() => undefined)
  if (cached) {
    event.waitUntil(refresh)
    return cached
  }
  const fresh = await refresh
  return fresh || Response.error()
}
