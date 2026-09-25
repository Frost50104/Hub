/**
 * Путь кнопки «Обновить» (баннер и «Обновить приложение» в Настройках) —
 * оркестратор с инъекцией зависимостей; правила — `lib/swPolicy.ts`.
 *
 * Прежний путь ждал `registration.update()` до 8 с и установку воркера до
 * 20 с; в Safari с зависшей регистрацией это давало ровно 30 с на каждый
 * клик (замер 25.09). Теперь обновление приложения — это перезагрузка
 * страницы: HTML не в прекеше, свежий бандл приходит из сети при любом
 * состоянии воркера, а сам воркер догоняет в фоне (`lib/serviceWorker.ts`).
 *
 * Каждый `await` здесь — с потолком. Итог клика уходит в диагностику
 * (`lib/swDiag.ts`) ДО перезагрузки, `keepalive`-запросом без ожидания.
 */

import type { DiagStep, DiagStepName, SwDiagPayload } from './swDiag'
import { buildSwDiag } from './swDiag'
import { SKIP_WAITING } from './swMessages'
import {
  CONTROLLER_WAIT_MS,
  decideUpdateClick,
  INFLIGHT_SETTLE_MS,
  PURGE_MS,
  REGISTRATION_LOOKUP_MS,
  TOKEN_LOOKUP_MS,
  type UpdateClickAction,
  VERSION_FETCH_MS,
} from './swPolicy'
import type { SwStatusStore } from './swStatusStore'
import { TIMEOUT, withTimeout } from './withTimeout'

export type AppUpdateStatus = 'idle' | 'checking' | 'applying'

export interface WaitingWorkerLike {
  postMessage(message: unknown): void
}

export interface UpdateClickDeps {
  now: () => number
  online: () => boolean
  loadedVersion: string
  mode: string
  /** Снимок регистрации: нужен только `waiting`. `undefined` — регистрации нет. */
  getRegistration: () => Promise<{ waiting: WaitingWorkerLike | null } | undefined>
  /** `/version.json` → версия; `null` — не 2xx; отказ/таймаут — недоступен. */
  fetchVersion: () => Promise<string | null>
  getToken: () => Promise<string | null>
  store: SwStatusStore
  probeInFlight: () => boolean
  settleInFlight: (maxMs: number) => Promise<unknown>
  waitForController: (maxMs: number) => Promise<unknown>
  purge: () => Promise<unknown>
  reload: () => void
  sendDiag: (payload: SwDiagPayload, token: string | null) => void
  env: () => { ua: string; standalone: boolean; visible: boolean; path: string }
  setStatus: (status: AppUpdateStatus) => void
  silentActivation?: boolean
}

export interface UpdateClickOutcome {
  action: UpdateClickAction
  steps: DiagStep[]
  totalMs: number
}

type Timed<T> = { kind: 'ok'; value: T } | { kind: 'timeout' } | { kind: 'error' }

async function timed<T>(
  steps: DiagStep[],
  deps: Pick<UpdateClickDeps, 'now'>,
  name: DiagStepName,
  promise: Promise<T>,
  maxMs: number,
): Promise<Timed<T>> {
  const started = deps.now()
  const guarded: Promise<Timed<T>> = promise.then(
    (value) => ({ kind: 'ok' as const, value }),
    () => ({ kind: 'error' as const }),
  )
  const result = await withTimeout(guarded, maxMs)
  const outcome: Timed<T> = result === TIMEOUT ? { kind: 'timeout' } : result
  steps.push({ name, ms: deps.now() - started, result: outcome.kind })
  return outcome
}

export async function runUpdateClick(deps: UpdateClickDeps): Promise<UpdateClickOutcome> {
  const t0 = deps.now()
  const steps: DiagStep[] = []
  deps.setStatus('checking')

  const [lookup, fetched, token] = await Promise.all([
    timed(steps, deps, 'lookup', deps.getRegistration(), REGISTRATION_LOOKUP_MS),
    timed(steps, deps, 'version', deps.fetchVersion(), VERSION_FETCH_MS),
    timed(steps, deps, 'token', deps.getToken(), TOKEN_LOOKUP_MS),
  ])
  const waiting = lookup.kind === 'ok' ? (lookup.value?.waiting ?? null) : null
  const fetchedVersion: Parameters<typeof decideUpdateClick>[0]['fetched'] =
    fetched.kind === 'ok' && typeof fetched.value === 'string'
      ? { kind: 'version', version: fetched.value }
      : { kind: 'unreachable' }
  const tokenValue = token.kind === 'ok' ? token.value : null

  const state = deps.store.getState()
  const action = decideUpdateClick({
    online: deps.online(),
    loadedVersion: deps.loadedVersion,
    fetched: fetchedVersion,
    polled: state.polled,
    now: deps.now(),
    waiting: waiting !== null,
    health: state.health,
    probeInFlight: deps.probeInFlight(),
    silentActivation: deps.silentActivation,
  })

  const activate = () => {
    if (!waiting) return
    try {
      waiting.postMessage({ type: SKIP_WAITING })
    } catch {
      // Воркер уже сменился — перезагрузка всё равно принесёт свежий бандл.
    }
  }

  const diag = (): SwDiagPayload => {
    const s = deps.store.getState()
    const env = deps.env()
    return buildSwDiag({
      kind: 'update_click',
      now: deps.now(),
      loadedVersion: deps.loadedVersion,
      serverVersion: fetchedVersion.kind === 'version' ? fetchedVersion.version : (s.polled?.version ?? null),
      mode: deps.mode,
      ua: env.ua,
      standalone: env.standalone,
      online: deps.online(),
      visible: env.visible,
      path: env.path,
      pageLoadedAt: s.pageLoadedAt,
      snapshot: s.snapshot,
      health: s.health,
      probeStartedAt: s.probeStartedAt,
      hungAt: s.hungAt,
      lookupTimedOut: s.lookupTimedOut,
      click: {
        action: action.kind === 'toast' ? `toast-${action.reason}` : 'reload',
        totalMs: deps.now() - t0,
        steps,
      },
    })
  }

  if (action.kind === 'toast') {
    if (action.activateWaiting) activate()
    deps.setStatus('idle')
    deps.sendDiag(diag(), tokenValue)
    return { action, steps, totalMs: deps.now() - t0 }
  }

  deps.setStatus('applying')
  if (action.awaitInFlight) {
    await timed(steps, deps, 'inflight', deps.settleInFlight(INFLIGHT_SETTLE_MS), INFLIGHT_SETTLE_MS + 100)
  } else {
    steps.push({ name: 'inflight', ms: 0, result: 'skipped' })
  }
  if (action.activateWaiting) {
    activate()
    await timed(steps, deps, 'activate', deps.waitForController(CONTROLLER_WAIT_MS), CONTROLLER_WAIT_MS + 100)
  } else {
    steps.push({ name: 'activate', ms: 0, result: 'skipped' })
  }
  if (deps.store.getState().purgeSettled) {
    steps.push({ name: 'purge', ms: 0, result: 'skipped' })
  } else {
    await timed(steps, deps, 'purge', deps.purge(), PURGE_MS)
  }
  deps.sendDiag(diag(), tokenValue)
  deps.reload()
  return { action, steps, totalMs: deps.now() - t0 }
}
