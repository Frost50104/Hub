import { forwardRef, type InputHTMLAttributes } from 'react'

import { cn } from '@/lib/cn'

type NativeDateType = 'date' | 'time' | 'datetime-local'

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
  /** Приглушить подпись пустого заблокированного поля — как `disabled:opacity-50`
   *  у полей формы (`FIELD_CLASS`); у чипов карточки заблокированное не бледнеет. */
  dimDisabled?: boolean
}

/**
 * Родное поле даты/времени для десктопа, у которого ПУСТОЕ состояние видно
 * и в Safari.
 *
 * WebKit рисует пустое поле сегодняшним числом («25.09.2026»), а время —
 * «12:30», лишь чуть бледнее заданного: на глаз не отличить. ОС владельца
 * 25.09: у задачи без срока он не находил «+ время», которое появляется только
 * у заданной даты. Chrome в том же поле пишет «дд.мм.гггг».
 *
 * Пока значения нет, под полем в той же ячейке сетки лежит «пустой чип» — span
 * с ТЕМИ ЖЕ классами, что у поля, и подписью «дд.мм.гггг». Само поле прозрачно
 * (`opacity` на элементе, а не на его псевдоэлементе) и проявляется только в
 * фокусе, а подпись прячется ТЕМИ ЖЕ псевдоклассами того же элемента, — поэтому
 * видно ровно что-то одно. Первая версия (0e98501) прятала сегменты правилом
 * `::-webkit-datetime-edit`, а подпись — через `peer-focus`, и в настоящем
 * Safari с открытым календарём два механизма разошлись: родная дата легла
 * поверх подписи (ОС 25.09, в headless-WebKit календаря нет).
 *
 * Обёртка и поле рендерятся всегда: иначе на переходе «пусто ↔ дата» поле
 * пересоздавалось бы посреди набора и теряло фокус.
 */
export const NativeDateInput = forwardRef<HTMLInputElement, Props>(function NativeDateInput(
  { type, value, className, layout = 'inline', dimDisabled = false, disabled, ...rest },
  ref,
) {
  const empty = !value
  return (
    <span className={layout === 'block' ? 'grid' : 'inline-grid'}>
      <input
        ref={ref}
        type={type}
        value={value}
        disabled={disabled}
        // Наши классы — ПОСЛЕ чужих: у пустого поля `disabled:opacity-0`
        // обязан перебить `disabled:opacity-50` из `FIELD_CLASS`, иначе
        // заблокированное поле просвечивало бы сегодняшним числом.
        className={cn(
          className,
          'peer col-start-1 row-start-1',
          empty && 'opacity-0 focus:opacity-100 focus-within:opacity-100 disabled:opacity-0',
        )}
        {...rest}
      />
      {empty && (
        <span
          aria-hidden
          className={cn(
            className,
            'pointer-events-none col-start-1 row-start-1 flex items-center text-text3 peer-focus:invisible peer-focus-within:invisible',
            disabled && dimDisabled && 'opacity-50',
          )}
        >
          {EMPTY_TEXT[type]}
        </span>
      )}
    </span>
  )
})
