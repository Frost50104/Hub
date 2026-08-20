import { useDraggable } from '@dnd-kit/core'
import { CSS } from '@dnd-kit/utilities'
import type { CSSProperties } from 'react'

import { cn } from '@/lib/cn'
import { isOverdue } from '@/lib/taskDates'
import { type Task, type TaskPriority } from '@/lib/tasks'
import { OVERDUE_FILL, STATUS_FILL } from '@/lib/tone'

/** Планка приоритета слева: у `medium` её нет. Плотная заливка позади — тон
 *  планки берём как у строки (`PRIORITY_BAR`), но рамкой. */
const PRIORITY_EDGE: Record<TaskPriority, string> = {
  urgent: 'border-l-red',
  high: 'border-l-amber',
  low: 'border-l-blue-deep',
  medium: 'border-l-transparent',
}

interface CalendarTaskBarProps {
  task: Task
  /** Which calendar day this chip is rendered in (ISO YYYY-MM-DD). */
  day: string
  onClick: () => void
  /** Мобильный список дней: 44px, перенос строк, без перетаскивания. */
  variant?: 'cell' | 'list'
}

/**
 * Плашка задачи в календаре. Заливка = статус (`STATUS_FILL` из словаря
 * тонов), **при просрочке — сплошной `--red`**: один факт обязан выглядеть
 * одинаково в списке (красный срок), на доске (красный чип) и здесь. Статус в
 * этом случае вторичен — задача уже горит. Слева планка 3px приоритета.
 *
 * The same task may render in many cells (multi-day span); each chip carries
 * its origin `day` so the drop handler can compute a stable per-day offset.
 */
export function CalendarTaskBar({ task, day, onClick, variant = 'cell' }: CalendarTaskBarProps) {
  const dragId = `task-${task.id}|${day}`
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: dragId,
    data: { taskId: task.id, day },
    disabled: variant === 'list',
  })

  const style: CSSProperties = {
    transform: CSS.Translate.toString(transform),
    opacity: isDragging ? 0.4 : 1,
  }
  const overdue = isOverdue(task.due_at, task.status)
  const fill = overdue ? OVERDUE_FILL : STATUS_FILL[task.status]

  return (
    <button
      ref={setNodeRef}
      style={style}
      {...attributes}
      {...listeners}
      onClick={(e) => {
        e.stopPropagation()
        onClick()
      }}
      type="button"
      className={cn(
        'w-full border-l-[3px] text-left font-semibold',
        variant === 'cell'
          ? 'cursor-grab truncate rounded-[5px] px-1.5 py-0.5 text-[12px] leading-tight'
          : 'min-h-11 rounded-lg px-2.5 py-2 text-[14px] leading-[1.35]',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60',
        fill,
        PRIORITY_EDGE[task.priority],
      )}
      title={task.title}
      aria-label={task.title}
    >
      {task.title}
    </button>
  )
}
