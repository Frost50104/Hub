import { describe, expect, it } from 'vitest'

import { fmtDay, fmtDayWeekday, homeStatsView } from './homeStats'
import type { MyStats } from './stats'

function stats(over: Partial<MyStats> = {}): MyStats {
  // 30 точек: по одной закрытой задаче в каждый из последних трёх дней,
  // по одной заведённой — в последние два.
  const daily = Array.from({ length: 30 }, (_, i) => ({
    day: `2026-08-${String(i + 1).padStart(2, '0')}`,
    count: i >= 27 ? 1 : 0,
    created: i >= 28 ? 1 : 0,
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
    for (const period of [7, 30] as const) {
      const view = homeStatsView(stats(), period)
      expect(view.overdue).toBe(2)
      expect(view.open).toBe(9)
    }
  })

  it('два ряда в точке и максимумы по каждому', () => {
    const view = homeStatsView(stats(), 7)
    expect(view.points[6]).toMatchObject({ completed: 1, created: 1 })
    expect(view.points[3]).toMatchObject({ completed: 0, created: 0 })
    expect(view.max).toEqual({ completed: 1, created: 1 })
    expect(view.startLabel).toBe('24 августа')
    expect(view.endLabel).toBe('30 августа')
  })

  it('старый ответ без `created` читается нулями, а не ломает график', () => {
    const legacy = stats({ daily: stats().daily.map(({ day, count }) => ({ day, count })) })
    const view = homeStatsView(legacy, 30)
    expect(view.points.every((p) => p.created === 0)).toBe(true)
    expect(view.max.created).toBe(0)
    expect(view.isEmpty).toBe(false)
  })

  it('пусто — только когда ОБА ряда нулевые', () => {
    const quiet = stats({ daily: stats().daily.map((p) => ({ ...p, count: 0, created: 0 })) })
    expect(homeStatsView(quiet, 30).isEmpty).toBe(true)
    const onlyCreated = stats({ daily: stats().daily.map((p) => ({ ...p, count: 0 })) })
    expect(homeStatsView(onlyCreated, 30).isEmpty).toBe(false)
  })

  it('подписи дня: короткая для оси, длинная с днём недели для тултипа', () => {
    const view = homeStatsView(stats(), 7)
    expect(view.points[6]!.label).toBe('30 августа')
    expect(view.points[6]!.labelLong).toBe('30 августа, вс')
  })
})

describe('fmtDay', () => {
  it('читает дату как локальную, а не как UTC', () => {
    expect(fmtDay('2026-08-19')).toBe('19 августа')
    expect(fmtDayWeekday('2026-08-19')).toBe('19 августа, ср')
  })
})
