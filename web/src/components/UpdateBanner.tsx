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
 */
export function UpdateBanner() {
  const {
    needRefresh: [needRefresh, setNeedRefresh],
    updateServiceWorker,
  } = useRegisterSW({
    onRegisteredSW(_swUrl, registration) {
      if (!registration) return
      const check = () => {
        if (registration.installing || !navigator) return
        if (!('connection' in navigator) || navigator.onLine) {
          void registration.update()
        }
      }
      window.setInterval(check, UPDATE_CHECK_INTERVAL_MS)
      window.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') check()
      })
    },
  })

  useEffect(() => {
    if (!needRefresh) return undefined
    // Fallback in case `updateServiceWorker` doesn't reload in some edge case.
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
            // updateServiceWorker(true) reloads automatically after activation,
            // but iOS sometimes ignores it — explicit reload as a safety net.
            window.setTimeout(() => window.location.reload(), 1500)
          }}
        >
          Обновить
        </Button>
      </div>
    </div>
  )
}
