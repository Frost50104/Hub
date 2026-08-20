import { type KeyboardEvent, type ReactNode } from 'react'

import { PriorityBar } from '@/components/task/PriorityBar'
import { cn } from '@/lib/cn'
import { type TaskPriority } from '@/lib/tasks'

interface ListRowProps {
  /** Лид-элемент слева: плашка ключа, иконка статуса, аватар. */
  lead?: ReactNode
  title: ReactNode
  /** Вторая строка — контекст: мета, чипы. Рендерится всегда, даже пустая. */
  context?: ReactNode
  /** Справа: значение, счётчик, кнопка «…». */
  trailing?: ReactNode
  /** Планка приоритета у левого края (строка задачи). */
  priority?: TaskPriority
  selected?: boolean
  onClick?: () => void
  ariaLabel?: string
  className?: string
  titleClassName?: string
}

/**
 * Строка списка 64px — одна анатомия на проекты, задачи и уведомления:
 * планка приоритета (опц.) → лид-элемент → две строки текста → действие
 * справа. Контекстная строка занимает место всегда: иначе высота скачет и
 * список перестаёт сканироваться.
 *
 * Выделение — контур всей строки, не планка слева: 3px левого края принадлежат
 * приоритету. Левый отступ 16px (21 у строк задач, где 3px отданы планке —
 * задаётся `className`).
 */
export function ListRow({
  lead,
  title,
  context,
  trailing,
  priority,
  selected = false,
  onClick,
  ariaLabel,
  className,
  titleClassName,
}: ListRowProps) {
  const interactive = Boolean(onClick)
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      onClick?.()
    }
  }
  return (
    <div
      role={interactive ? 'button' : undefined}
      tabIndex={interactive ? 0 : undefined}
      aria-label={ariaLabel}
      onClick={onClick}
      onKeyDown={interactive ? onKey : undefined}
      className={cn(
        'relative flex min-h-16 items-center gap-3 border-b border-hair py-[9px] pl-4 pr-3.5 transition-colors',
        interactive &&
          'cursor-pointer hover:bg-glass focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-amber',
        selected && 'bg-surface shadow-[inset_0_0_0_1px_rgb(var(--amber))]',
        className,
      )}
    >
      {priority && <PriorityBar priority={priority} />}
      {lead && <span className="flex shrink-0 items-center">{lead}</span>}
      <span className="flex min-w-0 flex-1 flex-col gap-[3px]">
        <span
          className={cn(
            'flex min-w-0 items-center gap-2 text-[17px] font-semibold leading-[1.3] text-text',
            titleClassName,
          )}
        >
          {title}
        </span>
        <span className="flex min-h-[18px] min-w-0 items-center gap-2 text-[13px] leading-[1.35] text-text2">
          {context}
        </span>
      </span>
      {trailing && <span className="flex shrink-0 items-center gap-2">{trailing}</span>}
    </div>
  )
}
