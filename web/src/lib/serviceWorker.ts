/**
 * Регистрация и жизненный цикл service worker'а — своими руками, без
 * `virtual:pwa-register` (25.09).
 *
 * Плагин vite-plugin-pwa в режиме `prompt` после события `waiting` вешал
 * `controlling → window.location.reload()`: клик «Обновить» в одной вкладке
 * перезагружал ВСЕ вкладки браузера, увидевшие ожидающий воркер, — и это была
 * жалоба «работа пропадает, хотя кнопку не нажимали». Здесь `controllerchange`
 * только обновляет снимок состояния. Перезагружает страницу ровно один код —
 * путь кнопки (`lib/appUpdate.ts`).
 *
 * Правила (`lib/swPolicy.ts`, разбор там же):
 * - `register()` только когда регистрации нет: при живой регистрации это
 *   задание Update с фетчем `sw.js` от имени страницы — лишнее окно для
 *   зависания очереди WebKit при F5 в первые секунды;
 * - проб (`update()`) мало: через 5 с после загрузки, по смене версии
 *   сервера, повтор при провале установки; никогда после вердикта «завис»;
 * - здоровье регистрации меряется ВИДИМЫМ временем ожидания пробы;
 * - ожидающий воркер активируется тихо (`SKIP_WAITING`); воркер сам проверяет
 *   пингом, что все окна на новом бандле, и иначе ждёт.
 *
 * Зависимости инъецируются ради тестов (vitest без jsdom): `navigator`,
 * таймеры, видимость, чистка прекеша.
 */

import { purgePrecachedShell } from './precacheShell'
import { SKIP_WAITING } from './swMessages'
import {
  createVisibleClock,
  decideProbe,
  nextSwHealth,
  PROBE_MAX_RETRIES,
  PROBE_RETRY_DELAY_MS,
  type ProbeTrigger,
  SILENT_ACTIVATION,
  STARTUP_LOOKUP_MS,
  STARTUP_PROBE_DELAY_MS,
  type VisibleClock,
} from './swPolicy'
import { EMPTY_SNAPSHOT, type SwStatusState, type SwStatusStore, useSwStatus } from './swStatusStore'
import { TIMEOUT, withTimeout } from './withTimeout'

export interface SwWorkerLike {
  state: string
  postMessage(message: unknown): void
  addEventListener(type: 'statechange', listener: () => void): void
}

export interface SwRegistrationLike {
  installing: SwWorkerLike | null
  waiting: SwWorkerLike | null
  active: SwWorkerLike | null
  update(): Promise<unknown>
  addEventListener(type: 'updatefound', listener: () => void): void
}

export interface SwContainerLike {
  controller: unknown
  getRegistration(scope?: string): Promise<SwRegistrationLike | undefined>
  register(url: string, options: { scope: string }): Promise<SwRegistrationLike>
  addEventListener(type: 'controllerchange', listener: () => void): void
}

export interface SwDeps {
  container: SwContainerLike | undefined
  /** В dev-сборке `sw.js` нет (`devOptions.enabled: false`) — регистрировать нечего. */
  prod: boolean
  now: () => number
  setTimeout: (fn: () => void, ms: number) => unknown
  clearTimeout: (id: unknown) => void
  setInterval: (fn: () => void, ms: number) => unknown
  clearInterval: (id: unknown) => void
  isVisible: () => boolean
  onVisibilityChange: (listener: () => void) => void
  online: () => boolean
  path: () => string
  purge: () => Promise<unknown>
  silentActivation: boolean
  store: SwStatusStore
  /** Вердикт «регистрация зависла» — один раз на загрузку страницы. */
  onHung: () => void
}

/** Шаг проверки «висит ли проба» — секунда, чтобы вердикт не опаздывал. */
const HUNG_TICK_MS = 1000

export interface SwController {
  install(): Promise<void>
  noteServerVersion(version: string, now: number): void
  settleInFlightUpdate(maxMs: number): Promise<void>
  requestActivation(): void
  probeInFlight(): boolean
  waitingWorker(): SwWorkerLike | null
}

