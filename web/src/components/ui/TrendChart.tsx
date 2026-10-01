import { useRef, useState, type KeyboardEvent, type PointerEvent } from 'react'

import { useElementWidth } from '@/hooks/useElementWidth'
import { useIsTouch } from '@/hooks/useMediaQuery'
import { cn } from '@/lib/cn'
import type { TrendDayPoint } from '@/lib/homeStats'
import { SERIES_COLOR } from '@/lib/tone'
import {
  barTop,
  nearestSlot,
  readoutSide,
  stepSelection,
  trendLayout,
} from '@/lib/trendChart'
import { plural } from '@/lib/typography'

type Series = 'completed' | 'created'

const SERIES: { key: Series; label: string; color: string }[] = [
  // Порядок рядов фиксирован (спека): амбер — основной, синий — сравнение.
  { key: 'completed', label: 'Выполнено', color: SERIES_COLOR[0]! },
  { key: 'created', label: 'Создано', color: SERIES_COLOR[1]! },
]

interface TrendChartProps {
  points: TrendDayPoint[]
  max: { completed: number; created: number }
  /** Высота области столбиков, px. */
  height: number
  /** Потолок ширины столбика: семи дням на десктопе нужен, иначе плашки. */
  maxBarW?: number
  startLabel: string
  endLabel: string
  className?: string
}

function readoutText(p: TrendDayPoint, visible: Record<Series, boolean>): string {
  const parts = [
    visible.completed ? plural(p.completed, 'закрыта', 'закрыто', 'закрыто') : null,
    visible.created ? plural(p.created, 'заведена', 'заведено', 'заведено') : null,
  ].filter((s): s is string => s !== null)
  return `${p.labelLong} — ${parts.join(' · ')}`
}

/**
 * График «выполнено / создано по дням» на «Главной» — SVG в пикселях
 * (образец `RaceChart`), два ряда цветами `SERIES_COLOR`, сетка на `--hair`,
 * отметка «сегодня» у последней точки.
 *
 * Интерактив: наведение мыши — ближайший день по X на всём графике (промахи по
 * узкому столбику невозможны) и плавающее считывание `.glass-solid`; на тач
 * (`hover: none`) — тап фиксирует день, цифры в карточке ПОД графиком с
 * зарезервированной высотой (без CLS); клавиатура — ←/→, Home/End, Esc;
 * считывание дублируется в `aria-live`. Легенда переключает ряды, последний
 * видимый выключить нельзя. `touch-action: pan-y` — иначе страница перестаёт
 * скроллиться пальцем по графику.
 */
