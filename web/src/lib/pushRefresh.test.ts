import { describe, expect, it } from 'vitest'

import {
  parseSyncStamp,
  PUSH_SYNC_INTERVAL_MS,
  shouldSyncPush,
  type PushRefreshState,
} from './pushRefresh'

const NOW = 1_700_000_000_000

const state = (over: Partial<PushRefreshState> = {}): PushRefreshState => ({
  permission: 'granted',
  optedIn: true,
  lastSyncAt: null,
  now: NOW,
  ...over,
})

describe('shouldSyncPush', () => {
  it('подтверждает подписку при первом запуске после включения', () => {
    expect(shouldSyncPush(state())).toBe(true)
  })

  it('без разрешения — не пытается', () => {
    expect(shouldSyncPush(state({ permission: 'default' }))).toBe(false)
    expect(shouldSyncPush(state({ permission: 'denied' }))).toBe(false)
    expect(shouldSyncPush(state({ permission: 'unsupported' }))).toBe(false)
  })

  it('человек выключил уведомления — молча не возвращаем', () => {
    // Разрешение браузера остаётся granted и после нашей кнопки «Отключить»:
    // без отдельной отметки тихая логика подписала бы обратно.
    expect(shouldSyncPush(state({ optedIn: false }))).toBe(false)
  })

  it('недавно подтверждали — не бьём в сервер на каждой навигации', () => {
    expect(shouldSyncPush(state({ lastSyncAt: NOW - 60_000 }))).toBe(false)
  })

  it('прошёл интервал — подтверждаем снова', () => {
    expect(shouldSyncPush(state({ lastSyncAt: NOW - PUSH_SYNC_INTERVAL_MS - 1 }))).toBe(true)
  })

  it('час назад — рано, тринадцать часов — пора', () => {
    const hour = 60 * 60 * 1000
    expect(shouldSyncPush(state({ lastSyncAt: NOW - hour }))).toBe(false)
    expect(shouldSyncPush(state({ lastSyncAt: NOW - 13 * hour }))).toBe(true)
  })
})

describe('parseSyncStamp', () => {
  it('пусто и мусор дают null — решение падает в «пора подтвердить»', () => {
    expect(parseSyncStamp(null)).toBeNull()
    expect(parseSyncStamp('')).toBeNull()
    expect(parseSyncStamp('позавчера')).toBeNull()
    expect(parseSyncStamp('-1')).toBeNull()
  })

  it('число читается как есть', () => {
    expect(parseSyncStamp(String(NOW))).toBe(NOW)
  })
})
