import { useRef, useState } from 'react'

import { SegmentGroup } from '@/components/ui/SegmentGroup'
import { useElementWidth } from '@/hooks/useElementWidth'
import { cn } from '@/lib/cn'
import type { RaceChart as RaceChartData, RaceRef } from '@/lib/race'
import { formatAvg, formatPct } from '@/lib/raceBoard'
import { chartGeometry, nearestPoint, raceDayLabel, type ChartDot } from '@/lib/raceChart'

/**
 * SVG-график «клетки по дням заезда» — рукописный, в пикселях (масштабированный
 * `viewBox` уводил бы подписи ниже 12px на телефоне). Одна серия — амбер.
 */
export function RaceChart({ races, raceId, onRaceChange, chart, loading, height = 220, className }: { races: RaceRef[]; raceId: string | null; onRaceChange: (id: string) => void; chart: RaceChartData | undefined; loading: boolean; height?: number; className?: string }) {
  const ref = useRef<HTMLDivElement>(null)
  const width = useElementWidth(ref)
  const [hover, setHover] = useState<ChartDot | null>(null)
  const selectable = races.filter((r) => r.status !== 'scheduled')
  const geo = chart && width > 0 ? chartGeometry(chart, { width, height }) : null

  return (
    <section className={cn('flex flex-col gap-2', className)}>
      <div className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
        <h2 className="font-display text-[18px] font-bold text-text">Динамика по дням</h2>
        {selectable.length > 1 && raceId && (
          <SegmentGroup
            ariaLabel="Заезд"
            options={selectable.map((r) => ({ value: r.id, label: `№ ${r.seq}` }))}
            value={raceId}
            onChange={onRaceChange}
            size="sm"
          />
        )}
      </div>
      <div ref={ref} className="relative rounded-xl border border-hair bg-tint p-2">
        {!chart && loading && <p className="p-2 text-[14px] text-text2">Загружаем…</p>}
        {!chart && !loading && <p className="p-2 text-[14px] text-text2">Выберите точку и заезд.</p>}
        {geo && (
          <svg
            width={geo.width - 16}
            height={height}
            role="img"
            aria-label="Позиция гуся по дням заезда"
            onPointerMove={(e) => {
              const rect = e.currentTarget.getBoundingClientRect()
              setHover(nearestPoint(geo.dots, e.clientX - rect.left))
            }}
            onPointerLeave={() => setHover(null)}
          >
            {geo.yTicks.map((t) => (
              <g key={t.label}>
                <line x1={geo.plot.x0} x2={geo.plot.x1} y1={t.y} y2={t.y} stroke="rgb(var(--text) / 0.08)" />
                <text x={geo.plot.x0 - 6} y={t.y + 4} fontSize={12} textAnchor="end" fill="rgb(var(--text2))">
                  {t.label}
                </text>
              </g>
            ))}
            <line x1={geo.plot.x0} x2={geo.plot.x1} y1={geo.baselineY} y2={geo.baselineY} stroke="rgb(var(--text2))" strokeDasharray="4 3" />
            <text x={geo.plot.x1} y={geo.baselineY - 4} fontSize={12} textAnchor="end" fill="rgb(var(--text2))">
              база
            </text>
            {geo.xTicks.map((t) => (
              <text key={t.day} x={t.x} y={height - 6} fontSize={12} textAnchor="middle" fill="rgb(var(--text2))">
                {t.label}
              </text>
            ))}
            {geo.area && <path d={geo.area} fill="rgb(var(--amber) / 0.08)" />}
            {geo.path && <path d={geo.path} fill="none" stroke="rgb(var(--amber))" strokeWidth={2} strokeLinejoin="round" />}
            {geo.dots.map((d) => (
              <circle
                key={d.point.day}
                cx={d.x}
                cy={d.y}
                r={d.point.live ? 4 : 3}
                fill={d.point.live ? 'rgb(var(--bg))' : 'rgb(var(--amber))'}
                stroke="rgb(var(--amber))"
                strokeWidth={d.point.live ? 2 : 0}
              />
            ))}
            {hover && (
              <line x1={hover.x} x2={hover.x} y1={geo.plot.y0} y2={geo.plot.y1} stroke="rgb(var(--text) / 0.25)" />
            )}
          </svg>
        )}
        {hover && (
          <div className="glass-solid pointer-events-none absolute left-2 top-2 rounded-lg border border-hair px-2.5 py-1.5 text-[12px] text-text">
            {raceDayLabel(hover.point.day)} · {hover.point.cells} клеток · {formatPct(hover.point.pct)} · {formatAvg(hover.point.avg)} в чеке
            {hover.point.live && ' · сейчас'}
            {hover.point.is_record && ' · рекорд'}
          </div>
        )}
      </div>
    </section>
  )
}
