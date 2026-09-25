import { describe, expect, it } from 'vitest'

import {
  createVisibleClock,
  decideProbe,
  decideUpdateClick,
  HUNG_RECHECK_MS,
  hungBrowserHint,
  isDesktopMacUa,
  nextSwHealth,
  PROBE_HUNG_MS,
  PROBE_MAX_RETRIES,
  PROBE_MIN_INTERVAL_MS,
  type ProbeInput,
  serverVersionForClick,
  type UpdateClickInput,
} from './swPolicy'

const LOADED = 'aaaaaaa-20260925-100000'
const NEWER = 'bbbbbbb-20260925-110000'
const NOW = 1_700_000_000_000

function click(over: Partial<UpdateClickInput> = {}): UpdateClickInput {
  return {
    online: true,
    loadedVersion: LOADED,
    fetched: { kind: 'version', version: NEWER },
    polled: null,
    now: NOW,
    waiting: false,
    health: 'ok',
    probeInFlight: false,
    silentActivation: true,
    ...over,
  }
}

describe('decideUpdateClick', () => {
  it('1: офлайн — тост, без перезагрузки и без активации', () => {
    expect(decideUpdateClick(click({ online: false, waiting: true }))).toEqual({
      kind: 'toast',
      reason: 'offline',
      activateWaiting: false,
    })
  })

  it('2: version.json недоступен и опроса нет — тост «не удалось проверить»', () => {
    expect(decideUpdateClick(click({ fetched: { kind: 'unreachable' } }))).toEqual({
      kind: 'toast',
      reason: 'unreachable',
      activateWaiting: false,
    })
  })

  it('2: опрос баннера старше минуты не заменяет недоступный ответ', () => {
    const polled = { version: NEWER, at: NOW - 61_000 }
    expect(decideUpdateClick(click({ fetched: { kind: 'unreachable' }, polled })).kind).toBe('toast')
  })

  it('2a: version.json недоступен, но баннер видел новую версию < 60 с назад — перезагрузка', () => {
    const polled = { version: NEWER, at: NOW - 20_000 }
    expect(decideUpdateClick(click({ fetched: { kind: 'unreachable' }, polled }))).toEqual({
      kind: 'reload',
      awaitInFlight: false,
      activateWaiting: false,
    })
  })

  it('3: версия отличается, регистрация зависла — перезагрузка сразу, пробу не ждём', () => {
    expect(decideUpdateClick(click({ health: 'hung', probeInFlight: true, waiting: true }))).toEqual({
      kind: 'reload',
      awaitInFlight: false,
      activateWaiting: false,
    })
  })

  it('4: версия отличается, наша проба в полёте — дождаться её (с потолком), потом перезагрузка', () => {
    expect(decideUpdateClick(click({ probeInFlight: true }))).toEqual({
      kind: 'reload',
      awaitInFlight: true,
      activateWaiting: false,
    })
  })

  it('5: версия отличается, проб нет — перезагрузка сразу; ожидающий воркер активируем', () => {
    expect(decideUpdateClick(click({ waiting: true }))).toEqual({
      kind: 'reload',
      awaitInFlight: false,
      activateWaiting: true,
    })
  })

  it('5: без тихой активации ожидающий воркер на клике не трогаем', () => {
    expect(decideUpdateClick(click({ waiting: true, silentActivation: false })).kind).toBe('reload')
    expect(decideUpdateClick(click({ waiting: true, silentActivation: false }))).toMatchObject({
      activateWaiting: false,
    })
  })

  it('5: откат на сервере (версия старше бандла) — тоже «отличается», перезагрузка', () => {
    const older = '0000000-20260901-000000'
    expect(decideUpdateClick(click({ fetched: { kind: 'version', version: older } })).kind).toBe('reload')
  })

  it('6: версии равны — «последняя версия»; ожидающий воркер активируем без ожидания', () => {
    expect(
      decideUpdateClick(click({ fetched: { kind: 'version', version: LOADED }, waiting: true })),
    ).toEqual({ kind: 'toast', reason: 'latest', activateWaiting: true })
    expect(decideUpdateClick(click({ fetched: { kind: 'version', version: LOADED } }))).toEqual({
      kind: 'toast',
      reason: 'latest',
      activateWaiting: false,
    })
  })

  it('7: версии равны, регистрация зависла — «последняя версия» с подсказкой', () => {
    expect(
      decideUpdateClick(click({ fetched: { kind: 'version', version: LOADED }, health: 'hung', waiting: true })),
    ).toEqual({ kind: 'toast', reason: 'latest-hung', activateWaiting: false })
  })

  it('health=unknown ведёт себя как ok', () => {
    expect(decideUpdateClick(click({ health: 'unknown', probeInFlight: true }))).toMatchObject({
      kind: 'reload',
      awaitInFlight: true,
    })
  })
})

