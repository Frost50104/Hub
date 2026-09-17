import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

import { cn } from '@/lib/cn'
import type { RaceParticipant } from '@/lib/race'
import { formatPct, laneAria, type RaceView } from '@/lib/raceBoard'
import { cellsToPercent, glowLevel, moveDurationMs } from '@/lib/raceTrack'

import { GooseIcon } from './GooseIcon'
import { GooseTooltip } from './GooseTooltip'
import { RaceConfetti } from './RaceConfetti'

interface RaceLaneProps {
  p: RaceParticipant
  view: RaceView
  y: number
  /** false на первом кадре — гуси выезжают со старта. */
  mounted: boolean
  isMe: boolean
  selected: boolean
  onToggle: (id: string | null) => void
  /** Ниже lg подпись идёт над полосой, тултип — карточкой под треком. */
  stacked: boolean
  tv?: boolean
}

export function RaceLane({ p, view, y, mounted, isMe, selected, onToggle, stacked, tv = false }: RaceLaneProps) {
  const targetX = mounted ? cellsToPercent(p.cells) : 0
  const prevX = useRef<number | null>(null)
  const [moving, setMoving] = useState(false)
  const [moveMs, setMoveMs] = useState(800)
  const [hover, setHover] = useState(false)
  // Плавающий тултип — порталом с `position: fixed`: карточка трека несёт
  // `overflow-hidden` (скругления и внутренний скролл), и на крайних дорожках
  // абсолютный тултип уходил бы под край.
  const [anchor, setAnchor] = useState<{ x: number; y: number } | null>(null)

  useEffect(() => {
    const prev = prevX.current
    if (prev !== null && prev !== targetX) {
      const ms = moveDurationMs(prev * 4, targetX * 4)
      setMoveMs(ms)
      setMoving(true)
      const t = window.setTimeout(() => setMoving(false), ms + 100)
      prevX.current = targetX
      return () => window.clearTimeout(t)
    }
    if (prev === null && mounted) {
      setMoveMs(moveDurationMs(null, targetX * 4))
      setMoving(true)
      const t = window.setTimeout(() => setMoving(false), 2500)
      prevX.current = targetX
      return () => window.clearTimeout(t)
    }
    return undefined
  }, [targetX, mounted])

  const glow = glowLevel(p.cells)
  const showFloating = !stacked && (selected || hover)
  const flipLeft = targetX > 60

  return (
    <div
      className="race-lane"
      style={{ ['--race-y' as string]: `${y}px`, ['--race-move-ms' as string]: `${moveMs}ms`, height: 'var(--race-lane-h)' }}
      role="listitem"
    >
      <div className={cn('grid h-full', stacked ? 'grid-rows-[18px_1fr]' : 'grid-cols-[var(--race-label-w)_minmax(0,1fr)]')}>
        <div
          className={cn(
            'flex min-w-0 items-center gap-2 px-2',
            stacked ? 'justify-between text-[12px]' : 'text-[14px]',
            isMe && 'text-text',
          )}
          style={{ fontSize: stacked ? undefined : 'var(--race-fs)' }}
        >
          <span className={cn('flex min-w-0 items-center gap-1.5', stacked && 'rounded-md bg-bg/60 px-1 backdrop-blur-[2px]')}>
            {p.code && (
              <span
                className={cn(
                  'inline-flex h-[20px] shrink-0 items-center rounded-md px-1.5 text-[11px] font-bold uppercase tracking-[0.06em]',
                  isMe ? 'bg-amber text-on-amber' : 'bg-surface text-text2',
                )}
              >
                {p.code}
              </span>
            )}
            <span className={cn('truncate', isMe ? 'font-semibold' : 'text-text2')}>{p.name}</span>
            {isMe && !tv && <span className="shrink-0 text-[11px] text-text2">— вы</span>}
          </span>
          {stacked && (
            <span className="shrink-0 rounded-md bg-bg/60 px-1 tabular-nums text-text2 backdrop-blur-[2px]">
              {p.needs_baseline ? 'нет базы' : formatPct(p.pct)}
            </span>
          )}
        </div>
        <div className="relative" style={{ paddingInline: 'calc(var(--race-goose-w) / 2)' }}>
          <div className="absolute inset-x-[calc(var(--race-goose-w)/2)] top-1/2 h-px -translate-y-1/2 bg-text/10" />
          <div className="relative h-full">
            <div className="race-lane__mover" style={{ ['--race-x' as string]: `${targetX}%` }}>
              <button
                type="button"
                className={cn('race-goose rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/70', p.needs_baseline && 'opacity-50')}
                data-me={isMe}
                data-moving={moving}
                data-glow={glow}
                aria-label={laneAria(p, view)}
                aria-expanded={selected}
                onClick={(e) => {
                  e.stopPropagation()
                  const r = e.currentTarget.getBoundingClientRect()
                  setAnchor({ x: r.left + r.width / 2, y: r.top + r.height / 2 })
                  onToggle(selected ? null : p.store_id)
                }}
                onPointerEnter={(e) => {
                  if (e.pointerType === 'touch') return
                  const r = e.currentTarget.getBoundingClientRect()
                  setAnchor({ x: r.left + r.width / 2, y: r.top + r.height / 2 })
                  setHover(true)
                }}
                onPointerLeave={() => setHover(false)}
              >
                <span className="relative block">
                  <GooseIcon size={tv ? 40 : 32} pose={moving ? 'run' : 'idle'} />
                  {glow === 'max' && <RaceConfetti />}
                </span>
              </button>
              {showFloating &&
                anchor &&
                createPortal(
                  <div
                    className="pointer-events-none fixed z-50"
                    style={{
                      left: flipLeft ? anchor.x - 28 : anchor.x + 28,
                      top: anchor.y,
                      transform: flipLeft ? 'translate(-100%, -50%)' : 'translateY(-50%)',
                    }}
                  >
                    <GooseTooltip p={p} />
                  </div>,
                  document.body,
                )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
