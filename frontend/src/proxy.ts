import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

/**
 * Community Edition route guard (Next.js proxy).
 *
 * Same UX guard as the SaaS build, with one addition: the Community build ships
 * no marketing landing page, so the root path is redirected server-side (a real
 * 307, no client-side flash) — to the dashboard when a session is present, and
 * to sign-in otherwise. This file is swapped in for src/proxy.ts by
 * ce-export.sh.
 *
 * This is a UX guard, not an authorization boundary — real enforcement is
 * server-side on every API route. It only checks for the presence of a session
 * cookie and does not verify the JWT signature.
 */

const ACCESS_COOKIE = 'access_token';
const REFRESH_COOKIE = 'refresh_token';

// Reachable without a session. The Community build has no /auth/signup.
const PUBLIC_PATHS = [
  '/auth/login',
  '/auth/activate',
];

function isPublic(pathname: string): boolean {
  return PUBLIC_PATHS.some((p) => pathname === p || pathname.startsWith(`${p}/`));
}

export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;

  const hasSession =
    request.cookies.has(ACCESS_COOKIE) || request.cookies.has(REFRESH_COOKIE);

  // No landing page: send the root straight where it belongs.
  if (pathname === '/') {
    return NextResponse.redirect(
      new URL(hasSession ? '/dashboard' : '/auth/login', request.url),
    );
  }

  // Let auth routes resolve on their own so a non-existent one (e.g. the removed
  // /auth/signup) returns a genuine 404 instead of bouncing to login with a
  // dangling ?next. Everything else, when unauthenticated, goes to sign-in.
  if (!hasSession && !isPublic(pathname) && !pathname.startsWith('/auth/')) {
    const loginUrl = new URL('/auth/login', request.url);
    // Preserve the destination so the user lands where they intended.
    loginUrl.searchParams.set('next', `${pathname}${search}`);
    return NextResponse.redirect(loginUrl);
  }

  if (hasSession && pathname === '/auth/login') {
    return NextResponse.redirect(new URL('/dashboard', request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    // Everything except Next internals, the API proxy, static assets, and the
    // PWA files (service worker + manifest) which the browser fetches without a
    // session and must never redirect to the login page.
    '/((?!api|_next/static|_next/image|favicon.ico|sw.js|manifest.webmanifest|icons/|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)',
  ],
};