describe('serverVersionForClick', () => {
  it('ответ сейчас важнее опроса', () => {
    expect(
      serverVersionForClick({ kind: 'version', version: NEWER }, { version: LOADED, at: NOW }, NOW),
    ).toBe(NEWER)
  })
  it('без ответа — свежий опрос, иначе null', () => {
    expect(serverVersionForClick({ kind: 'unreachable' }, { version: NEWER, at: NOW - 59_999 }, NOW)).toBe(NEWER)
    expect(serverVersionForClick({ kind: 'unreachable' }, { version: NEWER, at: NOW - 60_000 }, NOW)).toBeNull()
    expect(serverVersionForClick({ kind: 'unreachable' }, null, NOW)).toBeNull()
  })
})

function probe(over: Partial<ProbeInput> = {}): ProbeInput {
  return {
    trigger: 'startup',
    health: 'unknown',
    inFlight: false,
    visible: true,
    online: true,
    path: '/',
    lastProbeAt: null,
    now: NOW,
    seenVersion: LOADED,
    probedVersion: LOADED,
    retries: 0,
    installing: false,
    hungAt: null,
    ...over,
  }
}

describe('decideProbe', () => {
  it('стартовая проба — один раз, только видимой и не на /login', () => {
    expect(decideProbe(probe())).toBe(true)
    expect(decideProbe(probe({ lastProbeAt: NOW - 1 }))).toBe(false)
    expect(decideProbe(probe({ visible: false }))).toBe(false)
    expect(decideProbe(probe({ path: '/login' }))).toBe(false)
    expect(decideProbe(probe({ path: '/auth/callback' }))).toBe(true)
  })

  it('после вердикта «завис» — только перепроверка через 5 минут и одна проба на смену версии', () => {
    const hung = { health: 'hung' as const, hungAt: NOW - HUNG_RECHECK_MS, lastProbeAt: NOW - 90_000 }
    expect(decideProbe(probe({ health: 'hung', hungAt: NOW - 1000 }))).toBe(false)
    expect(decideProbe(probe({ ...hung, trigger: 'visible', seenVersion: NEWER }))).toBe(false)
    expect(decideProbe(probe({ ...hung, trigger: 'settled', seenVersion: NEWER }))).toBe(false)
    expect(decideProbe(probe({ ...hung, trigger: 'retry' }))).toBe(false)
    expect(decideProbe(probe({ ...hung, trigger: 'recheck' }))).toBe(true)
    expect(decideProbe(probe({ ...hung, trigger: 'recheck', hungAt: NOW - HUNG_RECHECK_MS + 1 }))).toBe(false)
    expect(decideProbe(probe({ ...hung, trigger: 'version-changed', seenVersion: NEWER }))).toBe(true)
    expect(decideProbe(probe({ ...hung, trigger: 'version-changed' }))).toBe(false)
    // Здоровой регистрации перепроверка не нужна.
    expect(decideProbe(probe({ trigger: 'recheck', lastProbeAt: NOW - 90_000 }))).toBe(false)
  })

  it('пока воркер ставится, проб нет; по концу установки — стартовая или по разошедшейся версии', () => {
    expect(decideProbe(probe({ installing: true }))).toBe(false)
    expect(decideProbe(probe({ installing: true, trigger: 'version-changed', seenVersion: NEWER, lastProbeAt: NOW - 90_000 }))).toBe(false)
    expect(decideProbe(probe({ trigger: 'install-finished' }))).toBe(true)
    expect(decideProbe(probe({ trigger: 'install-finished', lastProbeAt: NOW - 90_000 }))).toBe(false)
    expect(decideProbe(probe({ trigger: 'install-finished', lastProbeAt: NOW - 90_000, seenVersion: NEWER }))).toBe(true)
  })

  it('проба в полёте или офлайн — не запускаем', () => {
    expect(decideProbe(probe({ inFlight: true }))).toBe(false)
    expect(decideProbe(probe({ online: false }))).toBe(false)
  })

  it('смена версии — проба, если её ещё не пробовали и прошло 30 с', () => {
    const base = { trigger: 'version-changed' as const, seenVersion: NEWER, lastProbeAt: NOW - PROBE_MIN_INTERVAL_MS }
    expect(decideProbe(probe(base))).toBe(true)
    expect(decideProbe(probe({ ...base, lastProbeAt: NOW - PROBE_MIN_INTERVAL_MS + 1 }))).toBe(false)
    expect(decideProbe(probe({ ...base, probedVersion: NEWER }))).toBe(false)
  })

  it('видимость и завершение пробы — только если версии разошлись', () => {
    expect(decideProbe(probe({ trigger: 'visible', lastProbeAt: NOW - 90_000 }))).toBe(false)
    expect(decideProbe(probe({ trigger: 'visible', seenVersion: NEWER, lastProbeAt: NOW - 90_000 }))).toBe(true)
    expect(decideProbe(probe({ trigger: 'settled', seenVersion: NEWER, lastProbeAt: NOW - 90_000 }))).toBe(true)
  })

  it('повтор после провала — не больше двух и с шагом', () => {
    const base = { trigger: 'retry' as const, lastProbeAt: NOW - 90_000 }
    expect(decideProbe(probe({ ...base, retries: 0 }))).toBe(true)
    expect(decideProbe(probe({ ...base, retries: PROBE_MAX_RETRIES }))).toBe(false)
    expect(decideProbe(probe({ ...base, lastProbeAt: NOW - 1000 }))).toBe(false)
  })
})

