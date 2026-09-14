import { authClient } from '@/lib/auth'
import { clearDeviceState } from '@/lib/deviceState'

/**
 * Выход из аккаунта: единственная точка на всё приложение.
 *
 * До этого логаут был четырьмя независимыми `authClient.logout()` и не оставлял
 * после себя ничего, кроме чистого IndexedDB с токенами — на общем устройстве
 * следующий вошедший наследовал тему предыдущего, его свёрнутые папки и
 * настройки колонок по UUID чужих проектов (ОС 09.09). Что именно чистится и
 * что НЕ чистится — в `lib/deviceState.ts`.
 */

function withTimeout(task: Promise<unknown>, ms: number): Promise<unknown> {
  return Promise.race([
    task.catch(() => undefined),
    new Promise((resolve) => setTimeout(resolve, ms)),
  ])
}

/**
 * Снять привязку push-подписки этого браузера к уходящему человеку.
 *
 * Браузерную подписку НЕ отменяем (`sub.unsubscribe()` здесь нет) — она
 * переиспользуется при следующем входе, и благодаря этому вернувшемуся не
 * нужно включать уведомления заново. Снимается ровно строка на сервере.
 *
 * Голый `fetch`, а не `pushApi.unsubscribe`: axios-инстанс несёт интерцептор
 * `attachAxiosAuth`, который на 401 пытается refresh и при его провале делает
 * `startLogin()` — то есть уводит на страницу входа. Человек, нажавший «Выйти»
 * с протухшей сессией, оказался бы обратно в приложении.
 *
 * `keepalive` — чтобы запрос дожил до сервера, даже если редирект логаута
 * случится раньше ответа.
 */
async function revokePushBinding(): Promise<void> {
  if (typeof navigator === 'undefined' || !('serviceWorker' in navigator)) return
  // getRegistration(), а НЕ ready: на iOS `ready` может не резолвиться, пока
  // service worker не активен, и выход подвис бы на неразрешимом промисе.
  const reg = await navigator.serviceWorker.getRegistration()
  const endpoint = (await reg?.pushManager.getSubscription())?.endpoint
  if (!endpoint) return
  const token = await authClient.getAccessToken()
  // Токена нет — отзывать нечем; перепривязку сделает следующий вошедший
  // (`usePushAutoRefresh` видит смену владельца и обходит троттл).
  if (!token) return
  await fetch(`/api/push/subscribe?endpoint=${encodeURIComponent(endpoint)}`, {
    method: 'DELETE',
    headers: { Authorization: `Bearer ${token}`, 'X-Auth-Mode': 'api' },
    keepalive: true,
  })
}

/**
 * Выйти: отозвать push-привязку, стереть следы человека на устройстве, уйти на
 * SSO-логаут. Порядок обязателен — `authClient.logout()` уводит браузер через
 * `window.location.href`, и всё, что после него, не исполнится.
 */
export async function logoutWithDeviceCleanup(): Promise<void> {
  await withTimeout(revokePushBinding(), 2000)
  clearDeviceState()
  await authClient.logout()
}
