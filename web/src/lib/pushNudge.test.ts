import { describe, expect, it } from 'vitest'

import { isIosUa, PUSH_NUDGE_DISMISS_MS, pushNudgeKind, pushNudgeText, readDismissedUntil, type PushNudgeInput } from './pushNudge'

const base: PushNudgeInput = {
  permission: 'default',
  subscribed: false,
  checked: true,
  ios: false,
  standalone: false,
  dismissedUntil: null,
  now: 1_000_000,
}

describe('ветки нуджа про уведомления', () => {
  it('default → «Включить», denied → настройки, granted без подписки → «Подписаться»', () => {
    expect(pushNudgeKind(base)).toBe('enable')
    expect(pushNudgeKind({ ...base, permission: 'denied' })).toBe('denied')
    expect(pushNudgeKind({ ...base, permission: 'granted' })).toBe('subscribe')
    expect(pushNudgeKind({ ...base, permission: 'granted', subscribed: true })).toBeNull()
  })

  it('granted без ответа getSubscription — молчим: на iOS ready может не прийти, и подписанный увидел бы «Подписаться»', () => {
    expect(pushNudgeKind({ ...base, permission: 'granted', checked: false })).toBeNull()
  })

  it('iPhone во вкладке Safari (unsupported) — инструкция про экран «Домой»; standalone или не-iOS — ничего', () => {
    expect(pushNudgeKind({ ...base, permission: 'unsupported', ios: true })).toBe('ios-install')
    expect(pushNudgeKind({ ...base, permission: 'unsupported', ios: true, standalone: true })).toBeNull()
    expect(pushNudgeKind({ ...base, permission: 'unsupported', ios: false })).toBeNull()
  })

  it('«Позже» прячет на неделю, не навсегда', () => {
    expect(pushNudgeKind({ ...base, dismissedUntil: base.now + 1 })).toBeNull()
    expect(pushNudgeKind({ ...base, dismissedUntil: base.now })).toBe('enable')
    expect(PUSH_NUDGE_DISMISS_MS).toBe(7 * 24 * 3600 * 1000)
    expect(readDismissedUntil(null)).toBeNull()
    expect(readDismissedUntil('abc')).toBeNull()
    expect(readDismissedUntil('42')).toBe(42)
  })

  it('iOS по UA, включая iPadOS под маской Macintosh с тачем', () => {
    expect(isIosUa('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)', 5)).toBe(true)
    expect(isIosUa('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)', 5)).toBe(true)
    expect(isIosUa('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)', 0)).toBe(false)
    expect(isIosUa('Mozilla/5.0 (Linux; Android 14)', 5)).toBe(false)
  })

  it('тексты: гоночный заголовок только для сотрудников точек, у iOS-ветки нет кнопки', () => {
    expect(pushNudgeText('enable', true)).toMatchObject({ title: 'Включите уведомления о гонке', action: 'Включить' })
    expect(pushNudgeText('enable', false).title).toBe('Включить уведомления о задачах?')
    expect(pushNudgeText('ios-install', true).action).toBeNull()
    expect(pushNudgeText('denied', false).action).toBe('Настройки')
    expect(pushNudgeText('subscribe', true).action).toBe('Подписаться')
  })
})