export function createServiceWorkerController(deps: SwDeps): SwController {
  const { store } = deps
  let registration: SwRegistrationLike | null = null
  let inFlight: Promise<'settled' | 'rejected'> | null = null
  let startupProbePending = true
  let retries = 0
  let hungTicker: unknown = null
  let clock: VisibleClock | null = null
  const watched = new WeakSet<SwWorkerLike>()

  const patch = (partial: Partial<Omit<SwStatusState, 'patch'>>) => store.getState().patch(partial)

  const refreshSnapshot = () => {
    patch({
      snapshot: {
        supported: true,
        controlled: deps.container?.controller != null,
        active: registration?.active != null,
        waiting: registration?.waiting != null,
        installing: registration?.installing != null,
      },
    })
  }

  const requestActivation = () => {
    if (!deps.silentActivation) return
    const waiting = registration?.waiting
    if (!waiting) return
    try {
      waiting.postMessage({ type: SKIP_WAITING })
    } catch {
      // Воркер уже сменился или закрыт — следующий повод пришлёт снова.
    }
  }

  const stopHungTicker = () => {
    if (hungTicker !== null) deps.clearInterval(hungTicker)
    hungTicker = null
  }

  const startHungTicker = () => {
    stopHungTicker()
    hungTicker = deps.setInterval(() => {
      if (clock === null || inFlight === null) {
        stopHungTicker()
        return
      }
      const state = store.getState()
      if (state.health === 'hung') {
        stopHungTicker()
        return
      }
      const health = nextSwHealth(state.health, {
        result: 'timeout',
        visibleMs: clock.elapsedVisible(deps.now()),
      })
      if (health === 'hung') {
        patch({ health, hungAt: deps.now() })
        stopHungTicker()
        deps.onHung()
      }
    }, HUNG_TICK_MS)
  }

  const scheduleRetry = () => {
    if (retries >= PROBE_MAX_RETRIES) return
    deps.setTimeout(() => runProbe('retry'), PROBE_RETRY_DELAY_MS)
  }

  const watchInstalling = (worker: SwWorkerLike) => {
    if (watched.has(worker)) return
    watched.add(worker)
    worker.addEventListener('statechange', () => {
      refreshSnapshot()
      if (worker.state === 'installed') {
        retries = 0
        requestActivation()
      } else if (worker.state === 'redundant') {
        scheduleRetry()
      }
    })
  }

  function runProbe(trigger: ProbeTrigger): void {
    if (!registration) return
    const state = store.getState()
    const allowed = decideProbe({
      trigger,
      health: state.health,
      inFlight: inFlight !== null,
      visible: deps.isVisible(),
      online: deps.online(),
      path: deps.path(),
      lastProbeAt: state.lastProbeAt,
      now: deps.now(),
      seenVersion: state.seenVersion,
      probedVersion: state.probedVersion,
      retries,
    })
    if (!allowed) return
    startupProbePending = false
    if (trigger === 'retry') retries += 1
    const startedAt = deps.now()
    patch({ probeStartedAt: startedAt, lastProbeAt: startedAt, probedVersion: state.seenVersion })
    clock = createVisibleClock(startedAt, deps.isVisible())
    const probe: Promise<'settled' | 'rejected'> = registration.update().then(
      () => 'settled' as const,
      () => 'rejected' as const,
    )
    inFlight = probe
    startHungTicker()
    void probe.then((result) => {
      if (inFlight === probe) inFlight = null
      stopHungTicker()
      const visibleMs = clock?.elapsedVisible(deps.now()) ?? 0
      const health = nextSwHealth(store.getState().health, { result, visibleMs })
      patch({ health, probeStartedAt: null, ...(health === 'ok' ? { hungAt: null } : {}) })
      refreshSnapshot()
      if (result === 'rejected') scheduleRetry()
      requestActivation()
      runProbe('settled')
    })
  }

  const onVisibility = () => {
    const visible = deps.isVisible()
    clock?.note(visible, deps.now())
    if (!visible) return
    requestActivation()
    runProbe(startupProbePending ? 'startup' : 'visible')
  }

  const install = async (): Promise<void> => {
    if (!deps.prod || !deps.container) {
      patch({ snapshot: { ...EMPTY_SNAPSHOT, supported: false }, purgeSettled: true })
      return
    }
    const container = deps.container
    void Promise.resolve()
      .then(() => deps.purge())
      .catch(() => undefined)
      .then(() => patch({ purgeSettled: true }))

    let reg: SwRegistrationLike | undefined
    const looked = await withTimeout(
      container.getRegistration('/').catch(() => undefined),
      STARTUP_LOOKUP_MS,
    )
    if (looked === TIMEOUT) patch({ lookupTimedOut: true })
    else reg = looked
    if (!reg) {
      try {
        reg = await container.register('/sw.js', { scope: '/' })
      } catch {
        // Регистрация не удалась (CSP, приватный режим) — push и прекеш
        // недоступны, приложение работает из сети как обычно.
        return
      }
    }
    registration = reg
    container.addEventListener('controllerchange', refreshSnapshot)
    reg.addEventListener('updatefound', () => {
      if (registration?.installing) watchInstalling(registration.installing)
      refreshSnapshot()
    })
    // Страница перезагрузилась посреди установки: `updatefound` для этого
    // воркера уже отгремел в прошлом документе, ловим его состояние сами.
    if (reg.installing) watchInstalling(reg.installing)
    refreshSnapshot()
    requestActivation()
    deps.onVisibilityChange(onVisibility)
    deps.setTimeout(() => runProbe('startup'), STARTUP_PROBE_DELAY_MS)
  }

  return {
    install,
    noteServerVersion(version, now) {
      const state = store.getState()
      patch({ polled: { version, at: now } })
      if (version === state.seenVersion) return
      patch({ seenVersion: version })
      retries = 0
      runProbe('version-changed')
    },
    settleInFlightUpdate(maxMs) {
      if (inFlight === null) return Promise.resolve()
      return withTimeout(inFlight, maxMs).then(() => undefined)
    },
    requestActivation,
    probeInFlight: () => inFlight !== null,
    waitingWorker: () => registration?.waiting ?? null,
  }
}

