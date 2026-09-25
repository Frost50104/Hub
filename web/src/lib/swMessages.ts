/**
 * Контракт сообщений между service worker'ом и страницей. Общий модуль для
 * `src/sw.ts` и приложения: на верхнем уровне НИКАКИХ обращений к `window`,
 * `document` или `self` — в воркере первых двух нет, в vitest нет ни одного.
 *
 * Зачем: клик по push-уведомлению раньше делал `client.navigate(url)` —
 * полную навигацию первого попавшегося окна Hub, то есть новый документ там,
 * где человек, возможно, печатал (25.09). Теперь воркер ШЛЁТ странице
 * `OPEN_URL`, страница подтверждает получение и переходит SPA-маршрутом;
 * `navigate()` остаётся запасным ходом для окна без слушателя (старый бандл).
 *
 * `HUB_PING`/`HUB_PONG` — защитный пинг перед `skipWaiting()`: старый бандл
 * (плагин vite-plugin-pwa) на сообщения не отвечает, и воркер не активируется,
 * пока живо хоть одно такое окно — иначе слушатель `controlling` плагина
 * перезагрузил бы его без клика.
 */

export interface OpenUrlMessage {
  type: 'OPEN_URL'
  url: string
  title?: string
}

export interface PingMessage {
  type: 'HUB_PING'
}

export type SwToPageMessage = OpenUrlMessage | PingMessage

export const OPEN_URL_ACK = 'OPEN_URL_ACK'
export const HUB_PONG = 'HUB_PONG'
export const SKIP_WAITING = 'SKIP_WAITING'

function typeOf(data: unknown): string | null {
  if (typeof data !== 'object' || data === null) return null
  const t = (data as { type?: unknown }).type
  return typeof t === 'string' ? t : null
}

export function parseSwMessage(data: unknown): SwToPageMessage | null {
  const type = typeOf(data)
  if (type === 'HUB_PING') return { type }
  if (type === 'OPEN_URL') {
    const { url, title } = data as { url?: unknown; title?: unknown }
    if (typeof url !== 'string' || url === '') return null
    return typeof title === 'string' ? { type, url, title } : { type, url }
  }
  return null
}

/** Ответ страницы: объект с ожидаемым `type`. */
export function isAck(data: unknown, ackType: string): boolean {
  return typeOf(data) === ackType
}

/**
 * Адрес уведомления как маршрут приложения: только свой origin, только
 * http(s). Абсолютный чужой адрес или `javascript:` — null.
 */
export function openUrlTarget(url: string, origin: string): string | null {
  let parsed: URL
  try {
    parsed = new URL(url, origin)
  } catch {
    return null
  }
  if (parsed.origin !== origin) return null
  if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') return null
  return `${parsed.pathname}${parsed.search}${parsed.hash}`
}

export interface WindowClientLike {
  url: string
  focused?: boolean
  visibilityState?: string
}

/**
 * Окно, которому можно отдать уведомление: свой origin и не служебная
 * страница — `/p/` (публичный вид без Shell), `/login` (сейчас уйдёт на SSO
 * полной навигацией, сообщение умрёт вместе с документом), `/auth/` (вход).
 */
export function isNotificationClientUrl(url: string, origin: string): boolean {
  let parsed: URL
  try {
    parsed = new URL(url)
  } catch {
    return false
  }
  if (parsed.origin !== origin) return false
  const path = parsed.pathname
  return !(path.startsWith('/p/') || path === '/login' || path.startsWith('/login/') || path.startsWith('/auth/'))
}

function bestClient<T extends WindowClientLike>(clients: readonly T[], origin: string): T | null {
  const fit = clients.filter((c) => isNotificationClientUrl(c.url, origin))
  if (fit.length === 0) return null
  return (
    fit.find((c) => c.focused === true) ??
    fit.find((c) => c.visibilityState === 'visible') ??
    fit[0] ??
    null
  )
}

/**
 * Сначала окна под контролем этого воркера (им можно и `navigate()`),
 * потом остальные. Внутри — в фокусе, потом видимое, потом первое.
 */
export function pickNotificationClient<T extends WindowClientLike>(
  controlled: readonly T[],
  all: readonly T[],
  origin: string,
): T | null {
  return bestClient(controlled, origin) ?? bestClient(all, origin)
}

export type OpenUrlDecision = { kind: 'navigate'; to: string } | { kind: 'ignore' }

