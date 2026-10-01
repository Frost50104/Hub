import { describe, expect, it } from 'vitest'

import { LEADER_COLUMNS, columnMe, columnRows, leaderColumn, meLine, placeLabel } from './leaders'
import type { Leaders } from './stats'

const data: Leaders = {
  window_days: 30,
  completed: [
    { employee_id: 'a', full_name: 'Анна', count: 9, rank: 1 },
    { employee_id: 'me', full_name: 'Я', count: 7, rank: 2 },
  ],
  created: [{ employee_id: 'a', full_name: 'Анна', count: 3, rank: 1 }],
  overdue: [],
  me: { completed: { rank: 2, count: 7 }, created: { rank: 5, count: 1 }, overdue: null },
}

describe('колонки', () => {
  it('порядок фиксирован: выполнили, создали, просрочено; у просрочки красный тон', () => {
    expect(LEADER_COLUMNS.map((c) => c.key)).toEqual(['completed', 'created', 'overdue'])
    expect(leaderColumn('overdue').tone).toBe('danger')
    expect(leaderColumn('overdue').title).toContain('сейчас')
    expect(columnRows(data, 'created')).toHaveLength(1)
    expect(columnMe(data, 'overdue')).toBeNull()
  })
})

describe('meLine', () => {
  it('в тройке строки нет — её несёт «— это вы» в строке', () => {
    expect(meLine('completed', data.me.completed, data.completed, 'me')).toBeNull()
  })

  it('вне тройки — место и число', () => {
    expect(meLine('created', data.me.created, data.created, 'me')).toBe('Вы — 5-е место · 1')
  })

  it('ноль — честный текст, у просрочки — хорошая новость', () => {
    expect(meLine('overdue', null, [], 'me')).toBe('У вас просроченных нет')
    expect(meLine('completed', null, [], 'me')).toContain('не закрывали')
    expect(meLine('created', null, [], 'me')).toContain('не заводили')
  })

  it('без своего id не считаем себя в тройке', () => {
    expect(meLine('completed', data.me.completed, data.completed, undefined)).toBe('Вы — 2-е место · 7')
  })
})

describe('placeLabel', () => {
  it('средний род на все числа', () => {
    expect(placeLabel(1)).toBe('1-е место')
    expect(placeLabel(11)).toBe('11-е место')
  })
})
