import { useEffect, useMemo, useState } from 'react'

import { useIsDesktop, useMediaQuery } from '@/hooks/useMediaQuery'
import { cn } from '@/lib/cn'
import type { RaceParticipant } from '@/lib/race'
import { pinMyLane, type RaceView } from '@/lib/raceBoard'
import { laneOrder, lanePositions } from '@/lib/raceTrack'

import { GooseTooltip } from './GooseTooltip'
import { RaceLane } from './RaceLane'
import { RaceTrackTicks } from './RaceTrackTicks'

interface RaceTrackProps {
  rows: RaceParticipant[]
  view: RaceView
  myStoreId: string | null | undefined
  selectedId: string | null
  onSelect: (id: string | null) => void
  tv?: boolean
  /** Свой скролл внутри карточки при большом числе дорожек (десктоп). */
  scrollInside?: boolean
  /** Подписи тиков только у старта и максимума (узкий трек, узкий ТВ). */
  compactTicks?: boolean
  className?: string
}

/**
 * Трек: дорожки `position:absolute` с `translateY` (перестановка мест
 * анимируется той же транзицией, что и переезд гуся), тики поверх,
 * стартовый выезд через `mounted` — только на первом кадре, рефетч и смена
 * лиги его не повторяют.
 */
export function RaceTrack({ rows, view, myStoreId, selectedId, onSelect, tv = false, scrollInside = false, compactTicks = false, className }: RaceTrackProps) {
  const isDesktop = useIsDesktop()
  const reduceMotion = useMediaQuery('(prefers-reduced-motion: reduce)')
  const stacked = !isDesktop && !tv
  const [mounted, setMounted] = useState(reduceMotion)
  // Таймер, а не requestAnimationFrame: в неактивной вкладке rAF не бежит
  // вовсе, и гуси стояли бы на нуле до первого показа. Первый кадр всё равно
  // рисуется с x=0 — транзиция стартует от него.
  useEffect(() => {
    if (mounted) return
    const t = window.setTimeout(() => setMounted(true), 80)
    return () => window.clearTimeout(t)
  }, [mounted])

  const ordered = useMemo(() => {
    const sorted = laneOrder(rows)
    return stacked ? pinMyLane(sorted, myStoreId) : sorted
  }, [rows, stacked, myStoreId])
  const laneH = tv ? 48 : stacked ? 56 : 36
  const positions = useMemo(() => lanePositions(ordered, laneH), [ordered, laneH])
  const selected = selectedId ? rows.find((r) => r.store_id === selectedId) ?? null : null
  const ticksLeft = stacked ? '0px' : 'var(--race-label-w)'

  return (
    <div className={cn('flex flex-col gap-3', className)}>
      <div
        // `overflow-x: clip`, а не hidden: фокус на гусе иначе прокручивает карточку
        // по горизонтали (scrollIntoView), и трек уезжал за левый край.
        className={cn('race-track relative overflow-hidden [overflow-x:clip] rounded-xl border border-hair', scrollInside && 'max-h-[min(70vh,1400px)] overflow-y-auto')}
        style={{ ['--race-lane-h' as string]: `${laneH}px` }}
        onClick={() => onSelect(null)}
      >
        <div className="sticky top-0 z-10 h-7 bg-bg-alt/85 backdrop-blur-sm" style={{ paddingLeft: ticksLeft }}>
          <div className="relative h-full">
            <RaceTrackTicks labels compact={stacked || compactTicks} />
          </div>
        </div>
        <div className="relative" style={{ height: positions.height }} role="list" aria-label="Дорожки">
          <div className="absolute inset-y-0 right-0" style={{ left: ticksLeft }}>
            <RaceTrackTicks />
          </div>
          {ordered.map((p) => (
            <RaceLane
              key={p.store_id}
              p={p}
              view={view}
              y={positions.byId[p.store_id] ?? 0}
              mounted={mounted}
              isMe={p.store_id === myStoreId}
              selected={selectedId === p.store_id}
              onToggle={onSelect}
              stacked={stacked}
              tv={tv}
            />
          ))}
        </div>
      </div>
      {stacked && selected && <GooseTooltip p={selected} variant="card" />}
    </div>
  )
}
