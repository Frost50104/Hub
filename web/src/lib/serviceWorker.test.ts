import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  createServiceWorkerController,
  type SwContainerLike,
  type SwDeps,
  type SwRegistrationLike,
  type SwWorkerLike,
} from './serviceWorker'
import { HUNG_RECHECK_MS, PROBE_HUNG_MS, PROBE_RETRY_DELAY_MS, STARTUP_PROBE_DELAY_MS } from './swPolicy'
import { createSwStatusStore } from './swStatusStore'

const LOADED = 'aaaaaaa-20260925-100000'
const NEWER = 'bbbbbbb-20260925-110000'

function fakeWorker(state = 'installing'): SwWorkerLike & {
  state: string
  messages: unknown[]
  fire(state: string): void
} {
  const listeners: (() => void)[] = []
  return {
    state,
    messages: [],
    postMessage(m) {
      this.messages.push(m)
    },
    addEventListener(_t, l) {
      listeners.push(l)
    },
    fire(next) {
      this.state = next
      for (const l of listeners) l()
    },
  }
}

interface FakeRegistration extends SwRegistrationLike {
  updates: number
  resolveUpdate: (() => void) | null
  rejectUpdate: (() => void) | null
  updateFound(): void
}

function fakeRegistration(over: Partial<Pick<SwRegistrationLike, 'installing' | 'waiting' | 'active'>> = {}): FakeRegistration {
  const listeners: (() => void)[] = []
  const reg: FakeRegistration = {
    installing: null,
    waiting: null,
    active: fakeWorker('activated'),
    updates: 0,
    resolveUpdate: null,
    rejectUpdate: null,
    update() {
      reg.updates += 1
      return new Promise<void>((resolve, reject) => {
        reg.resolveUpdate = resolve
        reg.rejectUpdate = () => reject(new Error('offline'))
      })
    },
    addEventListener(_t, l) {
      listeners.push(l)
    },
    updateFound() {
      for (const l of listeners) l()
    },
    ...over,
  }
  return reg
}

function fakeContainer(reg: FakeRegistration | undefined, opts: { hangLookup?: boolean } = {}) {
  let registered = 0
  const container: SwContainerLike & { registered: number; fireControllerChange(): void } = {
    controller: {},
    registered: 0,
    getRegistration: () => (opts.hangLookup ? new Promise(() => undefined) : Promise.resolve(reg)),
    register: () => {
      registered += 1
      container.registered = registered
      return Promise.resolve(reg ?? fakeRegistration())
    },
    addEventListener: (_t, l) => {
      container.fireControllerChange = l
    },
    fireControllerChange: () => undefined,
  }
  return container
}

function setup(reg: FakeRegistration | undefined, over: Partial<SwDeps> = {}) {
  let visible = true
  let visibilityListener: (() => void) | null = null
  const store = createSwStatusStore(LOADED, Date.now())
  const hung = vi.fn()
  const recovered = vi.fn()
  const deps: SwDeps = {
    container: fakeContainer(reg),
    prod: true,
    now: () => Date.now(),
    setTimeout: (fn, ms) => setTimeout(fn, ms),
    clearTimeout: (id) => clearTimeout(id as ReturnType<typeof setTimeout>),
    setInterval: (fn, ms) => setInterval(fn, ms),
    clearInterval: (id) => clearInterval(id as ReturnType<typeof setInterval>),
    isVisible: () => visible,
    onVisibilityChange: (l) => {
      visibilityListener = l
    },
    online: () => true,
    path: () => '/my',
    purge: () => Promise.resolve(0),
    silentActivation: true,
    store,
    onHung: hung,
    onRecovered: recovered,
    ...over,
  }
  const controller = createServiceWorkerController(deps)
  return {
    controller,
    store,
    hung,
    recovered,
    deps,
    setVisible(next: boolean) {
      visible = next
      visibilityListener?.()
    },
  }
}

beforeEach(() => {
  vi.useFakeTimers()
})
afterEach(() => {
  vi.useRealTimers()
})

describe('регистрация', () => {
  it('при живой регистрации register() не зовётся, снимок заполняется', async () => {
    const reg = fakeRegistration()
    const { controller, store, deps } = setup(reg)
    await controller.install()
    expect((deps.container as ReturnType<typeof fakeContainer>).registered).toBe(0)
    expect(store.getState().snapshot).toMatchObject({ supported: true, active: true, waiting: false })
    await vi.advanceTimersByTimeAsync(0)
    expect(store.getState().purgeSettled).toBe(true)
  })

  it('без регистрации — register один раз; вторая установка контроллера не нужна', async () => {
    const { controller, deps } = setup(undefined)
    await controller.install()
    expect((deps.container as ReturnType<typeof fakeContainer>).registered).toBe(1)
  })

  it('getRegistration повис — регистрируем заново после потолка', async () => {
    const reg = fakeRegistration()
    const container = fakeContainer(reg, { hangLookup: true })
    const { controller, store } = setup(reg, { container })
    const p = controller.install()
    await vi.advanceTimersByTimeAsync(2000)
    await p
    expect(container.registered).toBe(1)
    expect(store.getState().lookupTimedOut).toBe(true)
  })

  it('не prod или нет navigator.serviceWorker — supported=false, чистка «завершена»', async () => {
    const { controller, store } = setup(fakeRegistration(), { prod: false })
    await controller.install()
    expect(store.getState().snapshot.supported).toBe(false)
    expect(store.getState().purgeSettled).toBe(true)
  })
})

