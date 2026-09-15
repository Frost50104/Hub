import { forwardRef, type SelectHTMLAttributes } from 'react'

import { cn } from '@/lib/cn'

/**
 * Геометрия и вид поля-списка админ-форм.
 *
 * Вынесено в константу 16.09: длинные списки переехали на `SearchableSelect`, у
 * которого триггер — кнопка, и она обязана совпадать с соседним нативным
 * селектом ПИКСЕЛЬ-В-ПИКСЕЛЬ. В карточке сотрудника «Магазин» (с поиском) и
 * «Должность» (без) стоят в одной строке, и разница в высоте видна сразу.
 * `appearance-none` кнопке не нужен, но и не мешает.
 */
export const SELECT_FIELD_CLASS =
  'h-9 w-full appearance-none rounded-lg border border-glass-border bg-glass px-3 py-1 text-sm text-text transition-colors focus-visible:outline-none focus-visible:border-amber focus-visible:ring-1 focus-visible:ring-amber disabled:cursor-not-allowed disabled:opacity-50'

/**
 * Нативный select в стилистике Input — прагматичный выбор для админ-форм
 * (Ф0 LMS): системный дропдаун отлично работает на мобиле, ноль зависимостей.
 *
 * Остаётся для КОРОТКИХ словарей. Там, где вариантов десятки и больше, —
 * `ui/SearchableSelect`: у нативного списка нет поиска, и «Руководитель» с 315
 * строками искали прокруткой (ОС 16.09).
 */
export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(
  ({ className, children, ...props }, ref) => (
    <select
      ref={ref}
      className={cn('flex', SELECT_FIELD_CLASS, className)}
      {...props}
    >
      {children}
    </select>
  ),
)
Select.displayName = 'Select'
