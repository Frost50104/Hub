import { forwardRef } from 'react'

import { cn } from '@/lib/cn'

/**
 * Textarea, растущая по содержимому БЕЗ измерения scrollHeight.
 *
 * Прежний вариант выставлял высоту из `scrollHeight` в ref-колбэке — и это
 * ломалось на мобильном: высота считалась ДО загрузки Unbounded, шрифт
 * подменялся, строка переносилась третий раз, а высота оставалась старой, и
 * хвост заголовка обрезался (видно на 360/390, на 430 заголовок влезал в две
 * строки и баг не проявлялся).
 *
 * Здесь высоту задаёт невидимый двойник в той же ячейке грида: он подчиняется
 * тем же правилам переноса и пересчитывается браузером сам — и при смене
 * шрифта, и при смене ширины. Пробел в конце нужен, чтобы последняя строка,
 * заканчивающаяся переводом строки, не схлопывалась.
 */
export const AutoGrowTextarea = forwardRef<
  HTMLTextAreaElement,
  React.ComponentPropsWithoutRef<'textarea'> & { value: string }
>(({ className, value, ...props }, ref) => (
  <div className="grid">
    <textarea
      ref={ref}
      rows={1}
      value={value}
      className={cn(
        'col-start-1 row-start-1 resize-none overflow-hidden',
        className,
      )}
      {...props}
    />
    <span
      aria-hidden
      className={cn(
        'invisible col-start-1 row-start-1 whitespace-pre-wrap break-words',
        className,
      )}
    >
      {value + ' '}
    </span>
  </div>
))
AutoGrowTextarea.displayName = 'AutoGrowTextarea'