/** Уже на этом адресе — переходить некуда; чужой адрес — игнорируем. */
export function decideOpenUrl(input: { target: string | null; current: string }): OpenUrlDecision {
  if (input.target === null) return { kind: 'ignore' }
  if (input.target === input.current) return { kind: 'ignore' }
  return { kind: 'navigate', to: input.target }
}

export interface OpenUrlInbox {
  push(message: OpenUrlMessage): void
  subscribe(handler: (message: OpenUrlMessage) => void): () => void
  /** Только для тестов и отладки. */
  pending(): OpenUrlMessage | null
}

/**
 * Почтовый ящик страницы: сообщение приходит в `main.tsx` до React, а
 * обработчик появляется в `Shell`. Держим ПОСЛЕДНЕЕ сообщение до первого
 * живого подписчика и отдаём ровно один раз; переподписка (StrictMode)
 * ничего не теряет.
 */
export function createOpenUrlInbox(): OpenUrlInbox {
  const handlers = new Set<(message: OpenUrlMessage) => void>()
  let pending: OpenUrlMessage | null = null
  const deliver = () => {
    if (pending === null || handlers.size === 0) return
    const message = pending
    pending = null
    for (const handler of handlers) handler(message)
  }
  return {
    push(message) {
      pending = message
      deliver()
    },
    subscribe(handler) {
      handlers.add(handler)
      deliver()
      return () => {
        handlers.delete(handler)
      }
    },
    pending: () => pending,
  }
}

export interface MessagePortLike {
  postMessage(data: unknown): void
}

export interface SwMessageEventLike {
  data: unknown
  ports: readonly MessagePortLike[]
}

export interface SwContainerMessagesLike {
  addEventListener(type: 'message', listener: (event: SwMessageEventLike) => void): void
  startMessages?(): void
}

/**
 * Слушатель сообщений воркера. Подтверждение уходит СИНХРОННО при получении —
 * до любой навигации: воркер ждёт его с потолком, и поздний ответ означал бы
 * `navigate()` поверх уже сделанного SPA-перехода.
 *
 * `startMessages()` обязателен: очередь сообщений клиента запускается сама
 * только у `onmessage`-сеттера, а не у `addEventListener`.
 */
export function installSwMessageListener(container: SwContainerMessagesLike, inbox: OpenUrlInbox): void {
  container.addEventListener('message', (event) => {
    const message = parseSwMessage(event.data)
    if (!message) return
    const port = event.ports[0]
    if (message.type === 'HUB_PING') {
      port?.postMessage({ type: HUB_PONG })
      return
    }
    port?.postMessage({ type: OPEN_URL_ACK })
    inbox.push(message)
  })
  container.startMessages?.()
}

export interface MessageChannelLike {
  port1: { onmessage: ((event: { data: unknown }) => void) | null; close?: () => void }
  port2: unknown
}

export interface AckDeps {
  createChannel: () => MessageChannelLike
  setTimeout: (fn: () => void, ms: number) => unknown
  clearTimeout: (id: unknown) => void
}

/**
 * Послать сообщение и дождаться ответа `ackType` через `MessageChannel`, не
 * дольше `timeoutMs`. Любой сбой (получатель без поддержки transfer, закрытое
 * окно) — `false`, как и молчание.
 */
export function postAndAwaitAck(
  target: { postMessage(message: unknown, transfer: unknown[]): void },
  message: unknown,
  ackType: string,
  timeoutMs: number,
  deps: AckDeps,
): Promise<boolean> {
  return new Promise((resolve) => {
    let channel: MessageChannelLike
    try {
      channel = deps.createChannel()
    } catch {
      resolve(false)
      return
    }
    let done = false
    const finish = (value: boolean) => {
      if (done) return
      done = true
      deps.clearTimeout(timer)
      channel.port1.onmessage = null
      channel.port1.close?.()
      resolve(value)
    }
    const timer = deps.setTimeout(() => finish(false), timeoutMs)
    channel.port1.onmessage = (event) => {
      if (isAck(event.data, ackType)) finish(true)
    }
    try {
      target.postMessage(message, [channel.port2])
    } catch {
      finish(false)
    }
  })
}

/** Единственный ящик приложения: наполняется в `main.tsx`, читается в `Shell`. */
export const swInbox = createOpenUrlInbox()
