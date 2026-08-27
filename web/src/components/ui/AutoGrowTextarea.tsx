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
 *
 * **`min-w-0` обязателен на гриде И на обоих детях.** У элемента в grid-ячейке
 * `min-width: auto`, то есть ячейка не уже своего min-content — а min-content
 * слова без пробелов равен ВСЕМУ слову. Ссылка или строка из 5 000 символов
 * подряд растягивала поле до 41 592px (замер 26.08): текст уезжал за правый
 * край, диалог получал горизонтальную прокрутку, а `overflow-wrap` не помогал —
 * слово в такой строке помещалось, ломать было нечего. С `min-w-0` перенос
 * включается сам, отдельный `word-break` не нужен (проверено на стенде).
 */
export const AutoGrowTextarea = forwardRef<
  HTMLTextAreaElement,
  React.ComponentPropsWithoutRef<'textarea'> & { value: string }
>(({ className, value, ...props }, ref) => (
  <div className="grid min-w-0">
    <textarea
      ref={ref}
      rows={1}
      value={value}
      className={cn(
        'col-start-1 row-start-1 min-w-0 resize-none overflow-hidden',
        className,
      )}
      {...props}
    />
    <span
      aria-hidden
      className={cn(
        'invisible col-start-1 row-start-1 min-w-0 whitespace-pre-wrap break-words',
        className,
      )}
    >
      {value + ' '}
    </span>
  </div>
))
AutoGrowTextarea.displayName = 'AutoGrowTextarea'
