import { useCallback, useEffect, useState } from 'react'

import { useMe } from '@/hooks/useMe'
import { api } from '@/lib/api'
import { pushApi } from '@/lib/notifications'
import { markOptedIn, markOptedOut, urlBase64ToUint8Array } from '@/lib/pushRefresh'

type Permission = 'unsupported' | 'default' | 'granted' | 'denied'

interface EnvResponse {
  version: string
  environment: string
  vapid_public_key: string | null
  sentry_dsn: string | null
}

export interface UsePushResult {
  /** Browser permission. `unsupported` when Notification or SW APIs missing. */
  permission: Permission
  /** True when a subscription already exists for this browser. */
  subscribed: boolean
  /** Request permission + register subscription. Must be called from a user gesture. */
  subscribe: () => Promise<boolean>
  /** Unsubscribe locally and remove from backend. */
  unsubscribe: () => Promise<void>
}

export function usePush(): UsePushResult {
  // Кому принадлежит подписка: без этого владелец endpoint'а остаётся пустым и
  // следующий запуск делает лишнюю переподписку.
  const employeeId = useMe().data?.employee_id
  const [permission, setPermission] = useState<Permission>(() => {
    if (typeof Notification === 'undefined' || !('serviceWorker' in navigator)) {
      return 'unsupported'
    }
    return Notification.permission as Permission
  })
  const [subscribed, setSubscribed] = useState(false)

  // Check existing subscription on mount.
  useEffect(() => {
    if (permission === 'unsupported') return
    navigator.serviceWorker.ready
      .then((reg) => reg.pushManager.getSubscription())
      .then((sub) => setSubscribed(!!sub))
      .catch(() => setSubscribed(false))
  }, [permission])

  const subscribe = useCallback(async (): Promise<boolean> => {
    if (permission === 'unsupported') return false
    const env = await api.get<EnvResponse>('/env').then((r) => r.data)
    if (!env.vapid_public_key) {
      console.warn('VAPID public key not configured on backend')
      return false
    }

    const perm = await Notification.requestPermission()
    setPermission(perm as Permission)
    if (perm !== 'granted') return false

    const reg = await navigator.serviceWorker.ready
    // TS lib.dom requires ArrayBufferView<ArrayBuffer>, but Uint8Array's buffer
    // type is `ArrayBufferLike` which can include SharedArrayBuffer.
    // Cast — at runtime this is always a regular ArrayBuffer.
    const sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(
        env.vapid_public_key,
      ) as BufferSource,
    })
    const json = sub.toJSON() as {
      endpoint?: string
      keys?: { p256dh?: string; auth?: string }
    }
    if (!json.endpoint || !json.keys?.p256dh || !json.keys?.auth) {
      console.warn('subscribe(): malformed subscription', json)
      return false
    }
    await pushApi.subscribe({
      endpoint: json.endpoint,
      keys: { p256dh: json.keys.p256dh, auth: json.keys.auth },
      user_agent: navigator.userAgent.slice(0, 256),
    })
    // Отметка «человек включал уведомления» — по ней тихая переподписка знает,
    // что подписку МОЖНО восстанавливать. Разрешения браузера для этого мало:
    // оно остаётся `granted` и после нашей кнопки «Отключить».
    markOptedIn(employeeId)
    setSubscribed(true)
    return true
  }, [permission, employeeId])

  const unsubscribe = useCallback(async () => {
    if (permission === 'unsupported') return
    const reg = await navigator.serviceWorker.ready
    const sub = await reg.pushManager.getSubscription()
    if (sub) {
      const endpoint = sub.endpoint
      await sub.unsubscribe()
      try {
        await pushApi.unsubscribe(endpoint)
      } catch {
        // Best-effort — server might have cleaned it up already.
      }
    }
    // Снимаем отметку ДО setSubscribed: иначе тихая переподписка при следующем
    // запуске вернула бы то, что человек только что выключил.
    markOptedOut()
    setSubscribed(false)
  }, [permission])

  return { permission, subscribed, subscribe, unsubscribe }
}
