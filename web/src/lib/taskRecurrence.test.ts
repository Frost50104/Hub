import { describe, expect, it } from 'vitest'

import {
  bodyFor,
  canSetRecurrence,
  describeRecurrence,
  presetOf,
  recurrenceBlockReason,
  shortRecurrence,
} from './taskRecurrence'

const NBSP = ' '

describe('describeRecurrence', () => {
  it('пресеты — простыми словами', () => {
    expect(describeRecurrence({ freq: 'day', step: 1 })).toBe('каждый день')
    expect(describeRecurrence({ freq: 'weekday', step: 1 })).toBe('по будням')
    expect(describeRecurrence({ freq: 'week', step: 1 })).toBe('каждую неделю')
    expect(describeRecurrence({ freq: 'month', step: 1 })).toBe('каждый месяц')
  })

  it('свой интервал — с числительными', () => {
    expect(describeRecurrence({ freq: 'week', step: 2 })).toBe(`каждые 2${NBSP}недели`)
    expect(describeRecurrence({ freq: 'day', step: 5 })).toBe(`каждые 5${NBSP}дней`)
    // 21 по-русски единственное число — «каждые 21 день», а не «дней».
    expect(describeRecurrence({ freq: 'day', step: 21 })).toBe(`каждые 21${NBSP}день`)
    expect(describeRecurrence({ freq: 'week', step: 11 })).toBe(`каждые 11${NBSP}недель`)
  })

  it('«по будням» интервала не имеет', () => {
    expect(describeRecurrence({ freq: 'weekday', step: 3 })).toBe('по будням')
  })
})

describe('shortRecurrence', () => {
  it('коротко — для чипа в списке', () => {
    expect(shortRecurrence({ freq: 'week', step: 1 })).toBe('нед')
    expect(shortRecurrence({ freq: 'week', step: 2 })).toBe('2 нед')
    expect(shortRecurrence({ freq: 'weekday', step: 1 })).toBe('будни')
    expect(shortRecurrence({ freq: 'month', step: 3 })).toBe('3 мес')
  })
})

describe('presetOf', () => {
  it('интервал больше единицы — это «свой»', () => {
    expect(presetOf({ freq: 'day', step: 1 })).toBe('day')
    expect(presetOf({ freq: 'day', step: 2 })).toBe('custom')
    expect(presetOf(null)).toBeNull()
  })
})

describe('bodyFor', () => {
  it('пресет всегда даёт шаг 1', () => {
    expect(bodyFor('week', 5, 'day')).toEqual({ freq: 'week', step: 1 })
  })

  it('свой интервал берёт единицу измерения и число', () => {
    expect(bodyFor('custom', 3, 'month')).toEqual({ freq: 'month', step: 3 })
  })

  it('мусор в поле не уедет на сервер', () => {
    expect(bodyFor('custom', 0, 'day')).toEqual({ freq: 'day', step: 1 })
    expect(bodyFor('custom', 999, 'day')).toEqual({ freq: 'day', step: 365 })
    expect(bodyFor('custom', Number.NaN, 'week')).toEqual({ freq: 'week', step: 1 })
  })
})

describe('гейты — зеркало сервера', () => {
  it('без срока считать не от чего', () => {
    expect(canSetRecurrence({ due_at: null, parent_task_id: null })).toBe(false)
    expect(recurrenceBlockReason({ due_at: null, parent_task_id: null })).toMatch(/срок/i)
  })

  it('на подзадаче повтора нет', () => {
    const sub = { due_at: '2026-09-22T09:00:00Z', parent_task_id: 'p1' }
    expect(canSetRecurrence(sub)).toBe(false)
    expect(recurrenceBlockReason(sub)).toMatch(/подзадач/i)
  })

  it('обычная задача со сроком — можно', () => {
    const task = { due_at: '2026-09-22T09:00:00Z', parent_task_id: null }
    expect(canSetRecurrence(task)).toBe(true)
    expect(recurrenceBlockReason(task)).toBeNull()
  })
})
