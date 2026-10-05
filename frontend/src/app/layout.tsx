import type { Metadata, Viewport } from 'next';
import { Inter } from 'next/font/google';
import './globals.css';
import { Providers } from './providers';
import PWARegistrar from '@/components/PWARegistrar';
import { OfflineBanner } from '@/components/layout/OfflineBanner';
import { RouteTitle } from '@/components/layout/RouteTitle';
import { APP_DESCRIPTION, APP_NAME, BRAND_COLOR } from '@/lib/brand';

const inter = Inter({ subsets: ['latin'] });

export const metadata: Metadata = {
  // Every screen used to be titled the same, so the task switcher and the
  // installed app's window list could not tell them apart. Screens set their
  // name through RouteTitle; a segment that exports its own metadata title
  // gets the same "Screen · ursked" form from this template.
  title: {
    default: APP_NAME,
    template: `%s · ${APP_NAME}`,
  },
  description: APP_DESCRIPTION,
  applicationName: APP_NAME,
  manifest: '/manifest.webmanifest',
  appleWebApp: {
    capable: true,
    // "default" = dark text on a light bar, matching the white header. The
    // translucent style would put white status-bar text over that header.
    statusBarStyle: 'default',
    title: APP_NAME,
  },
  // Next renders appleWebApp.capable as the unprefixed mobile-web-app-capable
  // only; older iOS versions honour just the apple- prefixed tag and open the
  // home-screen icon in a Safari tab without it. No splash images are shipped: iOS then shows
  // the background colour while the app loads.
  other: {
    'apple-mobile-web-app-capable': 'yes',
  },
  icons: {
    icon: [
      { url: '/favicon.ico', sizes: '48x48' },
      { url: '/logo/ursked-mark.svg', type: 'image/svg+xml' },
      { url: '/icons/ursked-32.png', type: 'image/png', sizes: '32x32' },
      { url: '/icons/ursked-192.png', type: 'image/png', sizes: '192x192' },
    ],
    apple: [{ url: '/icons/ursked-apple-touch-180.png', sizes: '180x180' }],
  },
};

export const viewport: Viewport = {
  themeColor: BRAND_COLOR,
  width: 'device-width',
  initialScale: 1,
  // Content may run under a notch or home indicator; the shell pads itself
  // with env(safe-area-inset-*) (header, sidebar, main, toasts, side panels).
  viewportFit: 'cover',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={inter.className}>
        <Providers>{children}</Providers>
        <OfflineBanner />
        <RouteTitle />
        <PWARegistrar />
      </body>
    </html>
  );
}
