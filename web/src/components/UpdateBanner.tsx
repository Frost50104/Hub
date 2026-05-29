import { useEffect } from 'react'
import { useRegisterSW } from 'virtual:pwa-register/react'

import { Button } from '@/components/ui/Button'

const UPDATE_CHECK_INTERVAL_MS = 60_000

/**
 * Service Worker update banner.
 *
 * SW registered with `registerType: 'prompt'` waits for an explicit
 * `skipWaiting`. This banner polls for new versions every 60s and on
 * `visibilitychange` (iOS PWA freezes background timers, so the focus event
 * is the reliable wake-up), then surfaces a button to activate the new SW.
 *
 * Polling lives in a `useEffect` on `navigator.serviceWorker.ready`, NOT
 * inside `onRegisteredSW` — that callback only fires on first registration,
 * so users with an already-active SW would never get polled.
 */
export function UpdateBanner() {
  const {
    needRefresh: [needRefresh, setNeedRefresh],
    updateServiceWorker,
  } = useRegisterSW()

  useEffect(() => {
    if (!('serviceWorker' in navigator)) return undefined
    let cancelled = false
    let intervalId: number | undefined
    let visListener: (() => void) | undefined

    navigator.serviceWorker.ready
      .then((registration) => {
        if (cancelled || !registration) return
        const check = () => {
          if (navigator.onLine) void registration.update()
        }
        intervalId = window.setInterval(check, UPDATE_CHECK_INTERVAL_MS)
        visListener = () => {
          if (document.visibilityState === 'visible') check()
        }
        document.addEventListener('visibilitychange', visListener)
        // Kick off one check immediately — don't wait the full minute.
        check()
      })
      .catch(() => {
        /* SW not registered — nothing to poll. */
      })

    return () => {
      cancelled = true
      if (intervalId !== undefined) window.clearInterval(intervalId)
      if (visListener) document.removeEventListener('visibilitychange', visListener)
    }
  }, [])

  useEffect(() => {
    if (!needRefresh) return undefined
    // Safety net — `updateServiceWorker(true)` reloads itself, but iOS
    // sometimes ignores the reload. Force after a minute.
    const id = window.setTimeout(() => window.location.reload(), 60_000)
    return () => window.clearTimeout(id)
  }, [needRefresh])

  if (!needRefresh) return null

  return (
    <div className="glass fixed inset-x-4 bottom-4 z-40 flex flex-col gap-3 p-4 shadow-glass sm:left-auto sm:right-4 sm:w-96">
      <div>
        <p className="font-display text-sm font-semibold text-text">
          Доступно обновление
        </p>
        <p className="text-xs text-text2">
          Установлена новая версия Signaris Hub. Применить сейчас?
        </p>
      </div>
      <div className="flex justify-end gap-2">
        <Button variant="ghost" size="sm" onClick={() => setNeedRefresh(false)}>
          Позже
        </Button>
        <Button
          size="sm"
          onClick={() => {
            void updateServiceWorker(true)
            window.setTimeout(() => window.location.reload(), 1500)
          }}
        >
          Обновить
        </Button>
      </div>
    </div>
  )
}
