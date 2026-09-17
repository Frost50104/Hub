import { describe, expect, it } from 'vitest'

import type { RaceChartPoint } from './race'
import { chartGeometry, nearestPoint, raceDayLabel, raceDays } from './raceChart'

const pt = (day: string, cells: number): RaceChartPoint => ({ day, cells, pct: null, avg: null, is_record: false, live: false })

describe('геометрия графика', () => {
  it('дни заезда — все, включая будущие', () => {
    expect(raceDays('2026-09-21', '2026-09-27')).toHaveLength(7)
    expect(raceDays('2026-09-21', '2026-09-21')).toEqual(['2026-09-21'])
  })

  it('пустой ряд — без пути, оси на месте; одна точка — только точка', () => {
    const empty = chartGeometry({ starts_on: '2026-09-21', ends_on: '2026-09-27', points: [] }, { width: 400, height: 200 })
    expect(empty.path).toBe('')
    expect(empty.xTicks.length).toBe(7)
    expect(empty.yTicks.map((t) => t.label)).toEqual(['0', '100', '200', '300', '400'])
    const one = chartGeometry({ starts_on: '2026-09-21', ends_on: '2026-09-27', points: [pt('2026-09-21', 120)] }, { width: 400, height: 200 })
    expect(one.dots.length).toBe(1)
    expect(one.path.startsWith('M')).toBe(true)
  })

  it('y инвертирован: 400 — верхний отступ, 0 — нижний; база на 100', () => {
    const g = chartGeometry(
      { starts_on: '2026-09-21', ends_on: '2026-09-22', points: [pt('2026-09-21', 400), pt('2026-09-22', 0)] },
      { width: 400, height: 200, pad: { l: 30, r: 10, t: 10, b: 20 } },
    )
    expect(g.dots[0]?.y).toBe(10)
    expect(g.dots[1]?.y).toBe(180)
    expect(g.baselineY).toBeCloseTo(180 - 170 / 4, 5)
  })

  it('пропущенный день оставляет разрыв (новая подкривая), 14 дней — подписи через одну', () => {
    const g = chartGeometry(
      { starts_on: '2026-09-21', ends_on: '2026-10-04', points: [pt('2026-09-21', 100), pt('2026-09-23', 120)] },
      { width: 600, height: 200 },
    )
    expect(g.path.split('M').filter(Boolean).length).toBe(2)
    expect(g.xTicks.length).toBe(8)
    expect(g.xTicks[g.xTicks.length - 1]?.day).toBe('2026-10-04')
  })

  it('ближайшая точка по x, при равенстве — более ранняя', () => {
    const dots = [
      { x: 10, y: 0, point: pt('2026-09-21', 1) },
      { x: 30, y: 0, point: pt('2026-09-22', 2) },
    ]
    expect(nearestPoint(dots, 20)?.point.day).toBe('2026-09-21')
    expect(nearestPoint(dots, 26)?.point.day).toBe('2026-09-22')
    expect(nearestPoint([], 5)).toBeNull()
  })

  it('подпись дня — короткая дата без года', () => {
    expect(raceDayLabel('2026-09-08')).toMatch(/8\s?сен/)
  })
})
