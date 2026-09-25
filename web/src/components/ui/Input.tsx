import { forwardRef, type InputHTMLAttributes, type TextareaHTMLAttributes } from 'react'

import { cn } from '@/lib/cn'

/**
 * Общий вид поля ввода: рамка, фон, типографика и — главное — ФОКУС.
 *
 * Вынесено константой, потому что фокус здесь состоит из двух согласованных
 * частей: граница перекрашивается в амбер И поверх ложится кольцо 1px того же
 * цвета. Стоит собрать поле руками и взять только кольцо (`ring-2 ring-amber/60`),
 * как под ним остаётся серая `--glass-border` — контур читается двойным и поле
 * выпадает из системы. Ровно это случилось с формой обратной связи (ОС 26.08).
 *
 * Компоненту с собственной механикой (`AutoGrowTextarea`) класс передают
 * отсюда, а не переписывают.
 */
const FIELD_CLASS =
  'w-full border border-glass-border bg-glass text-text placeholder:text-text3 transition-colors focus-visible:outline-none focus-visible:border-amber focus-visible:ring-1 focus-visible:ring-amber disabled:cursor-not-allowed disabled:opacity-50'

/**
 * Многострочное поле — тот же вид, что у `Textarea`, без её тега.
 *
 * БЕЗ `flex`: класс уезжает в `AutoGrowTextarea`, а там его получает ещё и
 * невидимый двойник, по которому считается высота. `display: flex` оборачивает
 * его текст в анонимный флекс-элемент, тот перестаёт переноситься — и поле
 * замирает на минимальной высоте вместо того, чтобы расти (замер 26.08:
 * 4 997 символов давали scrollHeight 107px). Сам `Textarea` `flex` добавляет
 * себе отдельно, чтобы его вид не изменился.
 */
export const TEXTAREA_CLASS = `min-h-[80px] rounded-lg px-3 py-2 text-sm ${FIELD_CLASS}`

/** Выпадающий список формы — тот же вид и тот же фокус, что у поля ввода.
 *  Собранный руками селект брал только кольцо и получал двойной контур. */
export const SELECT_CLASS = `h-10 rounded-lg px-3 text-sm ${FIELD_CLASS}`

/** Поле ввода целиком — для родных полей даты формы (`NativeDateInput`),
 *  которые рисуются не через `Input`, но обязаны выглядеть так же. */
export const FIELD_INPUT_CLASS = `flex h-9 rounded-lg px-3 py-1 text-sm ${FIELD_CLASS}`

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => (
    <input ref={ref} className={cn(FIELD_INPUT_CLASS, className)} {...props} />
  ),
)
Input.displayName = 'Input'

export const Textarea = forwardRef<
  HTMLTextAreaElement,
  TextareaHTMLAttributes<HTMLTextAreaElement>
>(({ className, ...props }, ref) => (
  <textarea
    ref={ref}
    className={cn('flex', TEXTAREA_CLASS, className)}
    {...props}
  />
))
Textarea.displayName = 'Textarea'