export function TrendChart({
  points,
  max,
  height,
  maxBarW,
  startLabel,
  endLabel,
  className,
}: TrendChartProps) {
  const ref = useRef<HTMLDivElement>(null)
  const width = useElementWidth(ref)
  const touch = useIsTouch()
  const [visible, setVisible] = useState<Record<Series, boolean>>({ completed: true, created: true })
  const [hover, setHover] = useState<number | null>(null)
  const [selected, setSelected] = useState<number | null>(null)

  const n = points.length
  const scaleMax = Math.max(visible.completed ? max.completed : 0, visible.created ? max.created : 0)
  const layout = width > 0 ? trendLayout(n, width, height, scaleMax, { maxBarW }) : null
  const activeIndex = hover ?? selected
  const active = activeIndex !== null ? points[activeIndex] : undefined
  const activeSlot = layout && activeIndex !== null ? layout.slots[activeIndex] : undefined
  const shown = SERIES.filter((s) => visible[s.key])

  const toggle = (key: Series) => {
    setVisible((v) => {
      const next = { ...v, [key]: !v[key] }
      // Последний видимый ряд не выключаем: пустой график без объяснения.
      return next.completed || next.created ? next : v
    })
  }

  const onPointerMove = (e: PointerEvent<SVGSVGElement>) => {
    if (e.pointerType === 'touch' || !layout) return
    const rect = e.currentTarget.getBoundingClientRect()
    setHover(nearestSlot(layout.slots, e.clientX - rect.left))
  }
  const onPointerDown = (e: PointerEvent<SVGSVGElement>) => {
    if (!layout) return
    const rect = e.currentTarget.getBoundingClientRect()
    const idx = nearestSlot(layout.slots, e.clientX - rect.left)
    setSelected((cur) => (cur === idx ? null : idx))
  }
  const onKeyDown = (e: KeyboardEvent<SVGSVGElement>) => {
    const next = stepSelection(selected, e.key, n)
    if (next === undefined) return
    e.preventDefault()
    setSelected(next)
  }

  return (
    <div className={cn('flex flex-col gap-2', className)}>
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
        <div className="flex gap-2" role="group" aria-label="Ряды графика">
          {SERIES.map((s) => {
            const on = visible[s.key]
            const lastOn = on && shown.length === 1
            return (
              <button
                key={s.key}
                type="button"
                aria-pressed={on}
                aria-disabled={lastOn || undefined}
                onClick={() => !lastOn && toggle(s.key)}
                className={cn(
                  'inline-flex h-7 items-center gap-1.5 rounded-full border border-glass-border px-2.5 text-[13px] font-semibold transition-colors',
                  on ? 'bg-glass text-text' : 'text-text2 hover:text-text',
                  lastOn && 'cursor-default',
                )}
              >
                <span
                  aria-hidden
                  className={cn('h-2 w-2 rounded-full', !on && 'opacity-40')}
                  style={{ background: s.color }}
                />
                {s.label}
              </button>
            )
          })}
        </div>
        <p className="text-[13px] text-text2">
          Максимум за день — {scaleMax}
          {!touch && ' · наведите на день'}
        </p>
      </div>

      <div ref={ref} className="relative">
        {layout && (
          <svg
            width={width}
            height={height}
            role="group"
            aria-label={`${shown.map((s) => s.label.toLowerCase()).join(' и ')} по дням: ${startLabel} — ${endLabel}`}
            tabIndex={0}
            className="block select-none outline-none focus-visible:rounded-md focus-visible:ring-2 focus-visible:ring-amber/60"
            style={{ touchAction: 'pan-y' }}
            onPointerMove={onPointerMove}
            onPointerLeave={() => setHover(null)}
            onPointerDown={onPointerDown}
            onKeyDown={onKeyDown}
          >
            {layout.ticks.map((t) => (
              <g key={t.value}>
                <line
                  x1={layout.plot.x0}
                  x2={layout.plot.x1}
                  y1={t.y}
                  y2={t.y}
                  stroke={t.value === 0 ? 'rgb(var(--text) / 0.18)' : 'rgb(var(--text) / 0.08)'}
                />
                <text
                  x={layout.plot.x0 - 6}
                  y={t.y + 4}
                  fontSize={11}
                  textAnchor="end"
                  fill="rgb(var(--text3))"
                  className="tabular-nums"
                >
                  {t.value}
                </text>
              </g>
            ))}
            {activeSlot && (
              <rect
                x={activeSlot.x}
                y={layout.plot.y0}
                width={activeSlot.w}
                height={layout.plot.y1 - layout.plot.y0}
                rx={4}
                fill="rgb(var(--text) / 0.06)"
              />
            )}
            {n > 0 && (
              <line
                x1={layout.slots[n - 1]!.xc}
                x2={layout.slots[n - 1]!.xc}
                y1={layout.plot.y0}
                y2={layout.plot.y1}
                stroke="rgb(var(--amber) / 0.55)"
                strokeDasharray="3 3"
              />
            )}
            {points.map((p, i) => {
              const slot = layout.slots[i]!
              const bars = shown.map((s) => ({ s, value: p[s.key] }))
              const groupW = bars.length * layout.barW + (bars.length - 1) * layout.barGap
              const startX = slot.xc - groupW / 2
              return (
                <g key={p.key}>
                  {bars.map(({ s, value }, j) => {
                    const top = barTop(value, layout)
                    return (
                      <rect
                        key={s.key}
                        x={startX + j * (layout.barW + layout.barGap)}
                        y={top}
                        width={layout.barW}
                        height={layout.plot.y1 - top}
                        rx={value > 0 ? 3 : 0}
                        fill={value > 0 ? s.color : 'rgb(var(--text) / 0.16)'}
                        opacity={activeIndex === null || activeIndex === i ? 1 : 0.55}
                      />
                    )
                  })}
                </g>
              )
            })}
          </svg>
        )}
        {!touch && active && activeSlot && layout && (
          <div
            className="glass-solid pointer-events-none absolute top-2 flex min-w-[168px] flex-col gap-1.5 rounded-xl border border-glass-border px-3 py-2.5 text-[13px] shadow-glass"
            style={
              readoutSide(activeSlot.xc, layout.width) === 'right'
                ? { left: Math.round(activeSlot.xc) + 10 }
                : { right: Math.round(layout.width - activeSlot.xc) + 10 }
            }
          >
            <span className="font-semibold text-text">{active.labelLong}</span>
            {shown.map((s) => (
              <span key={s.key} className="flex items-center gap-2 text-text2">
                <span aria-hidden className="h-2 w-2 rounded-full" style={{ background: s.color }} />
                {s.label}
                <span className="ml-auto font-display text-[15px] font-bold tabular-nums text-text">
                  {active[s.key]}
                </span>
              </span>
            ))}
          </div>
        )}
      </div>

      <div className="flex justify-between pl-7 text-[12px] text-text2">
        <span>{startLabel}</span>
        <span className="font-semibold text-amber">сегодня, {endLabel}</span>
      </div>

      {touch && (
        // Карточка-считывание ПОД графиком: высота зарезервирована, чтобы тап
        // не сдвигал экран. Текст подсказки — пока день не выбран.
        <div className="glass-solid flex min-h-12 items-center gap-3 rounded-xl border border-glass-border px-3 text-[13px]">
          {active ? (
            <>
              <span className="font-semibold text-text">{active.labelLong}</span>
              {shown.map((s) => (
                <span key={s.key} className="ml-auto flex items-center gap-1.5 text-text2 first:ml-auto">
                  <span aria-hidden className="h-2 w-2 rounded-full" style={{ background: s.color }} />
                  <span className="font-display text-[15px] font-bold tabular-nums text-text">
                    {active[s.key]}
                  </span>
                </span>
              ))}
            </>
          ) : (
            <span className="text-text3">Нажмите на день — цифры покажутся здесь</span>
          )}
        </div>
      )}

      <span className="sr-only" aria-live="polite">
        {active ? readoutText(active, visible) : ''}
      </span>
    </div>
  )
}
