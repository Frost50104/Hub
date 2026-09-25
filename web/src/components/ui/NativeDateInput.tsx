import { forwardRef, type InputHTMLAttributes } from 'react'

import { cn } from '@/lib/cn'

type NativeDateType = 'date' | 'time' | 'datetime-local'

/** Движок рисует сегменты поля псевдоэлементом, который можно спрятать. */
const HIDES_SEGMENTS =
  typeof CSS !== 'undefined' &&
  typeof CSS.supports === 'function' &&
  CSS.supports('selector(::-webkit-datetime-edit)')

const EMPTY_TEXT: Record<NativeDateType, string> = {
  date: 'дд.мм.гггг',
  time: '--:--',
  'datetime-local': 'дд.мм.гггг, --:--',
}

interface Props extends Omit<InputHTMLAttributes<HTMLInputElement>, 'type' | 'value'> {
  type: NativeDateType
  value: string
  /** `inline` — чип в ряду (карточка задачи), `block` — поле формы во всю ширину. */
  layout?: 'inline' | 'block'
}

/**
 * Родное поле даты/времени для десктопа, у которого ПУСТОЕ состояние видно
 * и в Safari.
 *
 * WebKit рисует пустое поле сегодняшним числом («25.09.2026»), а время —
 * «12:30», лишь чуть бледнее заданного значения: на глаз их не отличить. ОС
 * владельца 25.09: у задачи без срока «Старт» и «Срок» показывали сегодняшнюю
 * дату, и он не находил «+ время», которое появляется только у заданной даты.
 * Chrome в том же поле пишет «дд.мм.гггг».
 *
 * Пока пустое поле без фокуса, его сегменты спрятаны (`data-empty` + правило в
 * `globals.css`), а в ту же ячейку сетки ложится подпись с ТЕМИ ЖЕ классами,
 * что у поля, — поэтому она стоит ровно на месте текста, с теми же отступами и
 * полями. В фокусе всё родное: набор с клавиатуры и календарь не трогаем.
 * Движку без `::-webkit-datetime-edit` (Firefox) отдаём обычное поле — пустое
 * он рисует честно сам.
 */
export const NativeDateInput = forwardRef<HTMLInputElement, Props>(function NativeDateInput(
  { type, value, className, layout = 'inline', ...rest },
  ref,
) {
  if (!HIDES_SEGMENTS) {
    return <input ref={ref} type={type} value={value} className={className} {...rest} />
  }
  const empty = !value
  return (
    <span className={layout === 'block' ? 'grid' : 'inline-grid'}>
      <input
        ref={ref}
        type={type}
        value={value}
        data-empty={empty ? '' : undefined}
        className={cn('peer col-start-1 row-start-1', className)}
        {...rest}
      />
      {empty && (
        <span
          aria-hidden
          className={cn(
            className,
            'pointer-events-none col-start-1 row-start-1 flex items-center border-transparent bg-transparent text-text3 shadow-none peer-focus:hidden',
          )}
        >
          {EMPTY_TEXT[type]}
        </span>
      )}
    </span>
  )
})