describe('пробы', () => {
  it('стартовая проба через 5 с, только видимой; после ответа — ok', async () => {
    const reg = fakeRegistration()
    const { controller, store } = setup(reg)
    await controller.install()
    await vi.advanceTimersByTimeAsync(STARTUP_PROBE_DELAY_MS - 1)
    expect(reg.updates).toBe(0)
    await vi.advanceTimersByTimeAsync(1)
    expect(reg.updates).toBe(1)
    expect(controller.probeInFlight()).toBe(true)
    reg.resolveUpdate?.()
    await vi.advanceTimersByTimeAsync(0)
    expect(controller.probeInFlight()).toBe(false)
    expect(store.getState().health).toBe('ok')
  })

  it('скрытая вкладка откладывает стартовую пробу до появления', async () => {
    const reg = fakeRegistration()
    const { controller, setVisible } = setup(reg)
    await controller.install()
    setVisible(false)
    await vi.advanceTimersByTimeAsync(STARTUP_PROBE_DELAY_MS)
    expect(reg.updates).toBe(0)
    setVisible(true)
    expect(reg.updates).toBe(1)
  })

  it('на /login проб нет', async () => {
    const reg = fakeRegistration()
    const { controller } = setup(reg, { path: () => '/login' })
    await controller.install()
    await vi.advanceTimersByTimeAsync(STARTUP_PROBE_DELAY_MS)
    expect(reg.updates).toBe(0)
  })

  it('смена версии сервера запускает пробу; повторный опрос той же версии — нет', async () => {
    const reg = fakeRegistration()
    const { controller } = setup(reg)
    await controller.install()
    await vi.advanceTimersByTimeAsync(STARTUP_PROBE_DELAY_MS)
    reg.resolveUpdate?.()
    await vi.advanceTimersByTimeAsync(30_000)
    controller.noteServerVersion(NEWER, Date.now())
    expect(reg.updates).toBe(2)
    reg.resolveUpdate?.()
    await vi.advanceTimersByTimeAsync(30_000)
    controller.noteServerVersion(NEWER, Date.now())
    expect(reg.updates).toBe(2)
  })

  it('версия сменилась, пока проба в полёте — после её завершения и шага пробуем снова', async () => {
    const reg = fakeRegistration()
    const { controller } = setup(reg)
    await controller.install()
    await vi.advanceTimersByTimeAsync(STARTUP_PROBE_DELAY_MS)
    controller.noteServerVersion(NEWER, Date.now())
    expect(reg.updates).toBe(1) // в полёте — не дублируем
    await vi.advanceTimersByTimeAsync(31_000)
    reg.resolveUpdate?.()
    await vi.advanceTimersByTimeAsync(0)
    expect(reg.updates).toBe(2)
  })

  it('вердикт «завис» — по 20 с видимого времени, один onHung; обычных проб больше нет', async () => {
    const reg = fakeRegistration()
    const { controller, store, hung, recovered, setVisible } = setup(reg)
    await controller.install()
    await vi.advanceTimersByTimeAsync(STARTUP_PROBE_DELAY_MS)
    setVisible(false)
    await vi.advanceTimersByTimeAsync(600_000) // фон — не считается
    expect(store.getState().health).toBe('unknown')
    setVisible(true)
    await vi.advanceTimersByTimeAsync(PROBE_HUNG_MS + 1000)
    expect(store.getState().health).toBe('hung')
    expect(hung).toHaveBeenCalledTimes(1)
    setVisible(false)
    setVisible(true)
    expect(reg.updates).toBe(1) // видимость пробу не запускает
    // Поздний ответ снимает вердикт и сообщает о выздоровлении.
    reg.resolveUpdate?.()
    await vi.advanceTimersByTimeAsync(0)
    expect(store.getState().health).toBe('ok')
    expect(store.getState().hungAt).toBeNull()
    expect(recovered).toHaveBeenCalledTimes(1)
  })

  it('после «завис» — одна проба на смену версии и перепроверка через 5 минут', async () => {
    const reg = fakeRegistration()
    const { controller, store } = setup(reg)
    await controller.install()
    await vi.advanceTimersByTimeAsync(STARTUP_PROBE_DELAY_MS + PROBE_HUNG_MS + 1000)
    expect(store.getState().health).toBe('hung')
    // Висящая проба всё ещё в полёте — новая не стартует, пока та не завершится.
    controller.noteServerVersion(NEWER, Date.now())
    expect(reg.updates).toBe(1)
    reg.resolveUpdate?.()
    await vi.advanceTimersByTimeAsync(0)
    expect(store.getState().health).toBe('ok')
    // Снова зависла: версия сменилась ещё раз — одна проба.
    const fresh = fakeRegistration()
    const again = setup(fresh)
    await again.controller.install()
    await vi.advanceTimersByTimeAsync(STARTUP_PROBE_DELAY_MS + PROBE_HUNG_MS + 1000)
    expect(again.store.getState().health).toBe('hung')
    // Перепроверка через 5 минут: первая проба так и висит → в полёте → нет; иначе была бы.
    await vi.advanceTimersByTimeAsync(HUNG_RECHECK_MS)
    expect(fresh.updates).toBe(1)
  })

  it('пока воркер ставится, стартовая проба ждёт конца установки', async () => {
    const installing = fakeWorker('installing')
    const reg = fakeRegistration({ installing })
    const { controller } = setup(reg)
    await controller.install()
    await vi.advanceTimersByTimeAsync(STARTUP_PROBE_DELAY_MS)
    expect(reg.updates).toBe(0)
    reg.installing = null
    reg.waiting = installing
    installing.fire('installed')
    expect(reg.updates).toBe(1)
  })

  it('отказ update() — повтор через паузу, не больше двух', async () => {
    const reg = fakeRegistration()
    const { controller } = setup(reg)
    await controller.install()
    await vi.advanceTimersByTimeAsync(STARTUP_PROBE_DELAY_MS)
    reg.rejectUpdate?.()
    await vi.advanceTimersByTimeAsync(PROBE_RETRY_DELAY_MS)
    expect(reg.updates).toBe(2)
    reg.rejectUpdate?.()
    await vi.advanceTimersByTimeAsync(PROBE_RETRY_DELAY_MS)
    expect(reg.updates).toBe(3)
    reg.rejectUpdate?.()
    await vi.advanceTimersByTimeAsync(PROBE_RETRY_DELAY_MS * 2)
    expect(reg.updates).toBe(3)
  })

  it('settleInFlightUpdate ждёт пробу не дольше потолка', async () => {
    const reg = fakeRegistration()
    const { controller } = setup(reg)
    await controller.install()
    await vi.advanceTimersByTimeAsync(STARTUP_PROBE_DELAY_MS)
    let settled = false
    void controller.settleInFlightUpdate(1500).then(() => {
      settled = true
    })
    await vi.advanceTimersByTimeAsync(1499)
    expect(settled).toBe(false)
    await vi.advanceTimersByTimeAsync(1)
    expect(settled).toBe(true)
    reg.resolveUpdate?.()
    await vi.advanceTimersByTimeAsync(0)
    // Пробы в полёте нет — резолв сразу, без таймера.
    await expect(controller.settleInFlightUpdate(1500)).resolves.toBeUndefined()
  })
})

