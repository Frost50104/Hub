import { type CSSProperties } from 'react'

import { cn } from '@/lib/cn'

export interface DonutSegment {
  key: string
  label: string
  value: number
  /** CSS-цвет — из `lib/tone.ts`, свой цвет не изобретать. */
  color: string
}

interface DonutProps {
  segments: DonutSegment[]
  /** Внешний диаметр, px. Спека: 132. */
  size?: number
  /** Толщина кольца, px. Спека: 132 → внутренний радиус 42. */
  thickness?: number
  /** Легенда справа: точка 10×10 r3 · подпись 14 · «N · %» tabular. */
  legend?: boolean
  className?: string
}

/**
 * Кольцевая диаграмма на `conic-gradient` + `mask` — без библиотеки.
 * Секторы разделены зазором 1%: соседние этапы одного системного статуса
 * получают один тон, и без зазора сливаются в один сектор. Нулевая сумма —
 * пустое кольцо на `--surface`. Значения всегда продублированы легендой:
 * на телефоне нет hover, а тап по сектору невозможен.
 *
 * `-webkit-mask` обязателен: Safari (iOS) не понимает `mask` без префикса.
 */
export function Donut({
  segments,
  size = 132,
  thickness = 24,
  legend = true,
  className,
}: DonutProps) {
  const total = segments.reduce((s, x) => s + Math.max(0, x.value), 0)
  const GAP = total > 0 && segments.filter((s) => s.value > 0).length > 1 ? 1 : 0
  const live = segments.filter((s) => s.value > 0)
  const stops: string[] = []
  let acc = 0
  for (const s of live) {
    const share = (s.value / total) * 100
    const from = acc
    const to = acc + share
    // зазор отрезается от конца сектора, сектор не короче 1%
    const toWithGap = Math.max(from + 0.5, to - GAP)
    stops.push(`${s.color} ${from.toFixed(2)}% ${toWithGap.toFixed(2)}%`)
    if (GAP) stops.push(`transparent ${toWithGap.toFixed(2)}% ${to.toFixed(2)}%`)
    acc = to
  }
  const inner = size / 2 - thickness
  const mask = `radial-gradient(circle, transparent ${inner}px, #000 ${inner + 1}px)`
  const ring: CSSProperties = {
    width: size,
    height: size,
    background:
      total > 0 ? `conic-gradient(${stops.join(', ')})` : 'var(--surface)',
    WebkitMaskImage: mask,
    maskImage: mask,
  }

  return (
    <div className={cn('flex items-center gap-4', className)}>
      <div
        role="img"
        aria-label={
          total > 0
            ? segments.map((s) => `${s.label}: ${s.value}`).join(', ')
            : 'нет данных'
        }
        className="shrink-0 rounded-full"
        style={ring}
      />
      {legend && (
        <ul className="flex min-w-0 flex-1 flex-col gap-[7px]">
          {segments.map((s) => {
            const pct = total > 0 ? Math.round((s.value / total) * 100) : 0
            return (
              <li key={s.key} className="flex min-w-0 items-center gap-2.5 text-[14px]">
                <span
                  aria-hidden
                  className="h-2.5 w-2.5 shrink-0 rounded-[3px]"
                  style={{ background: s.color }}
                />
                <span className="min-w-0 flex-1 truncate text-text">{s.label}</span>
                <span className="shrink-0 tabular-nums text-text2">
                  {s.value} · {pct}%
                </span>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
