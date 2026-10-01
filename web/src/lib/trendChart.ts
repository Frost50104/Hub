/**
 * Геометрия графика «выполнено / создано по дням» на «Главной» — чистая
 * арифметика в пикселях (как `raceChart.ts`): SVG рисуется без `viewBox`,
 * чтобы подписи не уезжали ниже 12px на телефоне.
 */

export interface TrendSlot {
  index: number
  /** Левый край и ширина «ячейки» дня — зона наведения и подсветки. */
  x: number
  w: number
  /** Центр ячейки — направляющая и якорь тултипа. */
  xc: number
}

export interface TrendLayout {
  width: number
  height: number
  /** Область столбиков: `y1` — базовая линия. */
  plot: { x0: number; x1: number; y0: number; y1: number }
  slots: TrendSlot[]
  /** Ширина одного столбика и зазор между двумя рядами внутри дня. */
  barW: number
  barGap: number
  /** Верх шкалы (целое, «красивое»): столбик высотой `top` упирается в `y0`. */
  top: number
  ticks: { value: number; y: number }[]
}

/**
 * Красивый верх шкалы: чётное число не меньше 2, чтобы три деления (0, половина,
 * верх) были целыми. Пустой ряд получает 2 — сетка есть и у пустого графика.
 */
export function niceTop(max: number): number {
  if (!Number.isFinite(max) || max <= 2) return 2
  return Math.ceil(max / 2) * 2
}

export interface TrendLayoutOptions {
  /** Место под подписи оси Y слева. */
  axisWidth?: number
  /** Зазор между ячейками дней. */
  slotGap?: number
  /** Потолок ширины столбика: семи дням на десктопе нужен, иначе плашки. */
  maxBarW?: number
  /** Запас сверху под верхнее деление. */
  padTop?: number
}

export function trendLayout(
  n: number,
  width: number,
  height: number,
  max: number,
  opts: TrendLayoutOptions = {},
): TrendLayout {
  const axisWidth = opts.axisWidth ?? 28
  const slotGap = opts.slotGap ?? (n > 10 ? 4 : 10)
  const maxBarW = opts.maxBarW ?? 14
  const padTop = opts.padTop ?? 6
  const barGap = 2
  const x0 = axisWidth
  const x1 = Math.max(x0, width)
  const y0 = padTop
  const y1 = Math.max(y0, height)
  const count = Math.max(1, n)
  const slotW = Math.max(0, (x1 - x0 - slotGap * (count - 1)) / count)
  const barW = Math.max(2, Math.min(maxBarW, (slotW - barGap) / 2))
  const slots: TrendSlot[] = []
  for (let i = 0; i < n; i += 1) {
    const x = x0 + i * (slotW + slotGap)
    slots.push({ index: i, x, w: slotW, xc: x + slotW / 2 })
  }
  const top = niceTop(max)
  const yOf = (v: number) => y1 - (v / top) * (y1 - y0)
  const ticks = [0, top / 2, top].map((value) => ({ value, y: yOf(value) }))
  return { width, height, plot: { x0, x1, y0, y1 }, slots, barW, barGap, top, ticks }
}

/**
 * Верх столбика. Ноль — не «нет столбика», а полоска 2px над базовой линией:
 * пустое место читалось бы как пропуск данных, а не как «ноль» (правило
 * `MiniBarChart`). Ненулевое — не ниже 4px, иначе единица теряется.
 */
export function barTop(value: number, layout: TrendLayout): number {
  const { y0, y1 } = layout.plot
  if (value <= 0) return y1 - 2
  const h = Math.max(4, Math.round((value / layout.top) * (y1 - y0)))
  return y1 - h
}

/** Ближайшая по X ячейка дня; при равенстве — более ранняя. `null` — ячеек нет. */
export function nearestSlot(slots: TrendSlot[], xPx: number): number | null {
  let best: number | null = null
  let bestDist = Number.POSITIVE_INFINITY
  for (const s of slots) {
    const dist = Math.abs(s.xc - xPx)
    if (dist < bestDist) {
      best = s.index
      bestDist = dist
    }
  }
  return best
}

/**
 * С какой стороны от направляющей ставить тултип: справа, а после 60 % ширины
 * — слева, чтобы не вылезать за карточку (правило `RaceLane`).
 */
export function readoutSide(xc: number, width: number): 'right' | 'left' {
  return width > 0 && xc / width > 0.6 ? 'left' : 'right'
}

/** Клавиатура: ←/→ двигают выбранный день в пределах ряда, Home/End — к краям. */
export function stepSelection(
  current: number | null,
  key: string,
  n: number,
): number | null | undefined {
  if (n === 0) return undefined
  if (key === 'Escape') return null
  if (key === 'Home') return 0
  if (key === 'End') return n - 1
  if (key === 'ArrowLeft') return Math.max(0, (current ?? n) - 1)
  if (key === 'ArrowRight') return current === null ? n - 1 : Math.min(n - 1, current + 1)
  return undefined
}
