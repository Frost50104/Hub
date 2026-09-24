import { describe, expect, it } from 'vitest'

import { commitAction, syncDraft } from './dateDraft'
import {
  compareDue,
  dayTimeToIso,
  formatDueShort,
  parseTimeKey,
  shortDate,
  timeKey,
} from './taskDates'
import { dateTimePatch, splitDateTime, taskDateTime } from './taskDateTime'

const MSK = 'Europe/Moscow'

describe('время в taskDates (0061)', () => {
  it('timeKey — часы по МСК, полночь как 00:00', () => {
    expect(timeKey('2026-09-30T12:00:00Z', MSK)).toBe('15:00')
    expect(timeKey('2026-09-30T21:00:00Z', MSK)).toBe('00:00')
  })

  it('parseTimeKey терпит секунды и отвергает мусор', () => {
    expect(parseTimeKey('15:30')).toEqual([15, 30])
    expect(parseTimeKey('09:05:00')).toEqual([9, 5])
    expect(parseTimeKey('24:00')).toBeNull()
    expect(parseTimeKey('')).toBeNull()
  })

  it('dayTimeToIso — момент по МСК', () => {
    expect(dayTimeToIso('2026-09-30', '15:00', MSK)).toBe('2026-09-30T12:00:00.000Z')
    expect(dayTimeToIso('2026-09-30', 'xx', MSK)).toBeNull()
  })

  it('formatDueShort печатает час только выбранного времени', () => {
    // Сокращение месяца даёт ICU («сент»), его не зашиваем.
    const noon = '2026-09-30T09:00:00.000Z'
    expect(formatDueShort(noon, false)).toBe(shortDate(noon))
    expect(formatDueShort(noon, undefined)).toBe(shortDate(noon))
    const at15 = '2026-09-30T12:00:00.000Z'
    expect(formatDueShort(at15, true)).toBe(`${shortDate(at15)} 15:00`)
  })

  it('compareDue: день, внутри дня «весь день» раньше времени, без срока в конце', () => {
    const allDay = { due_at: '2026-09-30T09:00:00.000Z', due_has_time: false }
    const morning = { due_at: '2026-09-30T06:00:00.000Z', due_has_time: true } // 09:00
    const evening = { due_at: '2026-09-30T15:00:00.000Z', due_has_time: true } // 18:00
    const tomorrow = { due_at: '2026-10-01T09:00:00.000Z', due_has_time: false }
    const none = { due_at: null }
    const sorted = [none, evening, tomorrow, morning, allDay].sort(compareDue)
    expect(sorted).toEqual([allDay, morning, evening, tomorrow, none])
  })
})

describe('taskDateTime — правило патча', () => {
  it('splitDateTime: время только при флаге', () => {
    expect(splitDateTime('2026-09-30T12:00:00.000Z', true)).toEqual({ day: '2026-09-30', time: '15:00' })
    expect(splitDateTime('2026-09-30T09:00:00.000Z', false)).toEqual({ day: '2026-09-30', time: '' })
    expect(splitDateTime(null, true)).toEqual({ day: '', time: '' })
    expect(
      taskDateTime(
        { due_at: null, start_at: '2026-09-29T07:00:00.000Z', start_has_time: true },
        'start',
      ),
    ).toEqual({ day: '2026-09-29', time: '10:00' })
  })

  it('день без времени — полдень и флаг только в кэше', () => {
    expect(dateTimePatch('due', { day: '2026-09-30', time: '' })).toEqual({
      body: { due_at: '2026-09-30T09:00:00.000Z' },
      cache: { due_at: '2026-09-30T09:00:00.000Z', due_has_time: false },
    })
  })

  it('время — момент и флаг true в теле', () => {
    expect(dateTimePatch('start', { day: '2026-09-30', time: '15:30' })).toEqual({
      body: { start_at: '2026-09-30T12:30:00.000Z', start_has_time: true },
      cache: { start_at: '2026-09-30T12:30:00.000Z', start_has_time: true },
    })
  })

  it('снятая дата снимает и время', () => {
    expect(dateTimePatch('due', { day: '', time: '' })).toEqual({
      body: { due_at: null },
      cache: { due_at: null, due_has_time: false },
    })
  })

  it('обрывки набора не сохраняются', () => {
    // Промежуточный год из Chrome — это не срок.
    expect(dateTimePatch('due', { day: '0202-10-15', time: '' })).toBeNull()
    expect(dateTimePatch('due', { day: '', time: '15:00' })).toBeNull()
    expect(dateTimePatch('due', { day: '2026-09-30', time: '99:99' })).toBeNull()
  })
})

describe('dateDraft — черновик', () => {
  const server = { day: '2026-09-30', time: '15:00' }

  it('сервер не перетирает несохранённый ввод', () => {
    const typing = { value: { day: '2026-10-0', time: '15:00' }, dirty: true }
    expect(syncDraft(typing, server)).toBe(typing)
    const clean = { value: { day: '2026-09-29', time: '' }, dirty: false }
    expect(syncDraft(clean, server)).toEqual({ value: server, dirty: false })
  })

  it('уход фокуса: сохранить, ничего или откатить обрывок', () => {
    expect(commitAction({ value: server, dirty: false }, server, false)).toBe('none')
    expect(commitAction({ value: { day: '2026-10-01', time: '15:00' }, dirty: true }, server, false)).toBe(
      'commit',
    )
    expect(commitAction({ value: server, dirty: true }, server, false)).toBe('none')
    expect(commitAction({ value: { day: '', time: '' }, dirty: true }, server, true)).toBe('revert')
  })
})
