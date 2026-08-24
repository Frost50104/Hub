import { Check, Circle } from 'lucide-react'

import { cn } from '@/lib/cn'
import { DONE_INK, doneTone } from '@/lib/tone'

const BOX = {
  /** Строка списка на десктопе: иконка 19px в боксе 24px. */
  row: 'h-6 w-6',
  /** Мобильная строка: иконка 24px внутри тап-цели 44px. */
  mobile: 'h-11 w-11 -ml-2 -mr-2.5',
  /** Карточка доски: иконка 18px. */
  card: 'h-6 w-6',
} as const

const ICON = {
  row: 'h-[19px] w-[19px]',
  mobile: 'h-6 w-6',
  card: 'h-[18px] w-[18px]',
} as const

interface TaskDoneControlProps {
  done: boolean
  size?: keyof typeof BOX
  /**
   * Переключение состояния. Дизайн рисует десктопную иконку неинтерактивной,
   * но в продукте это единственный способ закрыть задачу, не открывая
   * карточку — действие сохраняем, визуально кнопка не отличается от иконки.
   */
  onToggle?: () => void
  className?: string
}

/**
 * Состояние задачи (0044): выполнена или нет — два состояния вместо четырёх
 * статусов. Колонка доски к состоянию отношения не имеет: галочку ставят из
 * любой колонки, и карточка остаётся на месте.
 */
export function TaskDoneControl({
  done,
  size = 'row',
  onToggle,
  className,
}: TaskDoneControlProps) {
  const label = done ? 'Выполнена' : 'Не выполнена'
  const body = done ? (
    <span
      className={cn(
        'flex items-center justify-center rounded-full bg-green-deep text-bg',
        size === 'mobile' ? 'h-6 w-6' : 'h-[19px] w-[19px]',
      )}
    >
      <Check className={size === 'mobile' ? 'h-4 w-4' : 'h-3 w-3'} strokeWidth={2.6} />
    </span>
  ) : (
    <Circle className={ICON[size]} strokeWidth={size === 'mobile' ? 1.5 : 1.9} />
  )
  const shell = cn(
    'flex shrink-0 items-center justify-center',
    BOX[size],
    DONE_INK[doneTone(done)],
    className,
  )

  if (!onToggle) {
    return (
      <span className={shell} title={label} aria-hidden>
        {body}
      </span>
    )
  }
  return (
    <button
      type="button"
      // Строка целиком — role=button; вложенная кнопка обязана гасить событие,
      // иначе галочка заодно открывала бы карточку.
      onClick={(e) => {
        e.stopPropagation()
        onToggle()
      }}
      onPointerDown={(e) => e.stopPropagation()}
      onKeyDown={(e) => e.stopPropagation()}
      className={cn(
        shell,
        'rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60',
      )}
      title={done ? 'Вернуть в работу' : 'Отметить выполненной'}
      aria-label={`${label}. ${done ? 'Вернуть в работу' : 'Отметить выполненной'}`}
      aria-pressed={done}
    >
      {body}
    </button>
  )
}
