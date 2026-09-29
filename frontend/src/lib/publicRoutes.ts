// Pages reachable without a session. The server-side guard (proxy.ts) and the
// client-side session-expiry handler (AuthContext) both read this list. They
// used to keep separate copies and both left out the password-reset pages, so
// a locked-out user who opened the reset link in their email was sent to the
// login screen and could never set a new password.
export const PUBLIC_PATHS = [
  '/',
  '/auth/login',
  '/auth/signup',
  '/auth/activate',
  '/auth/forgot-password',
  '/auth/reset-password',
  // Admin mode: the administrator sign-in page. Public like /auth/login, and
  // reachable WITH a session too: signing in there is how an employee
  // session becomes an admin one (proxy.ts must not bounce it).
  '/admin/login',
  // The finance sign-in page, for the same reason: signing in there is how
  // an employee session becomes a finance one.
  '/finance/login',
  // The service worker's offline page: fetched without a session when the
  // worker installs, and shown to whoever is using the device.
  '/offline',
];

export function isPublicPath(pathname: string): boolean {
  return PUBLIC_PATHS.some(
    (p) => pathname === p || (p !== '/' && pathname.startsWith(`${p}/`)),
  );
}
