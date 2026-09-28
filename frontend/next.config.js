const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

/**
 * Build stamp for the service worker.
 *
 * The worker's cache names were fixed at `v1`, so every deploy added to the
 * same caches and nothing was ever pruned. The page now registers
 * /sw.js?v=<id>: a new id installs a new worker, which deletes every cache that
 * is not its own.
 *
 * The id is a hash of what ships (src, public, the lockfile), not a timestamp:
 * `next build` evaluates this file in several processes, and they must all
 * agree. SW_BUILD_ID overrides it (e.g. a CI build number).
 */
function hashTree(hash, dir) {
  let entries;
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true });
  } catch {
    return;
  }
  for (const entry of entries.sort((a, b) => a.name.localeCompare(b.name))) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      hashTree(hash, full);
    } else if (entry.isFile()) {
      hash.update(path.relative(__dirname, full));
      hash.update(fs.readFileSync(full));
    }
  }
}

function buildId() {
  if (process.env.SW_BUILD_ID) return process.env.SW_BUILD_ID;
  const hash = crypto.createHash('sha256');
  for (const part of ['src', 'public']) hashTree(hash, path.join(__dirname, part));
  for (const file of ['package-lock.json', 'next.config.js']) {
    try {
      hash.update(fs.readFileSync(path.join(__dirname, file)));
    } catch {
      /* absent in some checkouts */
    }
  }
  return hash.digest('hex').slice(0, 16);
}

const BUILD_ID = buildId();

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Emit a self-contained server bundle so the runtime image does not need the
  // full node_modules tree (~1GB -> ~150MB) and can run as a non-root user.
  output: 'standalone',
  // Version banner in responses is free reconnaissance for an attacker.
  poweredByHeader: false,
  generateBuildId: async () => BUILD_ID,
  env: {
    NEXT_PUBLIC_BUILD_ID: BUILD_ID,
  },
  images: {
    remotePatterns: [{ protocol: 'http', hostname: 'localhost' }],
  },
  async headers() {
    return [
      {
        // The browser must always ask for the worker script itself; a cached
        // copy would hold back every update behind the HTTP cache.
        source: '/sw.js',
        headers: [{ key: 'Cache-Control', value: 'no-cache' }],
      },
      // Not /api/*: Next applies neither these headers nor ones set in
      // src/proxy.ts to responses proxied by the rewrite below (checked), so
      // `Cache-Control: no-store` for the API must come from the backend.
    ];
  },
  async rewrites() {
    const backend = process.env.API_INTERNAL_URL || 'http://localhost:8000';
    return [
      // Same-origin proxy: the browser only ever talks to this origin, so the
      // auth cookies are first-party and CORS is never involved.
      {
        source: '/api/:path*',
        destination: `${backend}/api/:path*`,
      },
      {
        source: '/health',
        destination: `${backend}/health`,
      },
    ];
  },
};

module.exports = nextConfig;
