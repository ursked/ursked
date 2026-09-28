'use client'

import { useEffect, useState } from 'react'

interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>
}

// Chrome fires beforeinstallprompt once per page load, often before the
// signed-in shell (and so the account menu) has mounted. Catch it at module
// load — PWARegistrar imports this module from the root layout — and hand it
// to whichever component asks later.
let captured: BeforeInstallPromptEvent | null = null
const subscribers = new Set<(e: BeforeInstallPromptEvent | null) => void>()

if (typeof window !== 'undefined') {
  window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault()
    captured = e as BeforeInstallPromptEvent
    subscribers.forEach((fn) => fn(captured))
  })
  window.addEventListener('appinstalled', () => {
    captured = null
    subscribers.forEach((fn) => fn(null))
  })
}

/** Captures the beforeinstallprompt event so we can show a custom "Install"
 * button. iOS Safari doesn't fire this, so `canInstall` stays false there and
 * callers should show manual "Add to Home Screen" instructions instead.
 *
 * Used by the account menu (components/layout/Header.tsx): employees mostly
 * reach ursked on a phone, and the browser's own install entry is buried in a
 * menu most people never open. */
export function useInstallPrompt() {
  const [deferred, setDeferred] = useState<BeforeInstallPromptEvent | null>(null)
  const [installed, setInstalled] = useState(false)
  const [isIOS, setIsIOS] = useState(false)

  useEffect(() => {
    const standalone =
      window.matchMedia?.('(display-mode: standalone)').matches ||
      (navigator as Navigator & { standalone?: boolean }).standalone === true
    const ios =
      /iphone|ipad|ipod/i.test(navigator.userAgent) && !/crios|fxios/i.test(navigator.userAgent)
    // Deferred so the state updates do not run synchronously in the effect
    // body (react-hooks/set-state-in-effect).
    void Promise.resolve().then(() => {
      setInstalled(standalone)
      setIsIOS(ios)
      setDeferred(captured)
    })

    const onChange = (e: BeforeInstallPromptEvent | null) => {
      setDeferred(e)
      if (!e) setInstalled(true)
    }
    subscribers.add(onChange)
    return () => {
      subscribers.delete(onChange)
    }
  }, [])

  const promptInstall = async () => {
    if (!deferred) return false
    await deferred.prompt()
    const choice = await deferred.userChoice
    // The event can be used once; the browser fires a new one if the user may
    // be asked again.
    captured = null
    setDeferred(null)
    return choice.outcome === 'accepted'
  }

  return { canInstall: !!deferred && !installed, installed, promptInstall, isIOS }
}
