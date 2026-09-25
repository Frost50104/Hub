/**
 * Диагностика обновления с устройства — `POST /api/diag`.
 *
 * Разбор 25.09 занял форензику nginx-логов за неделю, потому что с устройства
 * не приходило ничего. Теперь страница присылает состояние регистрации и
 * тайминги каждого нажатия «Обновить»; на сервере это строка `client_diag`
 * в журнале (`journalctl -u signaris-hub | grep client_diag`).
 *
 * Поле называется `kind`, а не `event`: у structlog первый позиционный
 * аргумент `log.info("client_diag", …)` и есть `event`, и распаковка
 * payload'а с таким ключом роняла бы ручку в 500.
 *
 * Отправка — голым `fetch` с `keepalive`, как `lib/session.ts::revokePushBinding`:
 * перед перезагрузкой запрос обязан пережить выгрузку документа, а
 * axios-инстанс на 401 зовёт `startLogin()` и увёл бы человека на вход посреди
 * клика. Ошибки глотаются: диагностика никогда не мешает обновлению.
 */

import type { SwHealth } from './swPolicy'
import type { SwSnapshot } from './swStatusStore'

export type SwDiagKind = 'sw_hung' | 'sw_recovered' | 'update_click'

export type DiagStepName = 'lookup' | 'version' | 'token' | 'inflight' | 'activate' | 'purge'
export type DiagStepResult = 'ok' | 'timeout' | 'error' | 'skipped'

export interface DiagStep {
  name: DiagStepName
  ms: number
  result: DiagStepResult
}

export interface SwDiagPayload {
  kind: SwDiagKind
  ts: string
  app: { loaded: string; server: string | null; mode: string }
  env: {
    ua: string
    standalone: boolean
    online: boolean
    visible: boolean
    path: string
    page_age_ms: number
  }
  sw: {
    supported: boolean
    controlled: boolean
    active: boolean
    waiting: boolean
    installing: boolean
    health: SwHealth
    probe_age_ms: number | null
    hung_after_ms: number | null
    lookup_timed_out: boolean
  }
  click?: { action: string; total_ms: number; steps: DiagStep[] }
}

/** Потолок тела: `keepalive`-запросы ограничены 64 КБ на всё; нам хватает 2. */
export const DIAG_MAX_BYTES = 2048
const UA_MAX = 200
const PATH_MAX = 200

export interface SwDiagInput {
  kind: SwDiagKind
  now: number
  loadedVersion: string
  serverVersion: string | null
  mode: string
  ua: string
  standalone: boolean
  online: boolean
  visible: boolean
  path: string
  pageLoadedAt: number
  snapshot: SwSnapshot
  health: SwHealth
  probeStartedAt: number | null
  hungAt: number | null
  lookupTimedOut: boolean
  click?: { action: string; totalMs: number; steps: DiagStep[] }
}

export function buildSwDiag(input: SwDiagInput): SwDiagPayload {
  const payload: SwDiagPayload = {
    kind: input.kind,
    ts: new Date(input.now).toISOString(),
    app: { loaded: input.loadedVersion, server: input.serverVersion, mode: input.mode },
    env: {
      ua: input.ua.slice(0, UA_MAX),
      standalone: input.standalone,
      online: input.online,
      visible: input.visible,
      path: input.path.slice(0, PATH_MAX),
      page_age_ms: Math.max(0, Math.round(input.now - input.pageLoadedAt)),
    },
    sw: {
      supported: input.snapshot.supported,
      controlled: input.snapshot.controlled,
      active: input.snapshot.active,
      waiting: input.snapshot.waiting,
      installing: input.snapshot.installing,
      health: input.health,
      probe_age_ms: input.probeStartedAt === null ? null : Math.max(0, Math.round(input.now - input.probeStartedAt)),
      hung_after_ms: input.hungAt === null ? null : Math.max(0, Math.round(input.hungAt - input.pageLoadedAt)),
      lookup_timed_out: input.lookupTimedOut,
    },
  }
  if (input.click) {
    payload.click = {
      action: input.click.action,
      total_ms: Math.round(input.click.totalMs),
      steps: input.click.steps.map((s) => ({ name: s.name, ms: Math.round(s.ms), result: s.result })),
    }
  }
  return payload
}

export function diagByteLength(payload: SwDiagPayload): number {
  return new TextEncoder().encode(JSON.stringify(payload)).length
}

export type FetchLike = (
  url: string,
  init: { method: string; headers: Record<string, string>; body: string; keepalive: boolean },
) => Promise<unknown>

/**
 * Отправить и забыть. Без токена — не шлём (`/auth/callback`, киоск);
 * слишком длинное тело — тоже (ручка ответила бы 422, а мы не узнали бы почему).
 */
export function sendSwDiag(payload: SwDiagPayload, token: string | null, fetchImpl: FetchLike): void {
  if (!token) return
  const body = JSON.stringify(payload)
  if (new TextEncoder().encode(body).length > DIAG_MAX_BYTES) return
  try {
    void fetchImpl('/api/diag', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'X-Auth-Mode': 'api',
        'Content-Type': 'application/json',
      },
      body,
      keepalive: true,
    }).catch(() => undefined)
  } catch {
    // Диагностика — фон; сюда попадаем только при синхронном броске fetch.
  }
}
