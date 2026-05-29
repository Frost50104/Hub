import { useDraggable } from '@dnd-kit/core'
import { CSS } from '@dnd-kit/utilities'
import type { CSSProperties } from 'react'

import { cn } from '@/lib/cn'
import { type Task, type TaskPriority } from '@/lib/tasks'

const PRIORITY_BAR: Record<TaskPriority, string> = {
  low: 'border-l-text3',
  medium: 'border-l-amber/50',
  high: 'border-l-amber',
  urgent: 'border-l-red',
}

interface CalendarTaskBarProps {
  task: Task
  /** Which calendar day this chip is rendered in (ISO YYYY-MM-DD). */
  day: string
  onClick: () => void
}

/**
 * One pill inside a calendar cell. The same task may render in many cells
 * (multi-day span); each chip carries its origin `day` so the drop handler
 * can compute a stable per-day offset.
 *
 * We don't draw an absolutely-positioned bar across cells (CSS-grid +
 * absolute is fragile across month boundaries). Repeating the pill per day
 * gives the same Asana-style "see this task on every day it overlaps"
 * without the layout pain.
 */
export function CalendarTaskBar({ task, day, onClick }: CalendarTaskBarProps) {
  const dragId = `task-${task.id}|${day}`
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: dragId,
    data: { taskId: task.id, day },
  })

  const style: CSSProperties = {
    transform: CSS.Translate.toString(transform),
    opacity: isDragging ? 0.4 : 1,
  }

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
        'w-full truncate rounded-sm border-l-2 bg-surface px-1.5 py-0.5 text-left text-[11px] leading-tight text-text',
        'hover:bg-glass focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-amber/60',
        task.status === 'done' && 'line-through opacity-60',
        PRIORITY_BAR[task.priority],
      )}
      title={task.title}
      aria-label={task.title}
    >
      {task.title}
    </button>
  )
}
