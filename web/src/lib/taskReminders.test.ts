import { describe, expect, it } from 'vitest'

import {
  anchorMoment,
  deliveryHint,
  reminderLabel,
  reminderPresets,
  reminderStatus,
  shouldToastReminder,
  type TaskReminderItem,
  timezoneNote,
} from './taskReminders'

// Всё в МСК (UTC+3): 29.09 10:00 МСК = 07:00Z.
const NOW = Date.parse('2026-09-29T07:00:00.000Z')
const DUE_15 = '2026-09-30T12:00:00.000Z' // 30.09 15:00 МСК
const DUE_DAY = '2026-09-30T09:00:00.000Z' // 30.09, без времени (полдень)

const timed = { due_at: DUE_15, due_has_time: true, start_at: null, start_has_time: false }
const dayOnly = { due_at: DUE_DAY, due_has_time: false, start_at: null, start_has_time: false }
const noDates = { due_at: null, start_at: null }

function item(over: Partial<TaskReminderItem>): TaskReminderItem {
  return { id: 'r', anchor: 'due', offset_minutes: 60, fire_at: null, state: 'armed', ...over }
}

describe('anchorMoment — зеркало сервера', () => {
  it('срок со временем — сам момент, без времени и due_day — 09:00', () => {
    expect(anchorMoment('due', timed)).toBe(DUE_15)
    expect(anchorMoment('due', dayOnly)).toBe('2026-09-30T06:00:00.000Z')
    expect(anchorMoment('due_day', timed)).toBe('2026-09-30T06:00:00.000Z')
    expect(anchorMoment('start', timed)).toBeNull()
    expect(anchorMoment('at', timed)).toBeNull()
  })
})

describe('reminderPresets', () => {
  it('срок со временем: от срока, потом время', () => {
    const keys = reminderPresets(timed, NOW).map((p) => p.key)
    expect(keys).toEqual([
      'due:0',
      'due:15',
      'due:60',
      'due:1440',
      'due_day:0',
      'at:hour',
      // «Завтра утром» (30.09 9:00) совпадает с «Утром в день срока» — скрыт.
    ])
  })

  it('срок без времени: «В день срока» и «Накануне»', () => {
    const presets = reminderPresets(dayOnly, NOW)
    expect(presets.map((p) => p.label)).toEqual(['В день срока', 'Через 1 час'])
    // «Накануне · 29.09 9:00» уже прошло в 10:00; «Завтра утром» = «В день срока».
  })

  it('без срока — только абсолютные', () => {
    expect(reminderPresets(noDates, NOW).map((p) => p.key)).toEqual(['at:hour', 'at:tomorrow'])
  })

  it('прошедшие и уже поставленные скрыты', () => {
    const late = Date.parse('2026-09-30T11:30:00.000Z') // 30.09 14:30 МСК
    const keys = reminderPresets(timed, late, [item({ anchor: 'due', offset_minutes: 0 })]).map(
      (p) => p.key,
    )
    // К сроку уже стоит, «за 1 час» (14:00) и «за 1 день» прошли.
    expect(keys).toEqual(['due:15', 'at:hour', 'at:tomorrow'])
  })

  it('подсказка: сегодня — только время, иначе дата', () => {
    const [toDue] = reminderPresets(timed, NOW)
    expect(toDue?.hint).toBe('30.09 15:00')
    const inHour = reminderPresets(noDates, NOW)[0]
    expect(inHour?.hint).toBe('11:00')
    expect(inHour?.body).toEqual({ anchor: 'at', fire_at: '2026-09-29T08:00:00.000Z' })
  })
})

describe('тексты', () => {
  it('название и состояние', () => {
    expect(reminderLabel(item({}), NOW)).toBe('За 1 ч до срока')
    expect(reminderLabel(item({ anchor: 'due_day', offset_minutes: 1440 }), NOW)).toBe('Накануне, 9:00')
    expect(reminderLabel(item({ anchor: 'at', offset_minutes: 0, fire_at: DUE_15 }), NOW)).toBe(
      'завтра в 15:00',
    )
    expect(reminderStatus(item({ fire_at: '2026-09-30T11:00:00.000Z' }), NOW)).toBe('завтра в 14:00')
    expect(reminderStatus(item({ state: 'fired', fired_at: '2026-09-29T06:00:00.000Z' }), NOW)).toBe(
      'пришло сегодня в 09:00',
    )
    expect(reminderStatus(item({ state: 'passed', anchor: 'start' }), NOW)).toBe(
      'Не сработает — время начала прошло',
    )
    expect(reminderStatus(item({ state: 'no_date' }), NOW)).toBe('Не сработает — у задачи нет срока')
  })

  it('подсказка о доставке', () => {
    expect(deliveryHint({ push_devices: 2, push_on: true, inapp_on: true })).toBeNull()
    expect(deliveryHint({ push_devices: 0, push_on: true, inapp_on: true })).toMatch(/только во «Входящие»/)
    expect(deliveryHint({ push_devices: 1, push_on: false, inapp_on: true })).toMatch(/выключены в настройках/)
    expect(deliveryHint({ push_devices: 1, push_on: false, inapp_on: false })).toBe(
      'Напоминания выключены в настройках уведомлений.',
    )
  })

  it('пометка пояса — только если часы устройства другие', () => {
    expect(timezoneNote(NOW, () => '10:00')).toBeNull()
    expect(timezoneNote(NOW, () => '12:00')).toBe('Время — московское')
  })
})

describe('shouldToastReminder', () => {
  const fresh = { kind: 'task.reminder', is_read: false, created_at: '2026-09-29T06:59:30.000Z' }
  it('рост счётчика + свежее напоминание', () => {
    expect(shouldToastReminder(2, 3, fresh, NOW)).toBe(true)
    expect(shouldToastReminder(undefined, 3, fresh, NOW)).toBe(false) // первая загрузка
    expect(shouldToastReminder(3, 3, fresh, NOW)).toBe(false)
    expect(shouldToastReminder(2, 3, { ...fresh, kind: 'task.mentioned' }, NOW)).toBe(false)
    expect(
      shouldToastReminder(2, 3, { ...fresh, created_at: '2026-09-29T06:50:00.000Z' }, NOW),
    ).toBe(false)
  })
})