let controller: SwController | null = null

function realDeps(): SwDeps {
  const hasContainer = typeof navigator !== 'undefined' && 'serviceWorker' in navigator
  return {
    container: hasContainer ? (navigator.serviceWorker as unknown as SwContainerLike) : undefined,
    prod: import.meta.env.PROD,
    now: () => Date.now(),
    setTimeout: (fn, ms) => window.setTimeout(fn, ms),
    clearTimeout: (id) => window.clearTimeout(id as number),
    setInterval: (fn, ms) => window.setInterval(fn, ms),
    clearInterval: (id) => window.clearInterval(id as number),
    isVisible: () => document.visibilityState === 'visible',
    onVisibilityChange: (listener) => document.addEventListener('visibilitychange', listener),
    online: () => navigator.onLine,
    path: () => window.location.pathname,
    purge: () => purgePrecachedShell(),
    silentActivation: SILENT_ACTIVATION,
    store: useSwStatus,
    onHung: () => undefined,
  }
}

/** Единственная регистрация воркера в приложении — зовётся из `main.tsx` до React. */
export function installServiceWorker(overrides: Partial<SwDeps> = {}): void {
  if (controller) return
  controller = createServiceWorkerController({ ...realDeps(), ...overrides })
  void controller.install()
}

/** Опрос баннера сообщает версию сервера — от неё запускаются пробы. */
export function noteServerVersion(version: string, now: number = Date.now()): void {
  controller?.noteServerVersion(version, now)
}

/** Перед перезагрузкой: дождаться НАШЕЙ пробы, чтобы не оборвать рукопожатие с воркером. */
export function settleInFlightUpdate(maxMs: number): Promise<void> {
  return controller?.settleInFlightUpdate(maxMs) ?? Promise.resolve()
}

export function probeInFlight(): boolean {
  return controller?.probeInFlight() ?? false
}

export function waitingWorker(): SwWorkerLike | null {
  return controller?.waitingWorker() ?? null
}

/** Только для тестов. */
export function _resetServiceWorkerForTests(): void {
  controller = null
}
