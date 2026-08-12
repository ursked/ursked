/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  swcMinify: true,
  // Emit a self-contained server bundle so the runtime image does not need the
  // full node_modules tree (~1GB -> ~150MB) and can run as a non-root user.
  output: 'standalone',
  // Version banner in responses is free reconnaissance for an attacker.
  poweredByHeader: false,
  images: {
    remotePatterns: [{ protocol: 'http', hostname: 'localhost' }],
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
