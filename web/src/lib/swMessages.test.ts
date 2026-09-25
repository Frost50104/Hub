import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  createOpenUrlInbox,
  decideOpenUrl,
  HUB_PONG,
  installSwMessageListener,
  isNotificationClientUrl,
  type MessagePortLike,
  OPEN_URL_ACK,
  openUrlTarget,
  parseSwMessage,
  pickNotificationClient,
  postAndAwaitAck,
  type SwMessageEventLike,
} from './swMessages'

const ORIGIN = 'https://hub.signaris.ru'

describe('parseSwMessage', () => {
  it('разбирает OPEN_URL и HUB_PING, остальное — null', () => {
    expect(parseSwMessage({ type: 'OPEN_URL', url: '/tasks?task=1', title: 'Задача' })).toEqual({
      type: 'OPEN_URL',
      url: '/tasks?task=1',
      title: 'Задача',
    })
    expect(parseSwMessage({ type: 'OPEN_URL', url: '/x' })).toEqual({ type: 'OPEN_URL', url: '/x' })
    expect(parseSwMessage({ type: 'HUB_PING' })).toEqual({ type: 'HUB_PING' })
    expect(parseSwMessage({ type: 'OPEN_URL' })).toBeNull()
    expect(parseSwMessage({ type: 'OPEN_URL', url: 7 })).toBeNull()
    expect(parseSwMessage({ type: 'SOMETHING' })).toBeNull()
    expect(parseSwMessage('OPEN_URL')).toBeNull()
    expect(parseSwMessage(null)).toBeNull()
  })
})

describe('openUrlTarget', () => {
  it('относительный и свой абсолютный адрес — маршрут с query и hash', () => {
    expect(openUrlTarget('/tasks?task=1#c', ORIGIN)).toBe('/tasks?task=1#c')
    expect(openUrlTarget(`${ORIGIN}/learn/courses/5`, ORIGIN)).toBe('/learn/courses/5')
  })
  it('чужой origin, javascript: и мусор — null', () => {
    expect(openUrlTarget('https://evil.example/x', ORIGIN)).toBeNull()
    expect(openUrlTarget('javascript:alert(1)', ORIGIN)).toBeNull()
    expect(openUrlTarget('http://[', ORIGIN)).toBeNull()
  })
})

describe('pickNotificationClient', () => {
  const c = (url: string, over: { focused?: boolean; visibilityState?: string } = {}) => ({
    url: url.startsWith('http') ? url : `${ORIGIN}${url}`,
    ...over,
  })

  it('служебные страницы и чужой origin не подходят', () => {
    expect(isNotificationClientUrl(`${ORIGIN}/p/race/abc`, ORIGIN)).toBe(false)
    expect(isNotificationClientUrl(`${ORIGIN}/login`, ORIGIN)).toBe(false)
    expect(isNotificationClientUrl(`${ORIGIN}/auth/callback?code=1`, ORIGIN)).toBe(false)
    expect(isNotificationClientUrl('https://auth.signaris.ru/', ORIGIN)).toBe(false)
    expect(isNotificationClientUrl(`${ORIGIN}/my`, ORIGIN)).toBe(true)
    expect(isNotificationClientUrl('garbage', ORIGIN)).toBe(false)
  })

  it('в фокусе > видимое > первое; сначала окна под контролем', () => {
    const controlled = [c('/a'), c('/b', { visibilityState: 'visible' }), c('/c', { focused: true })]
    expect(pickNotificationClient(controlled, controlled, ORIGIN)?.url).toBe(`${ORIGIN}/c`)
    expect(pickNotificationClient(controlled.slice(0, 2), controlled, ORIGIN)?.url).toBe(`${ORIGIN}/b`)
    expect(pickNotificationClient([c('/a')], controlled, ORIGIN)?.url).toBe(`${ORIGIN}/a`)
    // Контролируемых нет — берём из всех.
    expect(pickNotificationClient([], [c('/p/x'), c('/my')], ORIGIN)?.url).toBe(`${ORIGIN}/my`)
    expect(pickNotificationClient([], [c('/login')], ORIGIN)).toBeNull()
    expect(pickNotificationClient([], [], ORIGIN)).toBeNull()
  })
})

describe('decideOpenUrl', () => {
  it('переход только на другой свой адрес', () => {
    expect(decideOpenUrl({ target: '/tasks?task=1', current: '/my' })).toEqual({ kind: 'navigate', to: '/tasks?task=1' })
    expect(decideOpenUrl({ target: '/my', current: '/my' })).toEqual({ kind: 'ignore' })
    expect(decideOpenUrl({ target: null, current: '/my' })).toEqual({ kind: 'ignore' })
  })
})

