import { useState } from 'react'

import { cn } from '@/lib/cn'
import type { RaceStanding } from '@/lib/race'
import { formatPct } from '@/lib/raceBoard'
import { plural } from '@/lib/typography'

/** Общий зачёт: сумма мест по завершённым заездам — меньше лучше. */
const LIMIT = 10

export function RaceStandings({ standings, myStoreId, className }: { standings: RaceStanding[]; myStoreId: string | null | undefined; className?: string }) {
  const [showAll, setShowAll] = useState(false)
  const visible = showAll ? standings : standings.slice(0, LIMIT)
  const mine = myStoreId ? standings.find((s) => s.store_id === myStoreId) : undefined
  const meOutside = mine !== undefined && !visible.some((s) => s.store_id === myStoreId)
  return (
    <section className={cn('flex flex-col gap-2', className)}>
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="font-display text-[18px] font-bold text-text">Общий зачёт</h2>
        <span className="text-[12px] text-text2">чем меньше сумма мест, тем выше</span>
      </div>
      {standings.length === 0 ? (
        <p className="rounded-xl border border-hair bg-tint p-4 text-[14px] text-text2">Зачёт появится после первого завершённого заезда.</p>
      ) : (
        <div className="overflow-hidden rounded-xl border border-hair bg-tint">
          <div className="hidden grid-cols-[44px_minmax(0,1fr)_110px_90px] items-center gap-2 border-b border-hair px-3 py-2 text-[12px] font-semibold uppercase tracking-[0.06em] text-text2 lg:grid">
            <span>#</span>
            <span>Точка</span>
            <span className="text-right">Сумма мест</span>
            <span className="text-right">Заездов</span>
          </div>
          {[...visible, ...(meOutside && mine ? [mine] : [])].map((s) => {
            const me = s.store_id === myStoreId
            return (
              <div
                key={s.store_id}
                className={cn('grid grid-cols-[36px_minmax(0,1fr)_auto] items-center gap-2 border-b border-hair px-3 py-2 last:border-b-0 lg:grid-cols-[44px_minmax(0,1fr)_110px_90px]', me && 'bg-amber/[0.08]')}
              >
                <span className={cn('flex h-7 w-7 items-center justify-center rounded-lg text-[13px] font-bold tabular-nums', s.place <= 3 && !me ? 'bg-amber text-on-amber' : 'bg-surface text-text2')}>
                  {s.place}
                </span>
                <span className="min-w-0">
                  <span className="block truncate text-[15px] font-semibold text-text">
                    {s.name}
                    {me && <span className="ml-1.5 text-[13px] font-normal text-text2">— это вы</span>}
                  </span>
                  <span className="block text-[12px] text-text2 lg:hidden">
                    {plural(s.races_counted, 'заезд', 'заезда', 'заездов')}
                    {s.missed_races > 0 && ` · пропущено ${s.missed_races}`} · {formatPct(s.pct_sum)}
                  </span>
                </span>
                <span className="text-right font-display text-[16px] font-bold tabular-nums text-text">{s.points}</span>
                <span className="hidden text-right text-[13px] tabular-nums text-text2 lg:block">
                  {s.races_counted}
                  {s.missed_races > 0 && <span className="text-text3"> (−{s.missed_races})</span>}
                </span>
              </div>
            )
          })}
        </div>
      )}
      {standings.length > LIMIT && (
        <button type="button" className="self-start text-[14px] font-semibold text-amber hover:underline" onClick={() => setShowAll((v) => !v)}>
          {showAll ? 'Свернуть' : `Показать все (${standings.length})`}
        </button>
      )}
    </section>
  )
}
