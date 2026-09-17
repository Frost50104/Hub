/**
 * Геометрия трека «Гусиной гонки» — чистые функции под vitest.
 * Клетки → проценты ширины, тики, порядок и позиции дорожек, длительность
 * переезда гуся. Формулу самих клеток считает сервер.
 */
import type { RaceParticipant } from '@/lib/race'

export const TRACK_MAX = 400
export const START_CELL = 100
export const TICKS = [0, 100, 200, 300, 400] as const

export type TickKind = 'zero' | 'start' | 'plain' | 'max'

export interface TrackTick {
  cell: number
  pct: number
  label: string
  kind: TickKind
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v))
}

/** 0..400 клеток → 0..100 % ширины дорожки (линейно, с обрезкой). */
export function cellsToPercent(cells: number): number {
  return clamp(cells, 0, TRACK_MAX) / (TRACK_MAX / 100)
}

export function tickLabel(cell: number): string {
  if (cell === START_CELL) return 'старт · 100'
  if (cell === TRACK_MAX) return 'максимум · 400'
  return String(cell)
}

export function trackTicks(): TrackTick[] {
  return TICKS.map((cell) => ({
    cell,
    pct: cellsToPercent(cell),
    label: tickLabel(cell),
    kind: cell === 0 ? 'zero' : cell === START_CELL ? 'start' : cell === TRACK_MAX ? 'max' : 'plain',
  }))
}

/** Порядок дорожек: по месту (без места — в хвост), затем по клеткам и имени. */
export function laneOrder<T extends Pick<RaceParticipant, 'place' | 'cells' | 'name'>>(rows: T[]): T[] {
  return [...rows].sort((a, b) => {
    if (a.place != null && b.place != null && a.place !== b.place) return a.place - b.place
    if ((a.place == null) !== (b.place == null)) return a.place == null ? 1 : -1
    if (a.cells !== b.cells) return b.cells - a.cells
    return a.name.localeCompare(b.name, 'ru')
  })
}

export interface LanePositions {
  byId: Record<string, number>
  height: number
}

/** Абсолютные `translateY` дорожек: перестановка мест анимируется той же
 *  CSS-транзицией, что и движение гуся, без замеров DOM. */
export function lanePositions<T extends { store_id: string }>(rows: T[], laneHeight: number): LanePositions {
  const byId: Record<string, number> = {}
  rows.forEach((r, i) => {
    byId[r.store_id] = i * laneHeight
  })
  return { byId, height: rows.length * laneHeight }
}

export const MOVE_MS_MIN = 600
export const MOVE_MS_MAX = 2400

/** 100 клеток — 800 мс; стартовый выезд на 400 — 2,4 с. */
export function moveDurationMs(prevCells: number | null, nextCells: number): number {
  const from = prevCells ?? 0
  return clamp(Math.abs(nextCells - from) * 8, MOVE_MS_MIN, MOVE_MS_MAX)
}

export type GlowLevel = 'none' | 'gold' | 'max'

export function glowLevel(cells: number): GlowLevel {
  if (cells >= TRACK_MAX) return 'max'
  if (cells > 200) return 'gold'
  return 'none'
}
