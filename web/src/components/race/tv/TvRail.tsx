import { useRef } from 'react'

import { DynamicsMark } from '@/components/race/DynamicsMark'
import { useElementSize } from '@/hooks/useElementSize'
import { cn } from '@/lib/cn'
import type { RaceParticipant } from '@/lib/race'
import { formatAvg, formatCells, formatPct, leaderboardRows, type LeaderRow, type RaceView } from '@/lib/raceBoard'
import { nbsp, plural } from '@/lib/typography'

const ROW_H = 52
const ROW_GAP = 8

const MEDAL: Record<number, string> = {
  1: 'bg-amber text-on-amber',
  2: 'bg-text/80 text-bg',
  3: 'bg-[rgb(var(--race-primary)/0.75)] text-bg',
}

function Podium({ row, first }: { row: LeaderRow; first: boolean }) {
  const place = row.place ?? 0
  return (
    <div className={cn('flex flex-col gap-1 rounded-2xl border border-hair bg-tint px-5', first ? 'race-tv-gold py-3' : 'py-2.5', first && 'race-tv-gold')}>
      <div className="flex min-w-0 items-center gap-3">
        <span className={cn('flex shrink-0 items-center justify-center rounded-full font-display font-bold tabular-nums', MEDAL[place] ?? 'bg-surface text-text2', first ? 'h-11 w-11 text-[22px]' : 'h-9 w-9 text-[18px]')}>
          {place}
        </span>
        {row.p.code && <span className="shrink-0 rounded-md bg-surface px-1.5 text-[13px] font-bold uppercase tracking-[0.06em] text-text2">{row.p.code}</span>}
        <span className={cn('min-w-0 flex-1 truncate font-semibold text-text', first ? 'text-[26px]' : 'text-[22px]')}>{row.p.name}</span>
      </div>
      <div className="flex items-end justify-between gap-4">
        <span className="flex items-center gap-3 text-[20px] text-text2">
          <span className="whitespace-nowrap tabular-nums">{formatCells(row.p.cells)} кл.</span>
          <DynamicsMark value={row.p.dynamics} className="text-[20px]" />
        </span>
        <span className={cn('shrink-0 font-display font-bold leading-none tabular-nums text-text', first ? 'text-[40px]' : 'text-[30px]')}>
          {formatPct(row.p.pct)}
        </span>
      </div>
    </div>
  )
}

/** Правая колонка ТВ: подиум топ-3, дальше столько строк, сколько влезает по
 *  ИЗМЕРЕННОЙ высоте (ничего не режется), и «…и ещё N». */
export function TvRail({ participants, view }: { participants: RaceParticipant[]; view: RaceView }) {
  const rowsRef = useRef<HTMLDivElement>(null)
  const { height: rowsH } = useElementSize(rowsRef)
  const fit = Math.max(0, Math.floor((rowsH + ROW_GAP) / (ROW_H + ROW_GAP)))
  const { ranked, unranked } = leaderboardRows(participants, view)
  if (ranked.length === 0) {
    // До старта заезда мест нет — показываем состав и базу.
    return (
      <aside className="flex h-full min-h-0 flex-col gap-3">
        <p className="shrink-0 uppercase tracking-[0.12em] text-text2" style={{ fontSize: 'var(--race-fs)' }}>
          Участники · {unranked.length}
        </p>
        <div ref={rowsRef} className="flex min-h-0 flex-1 flex-col gap-2 overflow-hidden">
          {unranked.slice(0, fit).map((p) => (
            <div key={p.store_id} className="flex h-[52px] shrink-0 items-center gap-3 rounded-xl border border-hair bg-tint px-4">
              {p.code && <span className="shrink-0 rounded-md bg-surface px-1.5 text-[12px] font-bold uppercase tracking-[0.06em] text-text2">{p.code}</span>}
              <span className="min-w-0 flex-1 truncate text-[22px] font-semibold text-text">{p.name}</span>
              <span className="shrink-0 text-[20px] tabular-nums text-text2">{p.needs_baseline ? 'нет базы' : `база ${formatAvg(p.base)}`}</span>
            </div>
          ))}
        </div>
        {unranked.length > fit && (
          <p className="shrink-0 text-text2" style={{ fontSize: 'var(--race-fs)' }}>
            {nbsp(`…и ещё ${plural(unranked.length - fit, 'точка', 'точки', 'точек')}`)}
          </p>
        )}
      </aside>
    )
  }
  const podium = ranked.slice(0, 3)
  const rest = ranked.slice(3, 3 + fit)
  const more = ranked.length - podium.length - rest.length
  return (
    <aside className="flex h-full min-h-0 flex-col gap-3">
      <p className="shrink-0 uppercase tracking-[0.12em] text-text2" style={{ fontSize: 'var(--race-fs)' }}>
        Лидеры заезда
      </p>
      {podium.map((r, i) => (
        <Podium key={r.p.store_id} row={r} first={i === 0} />
      ))}
      <div ref={rowsRef} className="flex min-h-0 flex-1 flex-col gap-2 overflow-hidden">
        {rest.map((r) => (
          <div key={r.p.store_id} className="flex h-[52px] shrink-0 items-center gap-3 rounded-xl border border-hair bg-tint px-4">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-surface text-[16px] font-bold tabular-nums text-text2">{r.place}</span>
            {r.p.code && <span className="shrink-0 rounded-md bg-surface px-1.5 text-[12px] font-bold uppercase tracking-[0.06em] text-text2">{r.p.code}</span>}
            <span className="min-w-0 flex-1 truncate text-[22px] font-semibold text-text">{r.p.name}</span>
            <DynamicsMark value={r.p.dynamics} compact className="shrink-0" />
            <span className="shrink-0 text-[18px] tabular-nums text-text2">{formatCells(r.p.cells)} кл.</span>
            <span className="shrink-0 font-display text-[30px] font-bold tabular-nums text-text">{formatPct(r.p.pct)}</span>
          </div>
        ))}
      </div>
      <p className={cn('shrink-0 text-text2', more <= 0 && 'invisible')} style={{ fontSize: 'var(--race-fs)' }}>
        {more > 0 ? nbsp(`…и ещё ${plural(more, 'точка', 'точки', 'точек')} — на дорожке`) : ' '}
      </p>
    </aside>
  )
}
