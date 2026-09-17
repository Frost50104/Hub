import { Badge } from '@/components/ui/Badge'
import { SearchableSelect } from '@/components/ui/SearchableSelect'
import { cn } from '@/lib/cn'
import type { RaceHistoryRow, RaceParticipant } from '@/lib/race'
import { formatPct } from '@/lib/raceBoard'
import { humanDate } from '@/lib/taskDates'

const STATUS: Record<string, string> = { scheduled: 'ещё не начат', active: 'идёт', finished: 'завершён' }

/** История заездов точки: № · даты · клетки · % · место. */
export function RaceHistory({ participants, storeId, onStoreChange, rows, loading, className }: { participants: RaceParticipant[]; storeId: string | null; onStoreChange: (id: string | null) => void; rows: RaceHistoryRow[] | undefined; loading: boolean; className?: string }) {
  const options = participants.map((p) => ({ value: p.store_id, label: p.name, meta: p.code ?? undefined }))
  return (
    <section className={cn('flex flex-col gap-2', className)}>
      <div className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
        <h2 className="font-display text-[18px] font-bold text-text">История заездов</h2>
        <SearchableSelect
          value={storeId}
          onChange={onStoreChange}
          options={options}
          sheetTitle="Точка"
          placeholder="Выберите точку"
          className="lg:w-[260px]"
        />
      </div>
      {!storeId && <p className="rounded-xl border border-hair bg-tint p-4 text-[14px] text-text2">Выберите точку, чтобы увидеть её заезды.</p>}
      {storeId && loading && !rows && <p className="text-[14px] text-text2">Загружаем…</p>}
      {storeId && rows && rows.length === 0 && (
        <p className="rounded-xl border border-hair bg-tint p-4 text-[14px] text-text2">Заездов пока нет.</p>
      )}
      {storeId && rows && rows.length > 0 && (
        <div className="overflow-hidden rounded-xl border border-hair bg-tint">
          {rows.map((r) => (
            <div key={r.race_id} className="grid grid-cols-[48px_minmax(0,1fr)_auto] items-center gap-2 border-b border-hair px-3 py-2 last:border-b-0">
              <span className="font-display text-[15px] font-bold text-text">№ {r.seq}</span>
              <span className="min-w-0">
                <span className="block truncate text-[14px] text-text">
                  {humanDate(r.starts_on)} — {humanDate(r.ends_on)}
                </span>
                <span className="block text-[12px] text-text2">
                  {r.status === 'finished' ? `${r.cells ?? '—'} клеток · ${formatPct(r.pct)}` : STATUS[r.status]}
                  {r.finish_reason === 'forced' && ' · завершён досрочно'}
                </span>
              </span>
              <span className="text-right">
                {r.status === 'finished' ? (
                  r.place ? (
                    <Badge variant={r.place <= 3 ? 'default' : 'secondary'}>{r.place}-е место</Badge>
                  ) : (
                    <Badge variant="outline">без базы</Badge>
                  )
                ) : (
                  <Badge variant="outline">{STATUS[r.status]}</Badge>
                )}
              </span>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
