import { useEffect, useRef } from 'react'

import { api } from '@/lib/api'
import { pushApi } from '@/lib/notifications'
import {
  isOptedIn,
  lastSyncAt,
  markSynced,
  pushOwner,
  shouldSyncPush,
  urlBase64ToUint8Array,
} from '@/lib/pushRefresh'

/**
 * Тихое подтверждение push-подписки при запуске приложения.
 *
 * Живёт в `Shell` — корневом лэйауте, а НЕ в `usePush`. Это принципиально:
 * `usePush` монтируется всего в двух местах — в `PushPermissionPrompt` (только
 * на главной трекера) и в настройках. PWA, открытая на «Обучении» или по
 * ссылке из уведомления, этот хук не смонтировала бы вовсе, и переподписка
 * выглядела бы сделанной, ничего не делая.
 *
 * Что чинит: подписку, которую iOS отозвал (переустановка PWA, долгий простой)
 * — прежде она умирала молча, потому что баннер разрешения показывается только
 * при `permission === 'default'`. И продлевает `last_seen_at`, на котором
 * держится гейт свежести на сервере.
 *
 * Ошибки глотаются: это фоновая гигиена, а не действие человека. На iOS
 * `serviceWorker.ready` вдобавок может не резолвиться, пока SW не активен —
 * ждать его в UI нельзя.
 *
 * Принимает employee_id, а не флаг «готово»: на общем устройстве смена
 * пользователя обязана перевесить endpoint СРАЗУ, в обход 12-часового троттла
 * (иначе новый вошедший до полусуток получал бы уведомления предыдущего).
 */
export function usePushAutoRefresh(employeeId: string | undefined): void {
  // Гард от повторного запуска в рамках одной загрузки страницы: React
  // перемонтирует Shell при навигации, а StrictMode в dev — сразу дважды.
  const started = useRef(false)

  useEffect(() => {
    if (!employeeId || started.current) return
    if (typeof Notification === 'undefined' || !('serviceWorker' in navigator)) return
    if (
      !shouldSyncPush({
        permission: Notification.permission,
        optedIn: isOptedIn(),
        lastSyncAt: lastSyncAt(),
        owner: pushOwner(),
        employeeId,
        now: Date.now(),
      })
    ) {
      return
    }
    started.current = true

    void (async () => {
      try {
        const env = await api
          .get<{ vapid_public_key: string | null }>('/env')
          .then((r) => r.data)
        if (!env.vapid_public_key) return

        const reg = await navigator.serviceWorker.ready
        const existing = await reg.pushManager.getSubscription()
        const sub =
          existing ??
          (await reg.pushManager.subscribe({
            userVisibleOnly: true,
            applicationServerKey: urlBase64ToUint8Array(
              env.vapid_public_key,
            ) as BufferSource,
          }))
        const json = sub.toJSON() as {
          endpoint?: string
          keys?: { p256dh?: string; auth?: string }
        }
        if (!json.endpoint || !json.keys?.p256dh || !json.keys?.auth) return
        await pushApi.subscribe({
          endpoint: json.endpoint,
          keys: { p256dh: json.keys.p256dh, auth: json.keys.auth },
          user_agent: navigator.userAgent.slice(0, 256),
        })
        markSynced(Date.now(), employeeId)
      } catch {
        // Фоновая гигиена: не показываем ошибок и не мешаем работать.
      }
    })()
  }, [employeeId])
}
