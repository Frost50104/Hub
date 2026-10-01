import { describe, expect, it } from 'vitest'

import { barTop, nearestSlot, niceTop, readoutSide, stepSelection, trendLayout } from './trendChart'

describe('niceTop', () => {
  it('чётный верх не меньше 2: деления 0 / половина / верх — целые', () => {
    expect(niceTop(0)).toBe(2)
    expect(niceTop(1)).toBe(2)
    expect(niceTop(3)).toBe(4)
    expect(niceTop(6)).toBe(6)
    expect(niceTop(7)).toBe(8)
    expect(niceTop(Number.NaN)).toBe(2)
  })
})

describe('trendLayout', () => {
  it('30 дней на 1000px: ячейки без наложения, два столбика в ячейке', () => {
    const l = trendLayout(30, 1000, 140, 6)
    expect(l.slots).toHaveLength(30)
    expect(l.slots[0]!.x).toBe(28)
    const last = l.slots[29]!
    expect(last.x + last.w).toBeCloseTo(1000, 3)
    expect(l.barW * 2 + l.barGap).toBeLessThanOrEqual(last.w + 1e-6)
    expect(l.ticks.map((t) => t.value)).toEqual([0, 3, 6])
  })

  it('7 дней — потолок ширины столбика, иначе плашки', () => {
    const l = trendLayout(7, 1000, 140, 4, { maxBarW: 20 })
    expect(l.barW).toBe(20)
  })

  it('узкий экран: столбик не уже 2px, ячейка не отрицательная', () => {
    const l = trendLayout(30, 320, 96, 4)
    expect(l.barW).toBeGreaterThanOrEqual(2)
    expect(l.slots.every((s) => s.w >= 0)).toBe(true)
  })

  it('пустой ряд всё равно даёт сетку', () => {
    const l = trendLayout(0, 400, 100, 0)
    expect(l.slots).toHaveLength(0)
    expect(l.ticks.map((t) => t.value)).toEqual([0, 1, 2])
  })
})

describe('barTop', () => {
  const l = trendLayout(7, 700, 140, 4)
  it('ноль — полоска 2px над базой, не пустота', () => {
    expect(barTop(0, l)).toBe(l.plot.y1 - 2)
  })
  it('единица не ниже 4px; верх шкалы упирается в y0', () => {
    expect(l.plot.y1 - barTop(1, l)).toBeGreaterThanOrEqual(4)
    expect(barTop(4, l)).toBe(l.plot.y0)
  })
})

describe('nearestSlot', () => {
  const l = trendLayout(3, 328, 100, 2)
  it('ближайший день, при равенстве — более ранний', () => {
    expect(nearestSlot(l.slots, l.slots[0]!.xc)).toBe(0)
    const mid = (l.slots[1]!.xc + l.slots[2]!.xc) / 2
    expect(nearestSlot(l.slots, mid)).toBe(1)
    expect(nearestSlot(l.slots, 10_000)).toBe(2)
    expect(nearestSlot([], 10)).toBeNull()
  })
})

describe('readoutSide', () => {
  it('после 60 % ширины тултип уходит влево', () => {
    expect(readoutSide(100, 1000)).toBe('right')
    expect(readoutSide(650, 1000)).toBe('left')
    expect(readoutSide(10, 0)).toBe('right')
  })
})

describe('stepSelection', () => {
  it('стрелки ходят в пределах ряда, Esc снимает, прочее игнорируется', () => {
    expect(stepSelection(null, 'ArrowRight', 7)).toBe(6)
    expect(stepSelection(null, 'ArrowLeft', 7)).toBe(6)
    expect(stepSelection(6, 'ArrowRight', 7)).toBe(6)
    expect(stepSelection(0, 'ArrowLeft', 7)).toBe(0)
    expect(stepSelection(3, 'Home', 7)).toBe(0)
    expect(stepSelection(3, 'End', 7)).toBe(6)
    expect(stepSelection(3, 'Escape', 7)).toBeNull()
    expect(stepSelection(3, 'a', 7)).toBeUndefined()
    expect(stepSelection(null, 'ArrowRight', 0)).toBeUndefined()
  })
})
