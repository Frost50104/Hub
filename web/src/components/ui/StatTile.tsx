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
  className,
}: {
  label: string
  value: string
  accent?: boolean
  className?: string
}) {
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
          accent ? 'text-green-deep' : 'text-text',
        )}
      >
        {value}
      </span>
    </div>
  )
}
