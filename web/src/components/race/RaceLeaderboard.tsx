import { useState } from 'react'

import { Chip } from '@/components/ui/Chip'
import { cn } from '@/lib/cn'
import type { RaceParticipant } from '@/lib/race'
import { formatCells, formatPct, leaderboardRows, type RaceView } from '@/lib/raceBoard'
import { nbsp, plural } from '@/lib/typography'

import { DynamicsMark } from './DynamicsMark'

function Row({ p, place, me, tv }: { p: RaceParticipant; place: number | null; me: boolean; tv: boolean }) {
  const top = place !== null && place <= 3 && !me
  return (
    <div
      className={cn(
        'flex items-center gap-3 rounded-xl border px-3 py-2.5',
        me ? 'border-amber/55 bg-amber/[0.08]' : 'border-hair bg-tint',
        tv && 'py-3',
      )}
    >
      <span
        className={cn(
          'flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-[13px] font-bold tabular-nums',
          top ? 'bg-amber text-on-amber' : 'bg-surface text-text2',
          me && 'text-text',
          tv && 'h-9 w-9 text-[16px]',
        )}
      >
        {place ?? '—'}
      </span>
      <span className="flex min-w-0 flex-1 items-center gap-2">
        {p.code && (
          <Chip variant="outline" size="sm" className="shrink-0">
            {p.code}
          </Chip>
        )}
        <span className={cn('truncate font-semibold leading-[1.3] text-text', tv ? 'text-[20px]' : 'text-[15px] lg:text-[16px]')}>
          {p.name}
          {me && <span className="ml-1.5 text-[13px] font-normal text-text2">— это вы</span>}
        </span>
      </span>
      <DynamicsMark value={p.dynamics} compact className="shrink-0 lg:hidden" />
      <DynamicsMark value={p.dynamics} className="hidden shrink-0 lg:inline-flex" />
      <span className={cn('hidden shrink-0 tabular-nums text-text2 lg:inline', tv ? 'text-[16px]' : 'text-[13px]')}>
        {formatCells(p.cells)} кл.
      </span>
      <span className={cn('shrink-0 font-display font-bold tabular-nums text-text', tv ? 'text-[26px]' : 'text-[16px] lg:text-[18px]')}>
        {p.needs_baseline ? '—' : formatPct(p.pct)}
      </span>
    </div>
  )
}

/**
 * Таблица лидеров: место, точка, динамика, клетки (десктоп), % — главным
 * числом. Топ-3 — амбер-пилюля, «— это вы» с амбер-рамкой и дублем под
 * «···», если вне показанного топа; без базы — свёрнутый хвост.
 */
export function RaceLeaderboard({ participants, view, myStoreId, limit = 10, tv = false, className }: { participants: RaceParticipant[]; view: RaceView; myStoreId: string | null | undefined; limit?: number; tv?: boolean; className?: string }) {
  const [showAll, setShowAll] = useState(false)
  const [showUnranked, setShowUnranked] = useState(false)
  const { ranked, unranked } = leaderboardRows(participants, view)
  const visible = showAll || tv ? ranked.slice(0, tv ? limit : ranked.length) : ranked.slice(0, limit)
  const mine = myStoreId ? ranked.find((r) => r.p.store_id === myStoreId) ?? null : null
  const meOutside = mine !== null && !visible.some((r) => r.p.store_id === myStoreId)
  const rest = ranked.length - visible.length

  return (
    <section className={cn('flex flex-col gap-[7px] lg:gap-2', className)}>
      {ranked.length === 0 && unranked.length === 0 && (
        <p className="rounded-xl border border-hair bg-tint p-4 text-[14px] text-text2">Участников в этом виде нет.</p>
      )}
      {visible.map((r) => (
        <Row key={r.p.store_id} p={r.p} place={r.place} me={r.p.store_id === myStoreId} tv={tv} />
      ))}
      {meOutside && mine && (
        <>
          <p className="my-0.5 text-center text-[14px] text-text2">···</p>
          <Row p={mine.p} place={mine.place} me tv={tv} />
        </>
      )}
      {!tv && ranked.length > limit && (
        <button type="button" className="mt-1 self-start text-[14px] font-semibold text-amber hover:underline" onClick={() => setShowAll((v) => !v)}>
          {showAll ? 'Свернуть' : `Показать все (${ranked.length})`}
        </button>
      )}
      {tv && rest > 0 && (
        <p className="text-[14px] text-text2" style={{ fontSize: 'var(--race-fs)' }}>
          {nbsp(`…и ещё ${plural(rest, 'точка', 'точки', 'точек')} — на дорожке`)}
        </p>
      )}
      {!tv && unranked.length > 0 && (
        <div className="mt-1">
          <button
            type="button"
            className="text-[13px] font-semibold uppercase tracking-[0.06em] text-text2 hover:text-text"
            onClick={() => setShowUnranked((v) => !v)}
            aria-expanded={showUnranked}
          >
            Без базы · {unranked.length}
          </button>
          {showUnranked && (
            <div className="mt-2 flex flex-col gap-[7px]">
              {unranked.map((p) => (
                <Row key={p.store_id} p={p} place={null} me={p.store_id === myStoreId} tv={false} />
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  )
}
