import { cn } from '@/lib/cn'

/**
 * Плашка-показатель: подпись 13px сверху, значение Unbounded снизу.
 *
 * Один силуэт на весь продукт — отчёты ассистента и сводка библиотеки должны
 * выглядеть одинаково, иначе два места независимо разъедутся по высоте и
 * скруглению. `accent` красит значение в `--green-deep` (рост, «всё хорошо»);
 * по умолчанию значение нейтральное.
 */
export function StatTile({
  label,
  value,
  accent = false,
  variant = 'stat',
  tone = 'default',
  hint,
  className,
}: {
  label: string
  value: string
  accent?: boolean
  /**
   * `stat` — отчёты и сводка библиотеки (13px подпись, 17/20 значение);
   * `kpi` — дашборд и аналитика (12/700 uppercase подпись, Unbounded 26 tabular).
   */
  variant?: 'stat' | 'kpi'
  /** Краска значения у `kpi`: «В архиве» — muted, «Готово 30 д» — success, «Просрочено» — danger. */
  tone?: 'default' | 'muted' | 'success' | 'danger'
  /** Строка мелким под значением (аналитика: «привязали аккаунт»). */
  hint?: string
  className?: string
}) {
  const valueTone =
    accent || tone === 'success'
      ? 'text-green-deep'
      : tone === 'danger'
        ? 'text-red'
        : tone === 'muted'
          ? 'text-text2'
          : 'text-text'
  if (variant === 'kpi') {
    return (
      <div
        className={cn(
          'flex min-w-0 flex-col gap-1 rounded-xl border border-glass-border bg-tint p-3.5',
          className,
        )}
      >
        <span className="text-[12px] font-bold uppercase tracking-[0.07em] text-text2">{label}</span>
        <span className={cn('font-display text-[26px] font-bold leading-[1.15] tabular-nums', valueTone)}>
          {value}
        </span>
        {hint && <span className="text-[12px] text-text2">{hint}</span>}
      </div>
    )
  }
  return (
    <div
      className={cn(
        'flex min-w-[140px] flex-1 shrink-0 flex-col gap-1 rounded-xl border border-glass-border bg-tint px-3.5 py-3',
        className,
      )}
    >
      <span className="text-[13px] text-text2">{label}</span>
      <span
        className={cn(
          'font-display text-[17px] font-bold leading-[1.2] lg:text-[20px]',
          valueTone,
        )}
      >
        {value}
      </span>
      {hint && <span className="text-[12px] text-text2">{hint}</span>}
    </div>
  )
}
