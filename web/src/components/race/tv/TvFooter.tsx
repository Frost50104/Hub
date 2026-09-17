import { cn } from '@/lib/cn'
import { freshnessLine } from '@/lib/raceBoard'
import { nbsp } from '@/lib/typography'

/** Футер ТВ: свежесть, индикатор страницы с полосой ротации, марка Signaris. */
export function TvFooter({ asOf, nextAt, pageIdx, pages, pageMs, offlineSince }: { asOf: string | null; nextAt: string | null; pageIdx: number; pages: number; pageMs: number; offlineSince: string | null }) {
  const line = freshnessLine(asOf, nextAt, Date.now())
  return (
    <footer className="flex items-center justify-between gap-8 text-text2" style={{ fontSize: 'var(--race-fs)' }}>
      <p className="min-w-0 truncate">
        {offlineSince ? <span className="text-text">Нет связи — {offlineSince}</span> : line ? nbsp(line) : 'Данные ещё не загружались'}
      </p>
      {pages > 1 && (
        <div className="flex shrink-0 items-center gap-4">
          <span className="flex gap-1.5">
            {Array.from({ length: pages }, (_, i) => (
              <span key={i} className={cn('h-2.5 w-2.5 rounded-full', i === pageIdx ? 'bg-amber' : 'bg-hair')} />
            ))}
          </span>
          <span>{nbsp(`Дорожка ${pageIdx + 1} из ${pages}`)}</span>
          <span className="h-1 w-[240px] overflow-hidden rounded-full bg-hair">
            <span key={pageIdx} className="race-tv-progress block h-full bg-amber" style={{ ['--race-page-ms' as string]: `${pageMs}ms` }} />
          </span>
        </div>
      )}
      <span className="flex shrink-0 items-center gap-3">
        <img src="/brand/signaris-mark-on-dark.svg" alt="" className="h-7 w-7" />
        <span className="font-display font-semibold text-text">Hub</span>
      </span>
    </footer>
  )
}
