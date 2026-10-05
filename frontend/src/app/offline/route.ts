import { APP_NAME, BRAND_COLOR } from '@/lib/brand';

// The page the service worker shows when a navigation fails for lack of a
// network. The old worker's comment promised one; none existed, so an offline
// launch showed the browser's own error page.
//
// Deliberately a plain, self-contained HTML document rather than a React page:
// every app page renders inside providers that wait on network calls before
// showing anything, and it would need its script chunks cached to appear at
// all. This needs only itself and the logo, both precached when the worker
// installs. Public (no session) — see lib/publicRoutes.ts and the CE proxy.
export const dynamic = 'force-static';

const html = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="${BRAND_COLOR}">
<meta name="robots" content="noindex">
<title>Offline · ${APP_NAME}</title>
<link rel="icon" href="/favicon.ico" sizes="48x48">
<link rel="manifest" href="/manifest.webmanifest">
<style>
  *{box-sizing:border-box}
  html,body{margin:0;height:100%}
  body{font-family:Inter,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;color:#111827;
    background:linear-gradient(135deg,#ecfdf5 0%,#ffffff 50%,#ecfdf5 100%);
    min-height:100vh;min-height:100dvh;display:flex;align-items:center;justify-content:center;
    padding:calc(1rem + env(safe-area-inset-top)) calc(1rem + env(safe-area-inset-right))
      calc(1rem + env(safe-area-inset-bottom)) calc(1rem + env(safe-area-inset-left))}
  main{width:100%;max-width:28rem;text-align:center}
  .logo{height:2.5rem;width:auto;margin:0 auto 2rem;display:block}
  .card{background:#fff;border:1px solid #f3f4f6;border-radius:1rem;padding:2rem;
    box-shadow:0 10px 15px -3px rgba(0,0,0,.08),0 4px 6px -4px rgba(0,0,0,.06)}
  .badge{width:3rem;height:3rem;border-radius:9999px;background:#d1fae5;color:${BRAND_COLOR};
    display:inline-flex;align-items:center;justify-content:center;margin-bottom:1rem}
  h1{font-size:1.25rem;margin:0 0 .5rem}
  p{color:#6b7280;font-size:.875rem;line-height:1.5;margin:0 0 1.5rem}
  .actions{display:flex;flex-direction:column;gap:.75rem}
  .btn{display:block;width:100%;padding:.75rem 1rem;border-radius:.5rem;font:inherit;font-size:.875rem;
    font-weight:500;text-decoration:none;cursor:pointer;border:0}
  /* brand-600 / 700, the buttons on the sign-in pages */
  .primary{background:#047857;color:#fff}
  .primary:hover{background:#065f46}
  .secondary{background:#ecfdf5;color:#065f46}
  .secondary:hover{background:#d1fae5}
  .btn:focus-visible{outline:2px solid ${BRAND_COLOR};outline-offset:2px}
  [hidden]{display:none!important}
</style>
</head>
<body>
<main>
  <img class="logo" src="/logo/ursked-logo.svg" alt="${APP_NAME}" width="294" height="64">
  <div class="card">
    <div class="badge" aria-hidden="true">
      <svg width="24" height="24" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 2l20 20M8.5 16.5a5 5 0 0 1 7 0M2 8.82a15 15 0 0 1 4.17-2.65M10.66 5c4.01-.36 8.14.9 11.34 3.76M16.85 11.25a10 10 0 0 1 2.22 1.68M5 13a10 10 0 0 1 5.24-2.76M12 20h.01"/></svg>
    </div>
    <h1>You are offline</h1>
    <p>This page needs a connection. Check your Wi-Fi or mobile data and try again.
      Nothing you change while offline is sent.</p>
    <div class="actions">
      <button type="button" class="btn primary" id="retry">Try again</button>
      <a class="btn secondary" id="saved" href="/my/schedule" hidden>Open my saved schedule</a>
    </div>
  </div>
</main>
<script>
  document.getElementById('retry').addEventListener('click', function () { location.reload(); });
  window.addEventListener('online', function () { location.reload(); });
  // Offer the saved schedule only when this device holds one for the person
  // signed in (the worker keeps it per user and deletes it on sign-out).
  if (window.caches && location.pathname !== '/my/schedule') {
    caches.keys().then(function (keys) {
      var user = keys.some(function (k) { return k.indexOf('api-v2-u') === 0; });
      var page = keys.filter(function (k) { return k.indexOf('pages-') === 0; });
      if (!user || !page.length) return;
      return caches.match('/my/schedule', { cacheName: page[0] }).then(function (hit) {
        if (hit) document.getElementById('saved').hidden = false;
      });
    }).catch(function () {});
  }
</script>
</body>
</html>
`;

export function GET() {
  return new Response(html, {
    headers: {
      'Content-Type': 'text/html; charset=utf-8',
      'Cache-Control': 'no-cache',
    },
  });
}
