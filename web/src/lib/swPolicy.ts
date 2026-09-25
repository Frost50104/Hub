/**
 * Правила обновления приложения и жизненного цикла service worker'а —
 * чистые функции без DOM (vitest здесь без jsdom).
 *
 * Разбор 25.09 (журнал nginx за 20–25.09, исходники WebKit): в Safari
 * владельца регистрация воркера прода зависла 20.09 — очередь заданий
 * регистрации в WebKit строго последовательная, а установка ждёт подтверждения
 * промиса от СТРАНИЦЫ (`SWServerJobQueue::install`, FIXME на bug 215122);
 * задание, чья страница ушла на перезагрузку, висит навсегда. В таком
 * состоянии `registration.update()` не резолвится и не запрашивает `sw.js`,
 * а прежний путь кнопки ждал его 8 с, потом 20 с ждал `installed` —
 * ровно те 30 с, на которые жаловались.
 *
 * Отсюда два правила, которые здесь закреплены:
 * 1. Путь кнопки НИКОГДА не создаёт заданий воркера (`update()`/`register()`)
 *    и не ждёт установки — обновление приложения = перезагрузка страницы,
 *    HTML в прекеше нет с 21.09, свежий бандл приходит из сети при любом
 *    состоянии воркера.
 * 2. Проб воркера мало и они предсказуемы: одна после загрузки, одна на
 *    каждый выкат, повтор при провале — не 30-секундный опрос, каждое
 *    задание которого зависит от живого документа.
 */

/** Потолок `getRegistration()` в пути кнопки. Не зависал ни разу, потолок — по правилу 16.09. */
export const REGISTRATION_LOOKUP_MS = 1000
/** Потолок `getRegistration()` на старте: при таймауте регистрируем заново. */
export const STARTUP_LOOKUP_MS = 2000
/** Потолок `fetch('/version.json')` вместе с разбором тела. */
export const VERSION_FETCH_MS = 3000
/** Потолок чтения токена для диагностики (IndexedDB). */
export const TOKEN_LOOKUP_MS = 500
/** Сколько ждём НАШУ пробу в полёте перед перезагрузкой — см. `decideUpdateClick`. */
export const INFLIGHT_SETTLE_MS = 1500
/** Ожидание смены контроллера после SKIP_WAITING на клике; iOS PWA события иногда не шлёт. */
export const CONTROLLER_WAIT_MS = 1000
/** Потолок чистки прекеша перед перезагрузкой (пре-21.09 воркер держит index.html). */
export const PURGE_MS = 2000
/** Видимого времени без ответа `update()`, после которого регистрация считается зависшей. */
export const PROBE_HUNG_MS = 20_000
/** Минимальный шаг между пробами — равен опросу `version.json`. */
export const PROBE_MIN_INTERVAL_MS = 30_000
/** Первая проба — после того, как страница прожила несколько секунд (вне окна F5). */
export const STARTUP_PROBE_DELAY_MS = 5000
/** Повтор после провала установки (404 чанка посреди rsync, обрыв сети). */
export const PROBE_RETRY_DELAY_MS = 45_000
export const PROBE_MAX_RETRIES = 2
/**
 * Перепроверка вердикта «завис»: одна проба через 5 минут (и одна на смену
 * версии). Опыт 25.09: на iPhone проба, поставленная в очередь позади идущей
 * установки, не завершилась за 20 с, хотя очередь дальше работала — без
 * перепроверки подсказка «перезапустите браузер» жила бы до перезагрузки.
 */
export const HUNG_RECHECK_MS = 5 * 60_000
/** Сколько живёт опрошенная баннером версия как замена недоступному `version.json`. */
export const POLLED_VERSION_FRESH_MS = 60_000
/** Тихая активация ожидающего воркера (решение владельца 25.09). Откат — одна строка. */
export const SILENT_ACTIVATION = true

export type SwHealth = 'unknown' | 'ok' | 'hung'

export interface PolledVersion {
  version: string
  at: number
}

export interface UpdateClickInput {
  online: boolean
  loadedVersion: string
  /** Ответ `/version.json` на клике; `unreachable` — таймаут, сеть, не-2xx. */
  fetched: { kind: 'version'; version: string } | { kind: 'unreachable' }
  /** Последний успешный опрос баннера — замена недоступному ответу. */
  polled: PolledVersion | null
  now: number
  waiting: boolean
  health: SwHealth
  probeInFlight: boolean
  silentActivation?: boolean
}

export type UpdateClickAction =
  | { kind: 'toast'; reason: 'offline' | 'unreachable' | 'latest' | 'latest-hung'; activateWaiting: boolean }
  | { kind: 'reload'; awaitInFlight: boolean; activateWaiting: boolean }

/** Версия сервера, которой верим на клике: ответ сейчас, иначе свежий опрос баннера. */
export function serverVersionForClick(
  fetched: UpdateClickInput['fetched'],
  polled: PolledVersion | null,
  now: number,
): string | null {
  if (fetched.kind === 'version') return fetched.version
  if (polled && now - polled.at < POLLED_VERSION_FRESH_MS) return polled.version
  return null
}

/**
 * Что делать по клику «Обновить».
 *
 * `awaitInFlight` — единственное место, где кнопка считается с воркером: если
 * НАША проба (`update()`) ещё не резолвилась, перезагрузка попала бы в окно
 * между резолвом промиса в странице и подтверждением серверу — так очередь
 * WebKit и зависает. Ждём не дольше `INFLIGHT_SETTLE_MS`; в уже зависшем
 * браузере ждать нечего.
 */
