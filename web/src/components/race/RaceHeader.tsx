import type { CSSProperties } from 'react'

import { Badge } from '@/components/ui/Badge'
import { useCountdown } from '@/hooks/useCountdown'
import { cn } from '@/lib/cn'
import type { DisplayRace, RaceContest } from '@/lib/race'
import { freshnessLine, type BoardState } from '@/lib/raceBoard'
import { formatCountdown } from '@/lib/raceCountdown'
import { humanDate } from '@/lib/taskDates'
import { nbsp } from '@/lib/typography'

const STATUS_BADGE: Record<string, { label: string; variant: 'default' | 'secondary' | 'success' | 'outline' }> = {
  scheduled: { label: 'скоро', variant: 'secondary' },
  active: { label: 'идёт', variant: 'default' },
  finished: { label: 'завершён', variant: 'outline' },
}

export function RaceCountdown({ targetIso, mode, compact = false, className, style }: { targetIso: string | null; mode: 'to-end' | 'to-start'; compact?: boolean; className?: string; style?: CSSProperties }) {
  const parts = useCountdown(targetIso)
  if (!parts) return null
  return (
    <span role="timer" className={cn('font-display font-bold tabular-nums text-text', className)} style={style}>
      {formatCountdown(parts, mode, compact)}
    </span>
  )
}

export function RaceFreshness({ asOf, nextAt, className }: { asOf: string | null; nextAt: string | null; className?: string }) {
  const line = freshnessLine(asOf, nextAt, Date.now())
  if (!line) return null
  return <p className={cn('text-[12px] text-text2', className)}>{nbsp(line)}</p>
}

export function raceEyebrow(race: DisplayRace | null, contest: RaceContest | null): string {
  if (!race) return contest ? contest.title : 'Гусиная гонка'
  return nbsp(`Заезд № ${race.seq} · ${humanDate(race.starts_on)} — ${humanDate(race.ends_on)}`)
}

/** Шапка экрана: eyebrow с номером заезда и датами, бейдж статуса, отсчёт. */
export function RaceHeader({ contest, race, state, asOf, nextAt, isDesktop }: { contest: RaceContest | null; race: DisplayRace | null; state: BoardState; asOf: string | null; nextAt: string | null; isDesktop: boolean }) {
  const badge = race ? STATUS_BADGE[race.status] : null
  const countdownMode = state.kind === 'active' ? 'to-end' : 'to-start'
  const target = race ? (state.kind === 'active' ? race.ends_at : state.kind === 'scheduled' || state.kind === 'between' ? race.starts_at : null) : null
  return (
    <header className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between lg:gap-4">
      <div className="min-w-0">
        <p className="mb-1 flex items-center gap-2 text-[12px] leading-[1.35] text-text2">
          <span>{raceEyebrow(race, contest)}</span>
          {badge && <Badge variant={badge.variant}>{badge.label}</Badge>}
        </p>
        <h1 className="font-display text-[28px] font-bold leading-[1.18] tracking-[0.01em] text-text lg:text-[34px] lg:leading-[1.15]">
          Гусиная гонка
        </h1>
        {contest && race && <p className="mt-1.5 hidden text-[15px] text-text2 lg:block">{contest.title}</p>}
      </div>
      <div className={cn('flex flex-col gap-1', isDesktop ? 'items-end text-right' : 'items-start')}>
        {target && (
          <RaceCountdown targetIso={target} mode={countdownMode} className="text-[20px] leading-none lg:text-[32px]" />
        )}
        {state.kind === 'finished' && <span className="font-display text-[18px] font-bold text-text">Соревнование завершено</span>}
        <RaceFreshness asOf={asOf} nextAt={nextAt} />
      </div>
    </header>
  )
}
