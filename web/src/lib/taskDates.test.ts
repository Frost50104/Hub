import { describe, expect, it } from 'vitest'

import {
  addDaysKey,
  dayEndIso,
  dayKey,
  dayStartIso,
  dueDayToIso,
  isOverdue,
  overdueDays,
  todayKey,
} from './taskDates'

const MSK = 'Europe/Moscow'

describe('taskDates — календарный день display tz', () => {
  it('dayKey режет сутки по МСК, а не по UTC', () => {
    expect(dayKey('2026-08-21T20:59:59Z', MSK)).toBe('2026-08-21')
    expect(dayKey('2026-08-21T21:00:00Z', MSK)).toBe('2026-08-22')
  })

  it('dueDayToIso — полдень МСК, roundtrip через dayKey', () => {
    expect(dueDayToIso('2026-08-22', MSK)).toBe('2026-08-22T09:00:00.000Z')
    expect(dayKey(dueDayToIso('2026-08-22', MSK), MSK)).toBe('2026-08-22')
    expect(dayKey(dueDayToIso('2026-01-01', MSK), MSK)).toBe('2026-01-01')
  })

  it('границы дня для фильтров', () => {
    expect(dayStartIso('2026-08-22', MSK)).toBe('2026-08-21T21:00:00.000Z')
    expect(dayEndIso('2026-08-22', MSK)).toBe('2026-08-22T20:59:59.999Z')
    expect(addDaysKey('2026-08-31', 1)).toBe('2026-09-01')
    expect(addDaysKey('2026-03-01', -1)).toBe('2026-02-28')
  })

  it('срок сегодня не просрочен до конца дня, после полуночи — на 1 день', () => {
    const due = dueDayToIso('2026-08-20', MSK)
    const evening = Date.parse('2026-08-20T20:59:00Z') // 23:59 МСК
    const afterMidnight = Date.parse('2026-08-20T21:00:30Z') // 00:00:30 МСК 21.08
    expect(todayKey(evening, MSK)).toBe('2026-08-20')
    expect(isOverdue(due, 'todo', evening)).toBe(false)
    expect(isOverdue(due, 'todo', afterMidnight)).toBe(true)
    expect(isOverdue(due, 'done', afterMidnight)).toBe(false)
    expect(isOverdue(null, 'todo', afterMidnight)).toBe(false)
    expect(overdueDays(due, afterMidnight)).toBe(1)
    expect(overdueDays(due, Date.parse('2026-08-23T12:00:00Z'))).toBe(3)
  })
})