export function decideUpdateClick(input: UpdateClickInput): UpdateClickAction {
  const silent = input.silentActivation ?? SILENT_ACTIVATION
  const activateWaiting = silent && input.waiting
  if (!input.online) return { kind: 'toast', reason: 'offline', activateWaiting: false }
  const server = serverVersionForClick(input.fetched, input.polled, input.now)
  if (server === null) return { kind: 'toast', reason: 'unreachable', activateWaiting: false }
  if (server !== input.loadedVersion) {
    if (input.health === 'hung') return { kind: 'reload', awaitInFlight: false, activateWaiting: false }
    return { kind: 'reload', awaitInFlight: input.probeInFlight, activateWaiting }
  }
  if (input.health === 'hung') return { kind: 'toast', reason: 'latest-hung', activateWaiting: false }
  return { kind: 'toast', reason: 'latest', activateWaiting }
}

export type ProbeTrigger =
  | 'startup'
  | 'version-changed'
  | 'visible'
  | 'settled'
  | 'retry'
  | 'install-finished'
  | 'recheck'

export interface ProbeInput {
  trigger: ProbeTrigger
  health: SwHealth
  inFlight: boolean
  visible: boolean
  online: boolean
  path: string
  lastProbeAt: number | null
  now: number
  /** Версия сервера по последнему опросу баннера (изначально — версия бандла). */
  seenVersion: string
  /** Версия, при которой стартовала последняя проба. */
  probedVersion: string
  retries: number
  /**
   * Идёт установка воркера (`registration.installing`). Проба в это время
   * встала бы в очередь WebKit позади установки — так и зависла проба на
   * iPhone 25.09. Ждём `install-finished`.
   */
  installing: boolean
  hungAt: number | null
}

/** Пути, где страница вот-вот выгрузится целиком (`/login` уходит на SSO полной навигацией). */
export function probeForbiddenOnPath(path: string): boolean {
  return path === '/login' || path.startsWith('/login/')
}

/** Запускать ли `registration.update()` сейчас. */
export function decideProbe(input: ProbeInput): boolean {
  if (input.inFlight || input.installing || !input.visible || !input.online) return false
  if (probeForbiddenOnPath(input.path)) return false
  const spaced = input.lastProbeAt === null || input.now - input.lastProbeAt >= PROBE_MIN_INTERVAL_MS
  if (input.health === 'hung') {
    // Зависшую очередь новыми заданиями не лечат, но вердикт может быть
    // ложным — перепроверяем редко: раз в HUNG_RECHECK_MS и на смену версии.
    if (input.trigger === 'recheck') {
      return input.hungAt !== null && input.now - input.hungAt >= HUNG_RECHECK_MS
    }
    if (input.trigger === 'version-changed') return spaced && input.seenVersion !== input.probedVersion
    return false
  }
  switch (input.trigger) {
    case 'startup':
      return input.lastProbeAt === null
    case 'install-finished':
      return input.lastProbeAt === null || (spaced && input.seenVersion !== input.probedVersion)
    case 'retry':
      return spaced && input.retries < PROBE_MAX_RETRIES
    case 'recheck':
      return false
    case 'version-changed':
    case 'visible':
    case 'settled':
      return spaced && input.seenVersion !== input.probedVersion
  }
}

export interface ProbeSample {
  result: 'settled' | 'rejected' | 'timeout'
  /** Сколько проба провисела при ВИДИМОЙ вкладке — фон iPhone не считается. */
  visibleMs: number
}

/**
 * Здоровье регистрации по итогу пробы. Любой ответ (в том числе отказ —
 * офлайн `TypeError`) доказывает, что очередь движется; после `hung`
 * возвращение в `ok` снимает подсказку и снова разрешает пробы.
 */
export function nextSwHealth(prev: SwHealth, sample: ProbeSample): SwHealth {
  if (sample.result === 'settled' || sample.result === 'rejected') return 'ok'
  return sample.visibleMs >= PROBE_HUNG_MS ? 'hung' : prev
}

/**
 * Счётчик видимого времени: накапливает только отрезки, когда вкладка была
 * видима. Замороженный в фоне iPhone или заторможенная скрытая вкладка Chrome
 * не должны давать ложное «завис».
 */
export interface VisibleClock {
  note(visible: boolean, now: number): void
  elapsedVisible(now: number): number
}

export function createVisibleClock(startedAt: number, visibleAtStart: boolean): VisibleClock {
  let accumulated = 0
  let visibleSince: number | null = visibleAtStart ? startedAt : null
  return {
    note(visible, now) {
      if (visible) {
        if (visibleSince === null) visibleSince = now
      } else if (visibleSince !== null) {
        accumulated += Math.max(0, now - visibleSince)
        visibleSince = null
      }
    },
    elapsedVisible(now) {
      return accumulated + (visibleSince === null ? 0 : Math.max(0, now - visibleSince))
    },
  }
}

/**
 * Десктопный Mac по UA: только там уместно советовать ⌘Q. iPad в «настольном»
 * режиме тоже представляется Macintosh — отличаем по отсутствию тача.
 */
export function isDesktopMacUa(ua: string, maxTouchPoints: number): boolean {
  return /Macintosh/.test(ua) && maxTouchPoints === 0
}

/** Подсказка при вердикте «завис»: Настройки (под версией) и тост правила 7. */
export function hungBrowserHint(desktopMac: boolean): string {
  const how = desktopMac ? 'Закройте браузер полностью (⌘Q в Safari) и откройте заново.' : 'Закройте браузер полностью и откройте заново.'
  return `Фоновое обновление приложения в этом браузере зависло. ${how} Кнопка «Обновить приложение» при этом работает как обычно.`
}
