import { cn } from '@/lib/cn'

/**
 * Шапка колонок списка. Треки приходят из `lib/taskGrid.ts` — те же, что у
 * строки: две независимые декларации расходятся на пиксели, и подписи
 * перестают стоять над значениями.
 *
 * Колонки задачи и исполнителей подписей не имеют (`aria-hidden`): заголовок
 * и аватары называют себя сами.
 */
export function TaskListHeader({
  gridColumns,
  fieldNames,
  compact = false,
  leadLabel,
}: {
  gridColumns: string
  /** Подписи средних колонок в порядке треков. */
  fieldNames: string[]
  compact?: boolean
  /** Подпись первой средней колонки в «Моих задачах» — «Проект». */
  leadLabel?: string
}) {
  const cell = 'flex h-[38px] items-center text-[12px] font-bold uppercase tracking-[0.07em] text-text2'
  const labels = leadLabel ? [leadLabel, ...fieldNames] : fieldNames
  return (
    <div
      style={{ gridTemplateColumns: gridColumns }}
      className={cn(
        'grid items-center border-b border-hair bg-bg',
        compact ? 'pl-[11px] pr-2' : 'pl-[21px] pr-6',
      )}
    >
      <span aria-hidden className={cell} />
      {labels.map((name, i) => (
        <span key={`${name}-${i}`} className={cn(cell, 'truncate pr-3.5')} title={name}>
          {name}
        </span>
      ))}
      <span aria-hidden className={cn(cell, 'justify-end')} />
      <span className={cn(cell, 'justify-end')}>Срок</span>
    </div>
  )
}
