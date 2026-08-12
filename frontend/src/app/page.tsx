import { redirect } from 'next/navigation';

/**
 * Community Edition root.
 *
 * The Community build ships no marketing page. Visiting the site goes straight
 * to sign-in. Authenticated visitors are forwarded on to the dashboard by the
 * route middleware once they hit /auth/login, so a single redirect is enough.
 *
 * `force-dynamic` matters: without it Next statically prerenders this route at
 * build time, where redirect() bakes into an inert shell instead of issuing a
 * real HTTP redirect. Forcing dynamic makes '/' return a 307 to /auth/login on
 * every request.
 *
 * This file is swapped in for src/app/page.tsx by ce-export.sh. It is not a
 * stripped copy of the SaaS landing page and must stay minimal.
 */
export const dynamic = 'force-dynamic';

export default function CommunityRoot() {
  redirect('/auth/login');
}
