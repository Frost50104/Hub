import { CheckCircle2, Circle, ClipboardCheck, Clock } from 'lucide-react'

import { cn } from '@/lib/cn'
import { STATUS_LABEL, type TaskStatus } from '@/lib/tasks'
import { STATUS_INK } from '@/lib/tone'

const STATUS_ICON: Record<TaskStatus, typeof Circle> = {
  todo: Circle,
  in_progress: Clock,
  in_review: ClipboardCheck,
  done: CheckCircle2,
}

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

interface TaskStatusControlProps {
  status: TaskStatus
  size?: keyof typeof BOX
  /**
   * Переключение статуса. Дизайн рисует десктопную иконку неинтерактивной, но
   * в продукте это единственный способ закрыть задачу, не открывая карточку —
   * действие сохраняем, визуально кнопка не отличается от иконки.
   */
  onToggle?: () => void
  className?: string
}

export function TaskStatusControl({
  status,
  size = 'row',
  onToggle,
  className,
}: TaskStatusControlProps) {
  const Icon = STATUS_ICON[status]
  const body = (
    <Icon className={ICON[size]} strokeWidth={size === 'mobile' ? 1.5 : 1.9} />
  )
  const shell = cn(
    'flex shrink-0 items-center justify-center',
    BOX[size],
    STATUS_INK[status],
    className,
  )

  if (!onToggle) {
    return (
      <span className={shell} title={STATUS_LABEL[status]} aria-hidden>
        {body}
      </span>
    )
  }
  return (
    <button
      type="button"
      // Строка целиком — role=button; вложенная кнопка обязана гасить событие,
      // иначе смена статуса заодно открывала бы карточку.
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
      title={STATUS_LABEL[status]}
      aria-label={`Статус: ${STATUS_LABEL[status]}. Сменить`}
    >
      {body}
    </button>
  )
}