describe('тихая активация', () => {
  it('ожидающий воркер на старте получает SKIP_WAITING; без тихой активации — нет', async () => {
    const waiting = fakeWorker('installed')
    const { controller } = setup(fakeRegistration({ waiting }))
    await controller.install()
    expect(waiting.messages).toEqual([{ type: 'SKIP_WAITING' }])
    const waiting2 = fakeWorker('installed')
    const off = setup(fakeRegistration({ waiting: waiting2 }), { silentActivation: false })
    await off.controller.install()
    expect(waiting2.messages).toEqual([])
  })

  it('воркер, ставящийся на момент загрузки, доводится до SKIP_WAITING', async () => {
    const installing = fakeWorker('installing')
    const reg = fakeRegistration({ installing })
    const { controller } = setup(reg)
    await controller.install()
    reg.installing = null
    reg.waiting = installing
    installing.fire('installed')
    expect(installing.messages).toEqual([{ type: 'SKIP_WAITING' }])
  })

  it('updatefound → installed → SKIP_WAITING; redundant → повтор пробы', async () => {
    const reg = fakeRegistration()
    const { controller } = setup(reg)
    await controller.install()
    const fresh = fakeWorker('installing')
    reg.installing = fresh
    reg.updateFound()
    reg.installing = null
    reg.waiting = fresh
    fresh.fire('installed')
    expect(fresh.messages).toEqual([{ type: 'SKIP_WAITING' }])
    expect(controller.waitingWorker()).toBe(fresh)
    const broken = fakeWorker('installing')
    reg.installing = broken
    reg.updateFound()
    reg.installing = null
    broken.fire('redundant')
    await vi.advanceTimersByTimeAsync(PROBE_RETRY_DELAY_MS)
    expect(reg.updates).toBe(1)
  })

  it('возврат видимости повторяет SKIP_WAITING ожидающему (пинг мог отложить активацию)', async () => {
    const waiting = fakeWorker('installed')
    const { controller, setVisible } = setup(fakeRegistration({ waiting }))
    await controller.install()
    setVisible(false)
    setVisible(true)
    expect(waiting.messages).toHaveLength(2)
  })
})