describe('nextSwHealth', () => {
  it('ответ или отказ — ok, в том числе после hung', () => {
    expect(nextSwHealth('unknown', { result: 'settled', visibleMs: 0 })).toBe('ok')
    expect(nextSwHealth('hung', { result: 'settled', visibleMs: 100_000 })).toBe('ok')
    expect(nextSwHealth('ok', { result: 'rejected', visibleMs: 0 })).toBe('ok')
  })
  it('таймаут — hung только по видимому времени', () => {
    expect(nextSwHealth('unknown', { result: 'timeout', visibleMs: PROBE_HUNG_MS })).toBe('hung')
    expect(nextSwHealth('ok', { result: 'timeout', visibleMs: PROBE_HUNG_MS - 1 })).toBe('ok')
    expect(nextSwHealth('unknown', { result: 'timeout', visibleMs: 0 })).toBe('unknown')
  })
})

describe('createVisibleClock', () => {
  it('считает только видимые отрезки', () => {
    const clock = createVisibleClock(0, true)
    clock.note(false, 5_000)
    expect(clock.elapsedVisible(600_000)).toBe(5_000)
    clock.note(true, 600_000)
    expect(clock.elapsedVisible(615_000)).toBe(20_000)
  })
  it('старт в скрытой вкладке не накапливает, пока не станет видимой', () => {
    const clock = createVisibleClock(0, false)
    expect(clock.elapsedVisible(100_000)).toBe(0)
    clock.note(true, 100_000)
    clock.note(true, 100_500)
    expect(clock.elapsedVisible(101_000)).toBe(1_000)
  })
})

describe('hungBrowserHint', () => {
  it('⌘Q только на десктопном Mac; iPad в режиме Macintosh — без него', () => {
    expect(isDesktopMacUa('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari', 0)).toBe(true)
    expect(isDesktopMacUa('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari', 5)).toBe(false)
    expect(isDesktopMacUa('Mozilla/5.0 (iPhone; CPU iPhone OS 26_0)', 5)).toBe(false)
    expect(hungBrowserHint(true)).toContain('⌘Q')
    expect(hungBrowserHint(false)).not.toContain('⌘Q')
    expect(hungBrowserHint(false)).toContain('работает как обычно')
  })
})
