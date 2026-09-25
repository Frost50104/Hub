/// <reference lib="webworker" />
/// <reference types="vite-plugin-pwa/client" />

import { precacheAndRoute } from 'workbox-precaching'

import {
  HUB_PONG,
  type MessageChannelLike,
  OPEN_URL_ACK,
  pickNotificationClient,
  postAndAwaitAck,
  SKIP_WAITING,
} from './lib/swMessages'

declare const self: ServiceWorkerGlobalScope

// Inject manifest from vite-plugin-pwa build step.
precacheAndRoute(self.__WB_MANIFEST)

/** Ответ окна на пинг: старый бандл (плагин) молчит, новый отвечает за миллисекунды. */
const PING_TIMEOUT_MS = 300
/** Подтверждение OPEN_URL: iOS PWA после заморозки отвечает не сразу. */
const OPEN_URL_ACK_TIMEOUT_MS = 4000

const ackDeps = {
  // `MessagePort.onmessage` типизирован полным MessageEvent — нам нужен только `data`.
  createChannel: () => new MessageChannel() as unknown as MessageChannelLike,
  setTimeout: (fn: () => void, ms: number) => self.setTimeout(fn, ms),
  clearTimeout: (id: unknown) => self.clearTimeout(id as number),
}

/**
 * Все ли окна отвечают на пинг. Окно на старом бандле не ответит никогда —
 * там на `controllerchange` стоит `reload()` плагина vite-plugin-pwa, и
 * активация сейчас перезагрузила бы его без клика. Тогда не активируемся:
 * новые страницы повторят SKIP_WAITING, когда старое окно закроется.
 */
async function everyWindowAnswers(): Promise<boolean> {
  const clients = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
  const answers = await Promise.all(
    clients.map((client) => postAndAwaitAck(client, { type: 'HUB_PING' }, HUB_PONG, PING_TIMEOUT_MS, ackDeps)),
  )
  return answers.every(Boolean)
}

// SKIP_WAITING шлёт страница: тихая активация из `lib/serviceWorker.ts` и
// путь кнопки `lib/appUpdate.ts`.
self.addEventListener('message', (event) => {
  if (event.data && event.data.type === SKIP_WAITING) {
    event.waitUntil(
      everyWindowAnswers().then((ok) => {
        if (ok) return self.skipWaiting()
        return undefined
      }),
    )
  }
})

type PushPayload = {
  title: string
  body: string
  url?: string
  kind?: string
}

self.addEventListener('push', (event) => {
  if (!event.data) return
  let payload: PushPayload
  try {
    payload = event.data.json() as PushPayload
  } catch {
    payload = { title: 'Signaris Hub', body: event.data.text() }
  }
  event.waitUntil(
    self.registration.showNotification(payload.title, {
      body: payload.body,
      icon: '/icons/icon-192.png',
      badge: '/icons/icon-192.png',
      data: { url: payload.url ?? '/' },
    }),
  )
})

/**
 * Открыть адрес уведомления в живом окне: сначала сообщением (страница
 * перейдёт SPA-маршрутом, документ цел), и только без ответа — полной
 * навигацией, как раньше (окно на старом бандле слушателя не имеет).
 */
async function openInClient(url: string, title: string): Promise<void> {
  const controlled = await self.clients.matchAll({ type: 'window' })
  const all = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
  const client = pickNotificationClient(controlled, all, self.location.origin)
  if (!client) {
    await self.clients.openWindow(url).catch(() => undefined)
    return
  }
  // Фокус — первым: право на него даёт клик по уведомлению.
  await client.focus().catch(() => undefined)
  const handled = await postAndAwaitAck(
    client,
    { type: 'OPEN_URL', url, title },
    OPEN_URL_ACK,
    OPEN_URL_ACK_TIMEOUT_MS,
    ackDeps,
  )
  if (handled) return
  try {
    await client.navigate(url)
  } catch {
    // Неконтролируемое окно (первый визит, hard reload) навигацию отвергает.
    await self.clients.openWindow(url).catch(() => undefined)
  }
}

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const targetUrl = (event.notification.data as { url?: string } | null)?.url ?? '/'
  event.waitUntil(openInClient(targetUrl, event.notification.title))
})
