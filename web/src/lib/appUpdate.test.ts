import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { runUpdateClick, type UpdateClickDeps } from './appUpdate'
import type { SwDiagPayload } from './swDiag'
import { createSwStatusStore } from './swStatusStore'

const LOADED = 'aaaaaaa-20260925-100000'
const NEWER = 'bbbbbbb-20260925-110000'

const never = <T>() => new Promise<T>(() => undefined)

function setup(over: Partial<UpdateClickDeps> = {}) {
  const store = createSwStatusStore(LOADED, Date.now())
  store.getState().patch({ purgeSettled: true })
  const calls = {
    reload: 0,
    statuses: [] as string[],
    diag: [] as { payload: SwDiagPayload; token: string | null }[],
    skip: 0,
  }
  const waiting = {
    postMessage: () => {
      calls.skip += 1
    },
  }
  const deps: UpdateClickDeps = {
    now: () => Date.now(),
    online: () => true,
    loadedVersion: LOADED,
    mode: 'production',
    getRegistration: () => Promise.resolve({ waiting: null }),
    fetchVersion: () => Promise.resolve(NEWER),
    getToken: () => Promise.resolve('tok'),
    store,
    probeInFlight: () => false,
    settleInFlight: () => Promise.resolve(),
    waitForController: () => Promise.resolve(),
    purge: () => Promise.resolve(0),
    reload: () => {
      calls.reload += 1
    },
    sendDiag: (payload, token) => {
      calls.diag.push({ payload, token })
    },
    env: () => ({ ua: 'UA', standalone: false, visible: true, path: '/my' }),
    setStatus: (s) => {
      calls.statuses.push(s)
    },
    ...over,
  }
  return { deps, calls, store, waiting }
}

beforeEach(() => {
  vi.useFakeTimers()
})
afterEach(() => {
  vi.useRealTimers()
})

