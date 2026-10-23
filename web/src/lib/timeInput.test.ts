import { describe, expect, it } from 'vitest'

import { checkTrim, formatClockInput, parseClock, trimmedDuration } from './timeInput'

describe('parseClock', () => {
  it('разбирает м:сс, ч:мм:сс, секунды и минуты', () => {
    expect(parseClock('1:05')).toBe(65)
    expect(parseClock('01:05:30')).toBe(3930)
    expect(parseClock('95')).toBe(95)
    expect(parseClock('2м')).toBe(120)
    expect(parseClock(' 1 : 05 ')).toBe(65)
    expect(parseClock('1.05')).toBe(65)
  })

  it('отвергает мусор и секунды ≥ 60', () => {
    expect(parseClock('')).toBeNull()
    expect(parseClock('1:65')).toBeNull()
    expect(parseClock('1:2:3:4')).toBeNull()
    expect(parseClock('abc')).toBeNull()
  })
})

describe('formatClockInput', () => {
  it('без ведущих нулей у старшего разряда', () => {
    expect(formatClockInput(65)).toBe('1:05')
    expect(formatClockInput(3930)).toBe('1:05:30')
    expect(formatClockInput(0)).toBe('0:00')
    expect(formatClockInput(null)).toBe('')
  })
})

describe('checkTrim', () => {
  it('принимает пустые поля и валидные границы', () => {
    expect(checkTrim('', '', 231)).toEqual({ start: 0, end: null, problem: null })
    expect(checkTrim('0:10', '3:00', 231)).toEqual({ start: 10, end: 180, problem: null })
    expect(trimmedDuration(231, 10, 180)).toBe(170)
    expect(trimmedDuration(231, 10, null)).toBe(221)
    expect(trimmedDuration(null, 10, null)).toBeNull()
  })

  it('называет ошибку человеку', () => {
    expect(checkTrim('4:00', '', 231).problem).toBe('Начало подрезки за концом записи')
    expect(checkTrim('1:00', '0:30', 231).problem).toBe('«До» раньше, чем «с»')
    expect(checkTrim('0:00', '5:00', 231).problem).toBe('Конец подрезки за концом записи')
    expect(checkTrim('x', '', 231).problem).toBe('Время — в виде м:сс или ч:мм:сс')
    // Длительность неизвестна (часть ещё конвертируется) — проверяем только порядок.
    expect(checkTrim('0:10', '0:05', null).problem).toBe('«До» раньше, чем «с»')
    expect(checkTrim('0:10', '9:59', null).problem).toBeNull()
  })
})
