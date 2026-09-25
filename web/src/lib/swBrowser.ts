/**
 * Браузерные зависимости пути кнопки и диагностики — всё, что трогает
 * `navigator`, `window`, `fetch` и клиент auth. Чистая логика живёт в
 * `lib/appUpdate.ts` и `lib/swDiag.ts` и тестируется без этого файла.
 */

import { authClient } from '@/lib/auth'

import type { AppUpdateStatus, UpdateClickDeps } from './appUpdate'
import { purgePrecachedShell } from './precacheShell'
import { probeInFlight, settleInFlightUpdate } from './serviceWorker'
import { buildSwDiag, sendSwDiag, type SwDiagPayload } from './swDiag'
import { SILENT_ACTIVATION, TOKEN_LOOKUP_MS } from './swPolicy'
import { useSwStatus } from './swStatusStore'
import { TIMEOUT, withTimeout } from './withTimeout'

/** `/version.json` с сервера; `null` — не 2xx. Сеть и таймаут решает вызывающий. */
export async function fetchServerVersion(): Promise<string | null> {
  const res = await fetch('/version.json', { cache: 'no-store' })
  if (!res.ok) return null
  const data = (await res.json()) as { version?: string }
  return data.version ?? null
}

/** Токен для диагностики; отказ хранилища — «токена нет». */
export function readToken(): Promise<string | null> {
  return authClient.getAccessToken().catch(() => null)
}

/**
 * Смена контроллера после SKIP_WAITING, не дольше `maxMs`: iOS PWA событие
 * иногда не шлёт, а воркер с защитным пингом может отложить активацию.
 */
export function waitForController(maxMs: number): Promise<void> {
  if (typeof navigator === 'undefined' || !('serviceWorker' in navigator)) return Promise.resolve()
  return new Promise((resolve) => {
    const done = () => {
      window.clearTimeout(timer)
      navigator.serviceWorker.removeEventListener('controllerchange', done)
      resolve()
    }
    const timer = window.setTimeout(done, maxMs)
    navigator.serviceWorker.addEventListener('controllerchange', done)
  })
}

export function browserEnv(): { ua: string; standalone: boolean; visible: boolean; path: string } {
  return {
    ua: navigator.userAgent,
    standalone: window.matchMedia?.('(display-mode: standalone)').matches ?? false,
    visible: document.visibilityState === 'visible',
    path: window.location.pathname,
  }
}

export function sendDiag(payload: SwDiagPayload, token: string | null): void {
  sendSwDiag(payload, token, (url, init) => fetch(url, init))
}

/** Вердикт «регистрация зависла» — один раз на загрузку страницы (`installServiceWorker({ onHung })`). */
export function reportSwHung(): void {
  const s = useSwStatus.getState()
  const env = browserEnv()
  const payload = buildSwDiag({
    kind: 'sw_hung',
    now: Date.now(),
    loadedVersion: __APP_VERSION__,
    serverVersion: s.polled?.version ?? null,
    mode: __APP_MODE__,
    ua: env.ua,
    standalone: env.standalone,
    online: navigator.onLine,
    visible: env.visible,
    path: env.path,
    pageLoadedAt: s.pageLoadedAt,
    snapshot: s.snapshot,
    health: s.health,
    probeStartedAt: s.probeStartedAt,
    hungAt: s.hungAt,
    lookupTimedOut: s.lookupTimedOut,
  })
  void withTimeout(readToken(), TOKEN_LOOKUP_MS).then((token) => sendDiag(payload, token === TIMEOUT ? null : token))
}

export function updateClickDeps(setStatus: (status: AppUpdateStatus) => void): UpdateClickDeps {
  return {
    now: () => Date.now(),
    online: () => navigator.onLine,
    loadedVersion: __APP_VERSION__,
    mode: __APP_MODE__,
    getRegistration: () =>
      'serviceWorker' in navigator ? navigator.serviceWorker.getRegistration() : Promise.resolve(undefined),
    fetchVersion: fetchServerVersion,
    getToken: readToken,
    store: useSwStatus,
    probeInFlight,
    settleInFlight: settleInFlightUpdate,
    waitForController,
    purge: purgePrecachedShell,
    reload: () => window.location.reload(),
    sendDiag,
    env: browserEnv,
    setStatus,
    silentActivation: SILENT_ACTIVATION,
  }
}
