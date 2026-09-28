import type { MetadataRoute } from 'next'
import { APP_DESCRIPTION, APP_NAME, BACKGROUND_COLOR, BRAND_COLOR } from '@/lib/brand'

// Icon file names carry the brand, not a size alone: an installed app keeps the
// icon it fetched under a URL, so reusing /icons/icon-512.png would have left
// every existing install on the old placeholder "S".
export default function manifest(): MetadataRoute.Manifest {
  return {
    // A stable identity, so a later change to start_url does not make the
    // browser treat the app as a different one and offer to install it twice.
    id: '/dashboard',
    name: APP_NAME,
    short_name: APP_NAME,
    description: APP_DESCRIPTION,
    lang: 'en',
    dir: 'ltr',
    start_url: '/dashboard',
    scope: '/',
    display: 'standalone',
    // Rotating is useful on tablets and for the schedule grid on phones.
    orientation: 'any',
    background_color: BACKGROUND_COLOR,
    theme_color: BRAND_COLOR,
    categories: ['business', 'productivity'],
    icons: [
      { src: '/icons/ursked-192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
      { src: '/icons/ursked-512.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
      {
        src: '/icons/ursked-maskable-512.png',
        sizes: '512x512',
        type: 'image/png',
        purpose: 'maskable',
      },
    ],
    screenshots: [
      {
        src: '/screenshots/pwa-narrow.png',
        sizes: '780x1688',
        type: 'image/png',
        form_factor: 'narrow',
        label: 'My Schedule on a phone',
      },
      {
        src: '/screenshots/pwa-wide.png',
        sizes: '1440x900',
        type: 'image/png',
        form_factor: 'wide',
        label: 'Analytics on a desktop',
      },
    ],
  }
}
