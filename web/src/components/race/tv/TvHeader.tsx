import { RaceCountdown } from '@/components/race/RaceHeader'
import { cn } from '@/lib/cn'
import type { DisplayRace, RaceContest } from '@/lib/race'
import type { BoardState } from '@/lib/raceBoard'
import { humanDate } from '@/lib/taskDates'
import { nbsp } from '@/lib/typography'

/** Шапка ТВ: заезд и даты слева, отсчёт и прогресс дня справа. */
export function TvHeader({ contest, race, state, pageLabel }: { contest: RaceContest | null; race: DisplayRace | null; state: BoardState; pageLabel: string | null }) {
  const eyebrow = race
    ? nbsp(`Заезд № ${race.seq} · ${humanDate(race.starts_on)} — ${humanDate(race.ends_on)}`)
    : contest?.title ?? ''
  const target = race ? (state.kind === 'active' ? race.ends_at : state.kind === 'scheduled' || state.kind === 'between' ? race.starts_at : null) : null
  const mode = state.kind === 'active' ? 'to-end' : 'to-start'
  const dayIndex = race?.day_index ?? null
  const daysTotal = race?.days_total ?? 0
  return (
    <header className="flex items-start justify-between gap-12">
      <div className="min-w-0">
        <p className="truncate text-text2" style={{ fontSize: 'var(--race-fs)' }}>
          {eyebrow}
          {pageLabel && ` · ${pageLabel}`}
        </p>
        <h1 className="font-display font-bold leading-[1.05] text-text" style={{ fontSize: 'clamp(44px, 3.3vw, 80px)' }}>
          Гусиная гонка
        </h1>
        {contest && <p className="mt-1 text-text2" style={{ fontSize: 'calc(var(--race-fs) * 1.15)' }}>{contest.title}</p>}
      </div>
      <div className="flex shrink-0 flex-col items-end gap-2 text-right">
        {target && (
          <>
            <p className="uppercase tracking-[0.12em] text-text2" style={{ fontSize: 'calc(var(--race-fs) * 0.85)' }}>
              {mode === 'to-end' ? 'до конца заезда' : 'до старта заезда'}
            </p>
            <RaceCountdown targetIso={target} mode={mode} compact className="leading-none" style={{ fontSize: 'clamp(52px, 4vw, 96px)' }} />
          </>
        )}
        {state.kind === 'finished' && (
          <p className="font-display font-bold text-text" style={{ fontSize: 'clamp(32px, 2.4vw, 56px)' }}>
            Соревнование завершено
          </p>
        )}
        {state.kind === 'active' && dayIndex !== null && daysTotal > 0 && (
          <div className="mt-2 flex items-center gap-4">
            <div className="flex gap-1.5">
              {Array.from({ length: daysTotal }, (_, i) => (
                <span key={i} className={cn('h-3 w-8 rounded-sm', i < dayIndex ? 'bg-amber' : 'bg-hair')} />
              ))}
            </div>
            <span className="text-text2" style={{ fontSize: 'var(--race-fs)' }}>{nbsp(`День ${dayIndex} из ${daysTotal}`)}</span>
          </div>
        )}
      </div>
    </header>
  )
}