describe('runUpdateClick', () => {
  it('версия отличается — статус applying, диагностика ДО reload, reload один', async () => {
    const { deps, calls } = setup()
    const p = runUpdateClick(deps)
    await vi.advanceTimersByTimeAsync(0)
    const outcome = await p
    expect(outcome.action).toMatchObject({ kind: 'reload' })
    expect(calls.statuses).toEqual(['checking', 'applying'])
    expect(calls.reload).toBe(1)
    expect(calls.diag).toHaveLength(1)
    expect(calls.diag[0]?.token).toBe('tok')
    expect(calls.diag[0]?.payload.kind).toBe('update_click')
    expect(calls.diag[0]?.payload.click?.action).toBe('reload')
    expect(outcome.totalMs).toBeLessThan(100)
  })

  it('getRegistration повис — через 1 с считаем, что регистрации нет, и перезагружаем', async () => {
    const { deps, calls } = setup({ getRegistration: never })
    const p = runUpdateClick(deps)
    await vi.advanceTimersByTimeAsync(999)
    expect(calls.reload).toBe(0)
    await vi.advanceTimersByTimeAsync(1)
    await p
    expect(calls.reload).toBe(1)
    const lookup = calls.diag[0]?.payload.click?.steps.find((s) => s.name === 'lookup')
    expect(lookup?.result).toBe('timeout')
  })

  it('version.json повис и опроса нет — тост «не удалось проверить» через 3 с, без reload', async () => {
    const { deps, calls } = setup({ fetchVersion: never })
    const p = runUpdateClick(deps)
    await vi.advanceTimersByTimeAsync(3000)
    const outcome = await p
    expect(outcome.action).toEqual({ kind: 'toast', reason: 'unreachable', activateWaiting: false })
    expect(calls.reload).toBe(0)
    expect(calls.statuses).toEqual(['checking', 'idle'])
    expect(calls.diag[0]?.payload.click?.action).toBe('toast-unreachable')
  })

  it('version.json недоступен, но баннер видел новую версию только что — reload', async () => {
    const { deps, calls, store } = setup({ fetchVersion: () => Promise.reject(new Error('net')) })
    store.getState().patch({ polled: { version: NEWER, at: Date.now() - 5000 } })
    const p = runUpdateClick(deps)
    await vi.advanceTimersByTimeAsync(0)
    await p
    expect(calls.reload).toBe(1)
  })

  it('офлайн — тост без запросов к воркеру и без reload', async () => {
    const { deps, calls } = setup({ online: () => false })
    const outcome = await runUpdateClick(deps)
    expect(outcome.action).toMatchObject({ kind: 'toast', reason: 'offline' })
    expect(calls.reload).toBe(0)
  })

  it('версии равны — «последняя версия»; ожидающий воркер получает SKIP_WAITING без ожидания', async () => {
    const { deps, calls, waiting } = setup({
      fetchVersion: () => Promise.resolve(LOADED),
      getRegistration: () => Promise.resolve({ waiting }),
    })
    const outcome = await runUpdateClick(deps)
    expect(outcome.action).toEqual({ kind: 'toast', reason: 'latest', activateWaiting: true })
    expect(calls.skip).toBe(1)
    expect(calls.reload).toBe(0)
  })

  it('регистрация зависла и версии равны — тост с подсказкой, воркер не трогаем', async () => {
    const { deps, calls, waiting, store } = setup({
      fetchVersion: () => Promise.resolve(LOADED),
      getRegistration: () => Promise.resolve({ waiting }),
    })
    store.getState().patch({ health: 'hung' })
    const outcome = await runUpdateClick(deps)
    expect(outcome.action).toMatchObject({ reason: 'latest-hung' })
    expect(calls.skip).toBe(0)
  })

  it('проба в полёте при здоровой регистрации — ждём её потолок 1,5 с, потом reload', async () => {
    const { deps, calls } = setup({ probeInFlight: () => true, settleInFlight: never })
    const p = runUpdateClick(deps)
    await vi.advanceTimersByTimeAsync(1500)
    expect(calls.reload).toBe(0)
    await vi.advanceTimersByTimeAsync(100)
    await p
    expect(calls.reload).toBe(1)
  })

  it('проба в полёте при зависшей регистрации — reload сразу', async () => {
    const { deps, calls, store } = setup({ probeInFlight: () => true, settleInFlight: never })
    store.getState().patch({ health: 'hung' })
    const p = runUpdateClick(deps)
    await vi.advanceTimersByTimeAsync(0)
    await p
    expect(calls.reload).toBe(1)
  })

  it('ожидающий воркер при reload — SKIP_WAITING и ожидание контроллера ≤1 с', async () => {
    const { deps, calls, waiting } = setup({
      getRegistration: () => Promise.resolve({ waiting }),
      waitForController: never,
    })
    const p = runUpdateClick(deps)
    await vi.advanceTimersByTimeAsync(1100)
    await p
    expect(calls.skip).toBe(1)
    expect(calls.reload).toBe(1)
  })

  it('стартовая чистка не завершилась — ждём свою с потолком 2 с; иначе пропускаем', async () => {
    const { deps, calls, store } = setup({ purge: never })
    store.getState().patch({ purgeSettled: false })
    const p = runUpdateClick(deps)
    await vi.advanceTimersByTimeAsync(1999)
    expect(calls.reload).toBe(0)
    await vi.advanceTimersByTimeAsync(1)
    await p
    expect(calls.reload).toBe(1)
    const purge = calls.diag[0]?.payload.click?.steps.find((s) => s.name === 'purge')
    expect(purge?.result).toBe('timeout')

    const fast = setup({ purge: never })
    await runUpdateClick(fast.deps)
    expect(fast.calls.reload).toBe(1)
  })

  it('токен не прочитался за 0,5 с — диагностика без токена, обновление не ждёт', async () => {
    const { deps, calls } = setup({ getToken: never })
    const p = runUpdateClick(deps)
    await vi.advanceTimersByTimeAsync(500)
    await p
    expect(calls.reload).toBe(1)
    expect(calls.diag[0]?.token).toBeNull()
  })

  it('update() воркера в пути кнопки не существует как зависимость — нечего звать', () => {
    const { deps } = setup()
    expect('update' in deps).toBe(false)
  })
})
