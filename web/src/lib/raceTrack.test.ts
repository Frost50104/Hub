import { describe, expect, it } from 'vitest'

import { cellsToPercent, glowLevel, laneOrder, lanePositions, moveDurationMs, trackTicks } from './raceTrack'

const row = (name: string, cells: number, place: number | null) => ({ store_id: name, name, cells, place })

describe('геометрия трека', () => {
  it('клетки линейно ложатся в проценты и обрезаются по краям', () => {
    expect(cellsToPercent(0)).toBe(0)
    expect(cellsToPercent(100)).toBe(25)
    expect(cellsToPercent(400)).toBe(100)
    expect(cellsToPercent(-5)).toBe(0)
    expect(cellsToPercent(450)).toBe(100)
  })

  it('тики совпадают со шкалой гусей и подписаны старт/максимум', () => {
    const ticks = trackTicks()
    expect(ticks.map((t) => t.pct)).toEqual([0, 25, 50, 75, 100])
    expect(ticks.find((t) => t.cell === 100)?.kind).toBe('start')
    expect(ticks.find((t) => t.cell === 400)?.label).toContain('максимум')
  })

  it('порядок дорожек: по месту, без места — последними, затем клетки и имя', () => {
    const rows = [row('Б', 150, null), row('А', 150, 2), row('В', 300, 1), row('Г', 200, null)]
    expect(laneOrder(rows).map((r) => r.name)).toEqual(['В', 'А', 'Г', 'Б'])
  })

  it('позиции дорожек — index × высота, высота контейнера — n × высота', () => {
    const pos = lanePositions([row('А', 1, 1), row('Б', 1, 2)], 36)
    expect(pos).toEqual({ byId: { А: 0, Б: 36 }, height: 72 })
  })

  it('длительность переезда: 100 клеток → 800 мс, границы 600 и 2400', () => {
    expect(moveDurationMs(100, 200)).toBe(800)
    expect(moveDurationMs(100, 101)).toBe(600)
    expect(moveDurationMs(null, 400)).toBe(2400)
  })

  it('сияние: 200 — нет, 201 — золото, 400 — максимум', () => {
    expect(glowLevel(200)).toBe('none')
    expect(glowLevel(201)).toBe('gold')
    expect(glowLevel(399)).toBe('gold')
    expect(glowLevel(400)).toBe('max')
  })
})
