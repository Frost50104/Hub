/// <reference lib="webworker" />
/// <reference types="vite-plugin-pwa/client" />

import { precacheAndRoute } from 'workbox-precaching'

declare const self: ServiceWorkerGlobalScope

// Inject manifest from vite-plugin-pwa build step.
precacheAndRoute(self.__WB_MANIFEST)

// SKIP_WAITING — посылается из UpdateBanner после нажатия пользователем «Обновить».
self.addEventListener('message', (e) => {
  if (e.data && e.data.type === 'SKIP_WAITING') {
    self.skipWaiting()
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

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const targetUrl =
    (event.notification.data as { url?: string } | null)?.url ?? '/'
  event.waitUntil(
    self.clients.matchAll({ type: 'window' }).then((clients) => {
      for (const client of clients) {
        const url = new URL(client.url)
        if (url.origin === self.location.origin) {
          void client.focus()
          if ('navigate' in client) {
            void (client as WindowClient).navigate(targetUrl)
          }
          return
        }
      }
      void self.clients.openWindow(targetUrl)
    }),
  )
})
