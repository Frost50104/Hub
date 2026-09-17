import { describe, expect, it } from 'vitest'

import { countdownParts, formatCountdown, nextTickMs } from './raceCountdown'
import { NBSP } from './typography'

const T0 = Date.UTC(2026, 8, 21, 0, 0, 0)

describe('обратный отсчёт заезда', () => {
  it('раскладывает остаток на дни, часы, минуты, секунды', () => {
    const target = new Date(T0 + (1 * 86400 + 2 * 3600 + 3 * 60 + 4) * 1000).toISOString()
    expect(countdownParts(target, T0)).toMatchObject({ over: false, days: 1, hours: 2, minutes: 3, seconds: 4 })
  })

  it('ноль и прошлое — «завершён», мусор в дате не роняет', () => {
    expect(countdownParts(new Date(T0).toISOString(), T0).over).toBe(true)
    expect(countdownParts(new Date(T0 - 1).toISOString(), T0).over).toBe(true)
    expect(countdownParts('not-a-date', T0).over).toBe(true)
  })

  it('формат: больше дня — со словом «день» и склонением, меньше — только часы', () => {
    const day = countdownParts(new Date(T0 + (86400 + 7384) * 1000).toISOString(), T0)
    expect(formatCountdown(day, 'to-end')).toBe(`Осталось 1${NBSP}день 02:03:04`)
    const hours = countdownParts(new Date(T0 + 7384 * 1000).toISOString(), T0)
    expect(formatCountdown(hours, 'to-end')).toBe('Осталось 02:03:04')
    expect(formatCountdown(hours, 'to-start')).toBe('Старт через 02:03:04')
    expect(formatCountdown(hours, 'to-end', true)).toBe('02:03:04')
    expect(formatCountdown(countdownParts(new Date(T0).toISOString(), T0), 'to-end')).toBe('Заезд завершён')
  })

  it('тик — до следующей целой секунды', () => {
    expect(nextTickMs(T0 + 250)).toBe(750)
    expect(nextTickMs(T0)).toBe(1000)
  })
})