describe('createOpenUrlInbox', () => {
  const msg = (url: string) => ({ type: 'OPEN_URL' as const, url })

  it('сообщение до подписчика ждёт и отдаётся один раз', () => {
    const inbox = createOpenUrlInbox()
    inbox.push(msg('/a'))
    inbox.push(msg('/b'))
    const got: string[] = []
    inbox.subscribe((m) => got.push(m.url))
    inbox.subscribe((m) => got.push(`second:${m.url}`))
    expect(got).toEqual(['/b'])
    expect(inbox.pending()).toBeNull()
  })

  it('переподписка StrictMode ничего не теряет', () => {
    const inbox = createOpenUrlInbox()
    const got: string[] = []
    const off = inbox.subscribe((m) => got.push(`first:${m.url}`))
    off()
    inbox.push(msg('/a'))
    inbox.subscribe((m) => got.push(`second:${m.url}`))
    expect(got).toEqual(['second:/a'])
  })

  it('с живым подписчиком доставляет сразу', () => {
    const inbox = createOpenUrlInbox()
    const got: string[] = []
    inbox.subscribe((m) => got.push(m.url))
    inbox.push(msg('/x'))
    expect(got).toEqual(['/x'])
  })
})

describe('installSwMessageListener', () => {
  function fakeContainer() {
    const listeners: ((event: SwMessageEventLike) => void)[] = []
    let started = 0
    return {
      addEventListener: (_type: 'message', l: (event: SwMessageEventLike) => void) => {
        listeners.push(l)
      },
      startMessages: () => {
        started += 1
      },
      emit(data: unknown, port?: MessagePortLike) {
        for (const l of listeners) l({ data, ports: port ? [port] : [] })
      },
      get started() {
        return started
      },
    }
  }

  it('подтверждает OPEN_URL в порт, кладёт в ящик и запускает очередь', () => {
    const container = fakeContainer()
    const inbox = createOpenUrlInbox()
    installSwMessageListener(container, inbox)
    expect(container.started).toBe(1)
    const replies: unknown[] = []
    container.emit({ type: 'OPEN_URL', url: '/tasks' }, { postMessage: (d) => replies.push(d) })
    expect(replies).toEqual([{ type: OPEN_URL_ACK }])
    expect(inbox.pending()).toEqual({ type: 'OPEN_URL', url: '/tasks' })
  })

  it('отвечает на HUB_PING понгом и не трогает ящик; мусор игнорирует', () => {
    const container = fakeContainer()
    const inbox = createOpenUrlInbox()
    installSwMessageListener(container, inbox)
    const replies: unknown[] = []
    container.emit({ type: 'HUB_PING' }, { postMessage: (d) => replies.push(d) })
    container.emit({ type: 'NOPE' }, { postMessage: (d) => replies.push(d) })
    container.emit({ type: 'OPEN_URL', url: '/x' }) // без порта — не падает
    expect(replies).toEqual([{ type: HUB_PONG }])
    expect(inbox.pending()).toEqual({ type: 'OPEN_URL', url: '/x' })
  })
})

describe('postAndAwaitAck', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  function channel() {
    const ch = { port1: { onmessage: null as ((e: { data: unknown }) => void) | null }, port2: 'port2' }
    return ch
  }
  const deps = () => ({
    createChannel: channel,
    setTimeout: (fn: () => void, ms: number) => setTimeout(fn, ms),
    clearTimeout: (id: unknown) => clearTimeout(id as ReturnType<typeof setTimeout>),
  })

  it('ответ нужного типа — true, чужой ответ ждём дальше', async () => {
    let port1: { onmessage: ((e: { data: unknown }) => void) | null } | null = null
    const d = deps()
    d.createChannel = () => {
      const ch = channel()
      port1 = ch.port1
      return ch
    }
    const sent: unknown[] = []
    const p = postAndAwaitAck({ postMessage: (m, t) => sent.push([m, t]) }, { type: 'HUB_PING' }, HUB_PONG, 300, d)
    expect(sent).toEqual([[{ type: 'HUB_PING' }, ['port2']]])
    port1!.onmessage?.({ data: { type: 'OTHER' } })
    port1!.onmessage?.({ data: { type: HUB_PONG } })
    await expect(p).resolves.toBe(true)
  })

  it('молчание — false по таймауту; отказ postMessage — false сразу', async () => {
    const p = postAndAwaitAck({ postMessage: () => undefined }, { type: 'HUB_PING' }, HUB_PONG, 300, deps())
    await vi.advanceTimersByTimeAsync(300)
    await expect(p).resolves.toBe(false)
    const q = postAndAwaitAck(
      {
        postMessage: () => {
          throw new Error('closed')
        },
      },
      { type: 'HUB_PING' },
      HUB_PONG,
      300,
      deps(),
    )
    await expect(q).resolves.toBe(false)
  })
})
