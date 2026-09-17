/**
 * Геометрия SVG-графика «позиция по дням заезда» — чистые функции в пикселях.
 * X — все дни заезда (будущие дни остаются пустыми), Y — фиксированно 0..400,
 * пунктир базы на 100. Единственная серия: точка за день.
 */
import type { RaceChart, RaceChartPoint } from '@/lib/race'
import { addDaysKey, dueDayToIso, shortDate } from '@/lib/taskDates'

export interface ChartPad {
  l: number
  r: number
  t: number
  b: number
}

export interface ChartDot {
  x: number
  y: number
  point: RaceChartPoint
}

export interface ChartGeometry {
  width: number
  height: number
  plot: { x0: number; x1: number; y0: number; y1: number }
  days: string[]
  path: string
  area: string
  dots: ChartDot[]
  xTicks: { x: number; label: string; day: string }[]
  yTicks: { y: number; label: string }[]
  baselineY: number
}

export const DEFAULT_PAD: ChartPad = { l: 36, r: 12, t: 12, b: 24 }
const Y_MAX = 400

export function raceDays(startsOn: string, endsOn: string): string[] {
  const out: string[] = []
  let day = startsOn
  for (let i = 0; i < 60 && day <= endsOn; i++) {
    out.push(day)
    day = addDaysKey(day, 1)
  }
  return out
}

export function raceDayLabel(day: string): string {
  return shortDate(dueDayToIso(day))
}

export function chartGeometry(
  chart: Pick<RaceChart, 'starts_on' | 'ends_on' | 'points'>,
  opts: { width: number; height: number; pad?: ChartPad },
): ChartGeometry {
  const pad = opts.pad ?? DEFAULT_PAD
  const x0 = pad.l
  const x1 = Math.max(pad.l + 1, opts.width - pad.r)
  const y0 = pad.t
  const y1 = Math.max(pad.t + 1, opts.height - pad.b)
  const days = raceDays(chart.starts_on, chart.ends_on)
  const n = days.length
  const xOf = (idx: number) => (n <= 1 ? (x0 + x1) / 2 : x0 + (idx / (n - 1)) * (x1 - x0))
  const yOf = (cells: number) => y1 - (Math.max(0, Math.min(Y_MAX, cells)) / Y_MAX) * (y1 - y0)

  const index = new Map(days.map((d, i) => [d, i] as const))
  const dots: ChartDot[] = chart.points
    .filter((pt) => index.has(pt.day))
    .map((pt) => ({ x: xOf(index.get(pt.day) ?? 0), y: yOf(pt.cells), point: pt }))
    .sort((a, b) => a.x - b.x)

  let path = ''
  let prevIdx: number | null = null
  for (const d of dots) {
    const idx = index.get(d.point.day) ?? 0
    const cont = prevIdx !== null && idx === prevIdx + 1
    path += `${cont ? 'L' : 'M'}${d.x.toFixed(1)} ${d.y.toFixed(1)} `
    prevIdx = idx
  }
  path = path.trim()
  let area = ''
  if (dots.length >= 2) {
    const first = dots[0]
    const last = dots[dots.length - 1]
    if (first && last) {
      area = `M${first.x.toFixed(1)} ${y1.toFixed(1)} ${dots
        .map((d) => `L${d.x.toFixed(1)} ${d.y.toFixed(1)}`)
        .join(' ')} L${last.x.toFixed(1)} ${y1.toFixed(1)} Z`
    }
  }

  const step = n > 8 ? 2 : 1
  const xTicks = days
    .map((day, i) => ({ x: xOf(i), label: raceDayLabel(day), day, i }))
    .filter((t) => t.i % step === 0 || t.i === n - 1)
    .map(({ x, label, day }) => ({ x, label, day }))
  const yTicks = [0, 100, 200, 300, 400].map((v) => ({ y: yOf(v), label: String(v) }))

  return { width: opts.width, height: opts.height, plot: { x0, x1, y0, y1 }, days, path, area, dots, xTicks, yTicks, baselineY: yOf(100) }
}

/** Ближайшая по X точка; при равенстве — более ранняя. */
export function nearestPoint(dots: ChartDot[], xPx: number): ChartDot | null {
  let best: ChartDot | null = null
  let bestDist = Number.POSITIVE_INFINITY
  for (const d of dots) {
    const dist = Math.abs(d.x - xPx)
    if (dist < bestDist) {
      best = d
      bestDist = dist
    }
  }
  return best
}
