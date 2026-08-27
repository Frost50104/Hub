import { describe, expect, it } from 'vitest'

import { fmtDay, homeStatsView } from './homeStats'
import type { MyStats } from './stats'

function stats(over: Partial<MyStats> = {}): MyStats {
  // 30 точек: по одной закрытой задаче в каждый из последних трёх дней.
  const daily = Array.from({ length: 30 }, (_, i) => ({
    day: `2026-08-${String(i + 1).padStart(2, '0')}`,
    count: i >= 27 ? 1 : 0,
  }))
  return {
    completed_7: 3,
    completed_30: 3,
    created_7: 1,
    created_30: 5,
    overdue_now: 2,
    open_now: 9,
    daily,
    ...over,
  }
}

describe('homeStatsView', () => {
  it('«7 дней» — ХВОСТ ряда, а не голова: последняя точка это сегодня', () => {
    const view = homeStatsView(stats(), 7)
    expect(view.points).toHaveLength(7)
    expect(view.points[6]!.key).toBe('2026-08-30')
    expect(view.points[0]!.key).toBe('2026-08-24')
  })

  it('30 дней отдаёт весь ряд', () => {
    expect(homeStatsView(stats(), 30).points).toHaveLength(30)
  })

  it('числа за период берутся из своей пары полей', () => {
    const week = homeStatsView(stats(), 7)
    const month = homeStatsView(stats(), 30)
    expect(week.created).toBe(1)
    expect(month.created).toBe(5)
  })

  it('«просрочено» и «в работе» от периода не зависят', () => {
    // Эти два числа — состояние на сейчас, а не за окно: переключатель их
    // менять не должен, иначе подпись врёт.
    for (const period of [7, 30] as const) {
      const view = homeStatsView(stats(), period)
      expect(view.overdue).toBe(2)
      expect(view.open).toBe(9)
    }
  })

  it('максимум и подписи краёв', () => {
    const view = homeStatsView(stats(), 7)
    expect(view.maxLabel).toBe('Максимум за день — 1')
    expect(view.startLabel).toBe('24 августа')
    expect(view.endLabel).toBe('30 августа')
  })

  it('пустой период помечается — вместо графика будет строка', () => {
    const quiet = stats({ daily: stats().daily.map((p) => ({ ...p, count: 0 })) })
    expect(homeStatsView(quiet, 30).isEmpty).toBe(true)
    expect(homeStatsView(stats(), 7).isEmpty).toBe(false)
  })

  it('подпись столбика склоняет число', () => {
    const view = homeStatsView(stats(), 7)
    expect(view.points[6]!.title).toContain('1 закрыта')
    expect(view.points[0]!.title).toContain('0 закрыто')
  })
})

describe('fmtDay', () => {
  it('читает дату как локальную, а не как UTC', () => {
    // Голая дата в minus-зонах уезжала бы на день назад.
    expect(fmtDay('2026-08-19')).toBe('19 августа')
  })
})
