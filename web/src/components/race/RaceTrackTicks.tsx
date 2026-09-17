import { cn } from '@/lib/cn'
import { trackTicks } from '@/lib/raceTrack'

/**
 * Вертикальные отметки 0/100/200/300/400 поверх дорожек. Стартовая линия
 * (100) — лента в цветах бренда, 400 — «максимум». Геометрия та же, что у
 * гусей: контейнер с `padding-inline: goose/2`.
 */
/** `compact` — узкий трек (телефон): подписи только у старта и максимума,
 *  иначе «300» наезжает на «максимум · 400». */
export function RaceTrackTicks({ labels = false, compact = false, className }: { labels?: boolean; compact?: boolean; className?: string }) {
  return (
    <div className={cn('pointer-events-none absolute inset-0', className)} aria-hidden="true">
      <div className="relative h-full" style={{ marginInline: 'calc(var(--race-goose-w) / 2)' }}>
        {trackTicks().map((t) => (
          <div key={t.cell} className="absolute inset-y-0" style={{ left: `${t.pct}%` }}>
            <div
              className={cn(
                'absolute inset-y-0 -translate-x-1/2',
                t.kind === 'start' ? 'race-ribbon w-[6px] rounded-sm opacity-90' : 'w-px',
                t.kind === 'max' && 'bg-text/70',
                t.kind === 'plain' && 'bg-text/25',
                t.kind === 'zero' && 'bg-text/15',
              )}
            />
            {labels && (!compact || t.kind === 'start' || t.kind === 'max') && (
              <span
                className={cn(
                  'absolute top-1 -translate-x-1/2 whitespace-nowrap rounded-md px-1.5 py-0.5 text-[12px] font-semibold uppercase tracking-[0.06em]',
                  t.kind === 'start' ? 'bg-bg-alt/90 text-text' : 'text-text2',
                  t.kind === 'zero' && 'translate-x-0',
                  t.kind === 'max' && '-translate-x-full',
                )}
                style={{ fontSize: 'max(12px, calc(var(--race-fs) * 0.8))' }}
              >
                {compact && t.kind === 'max' ? 'макс. 400' : compact && t.kind === 'start' ? 'старт' : t.label}
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
