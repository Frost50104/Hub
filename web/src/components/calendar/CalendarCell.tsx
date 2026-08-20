import { useDroppable } from '@dnd-kit/core'
import { useState } from 'react'

import { cn } from '@/lib/cn'
import { type Task } from '@/lib/tasks'

import { CalendarTaskBar } from './CalendarTaskBar'

interface CalendarCellProps {
  /** ISO YYYY-MM-DD. */
  day: string
  /** Day-of-month integer (1..31) for the header chip. */
  dayNumber: number
  /** Whether this cell belongs to the rendered month (vs leading/trailing). */
  isCurrentMonth: boolean
  isToday: boolean
  tasks: Task[]
  onTaskClick: (id: string) => void
}

const MAX_CHIPS_DEFAULT = 3

/**
 * Ячейка месяца: min-height 96, номер — чип 22px моноширинный («сегодня» —
 * амбер), фон `--bg-alt` внутри месяца и `--tint` вне. Вне месяца гасим
 * ФОНОМ, а не `opacity`: opacity душит и число, и плашки задач.
 * Приём при перетаскивании — amber 8% + inset-контур 50%.
 */
export function CalendarCell({
  day,
  dayNumber,
  isCurrentMonth,
  isToday,
  tasks,
  onTaskClick,
}: CalendarCellProps) {
  const { setNodeRef, isOver } = useDroppable({ id: `cal-${day}` })
  const [expanded, setExpanded] = useState(false)
  const visibleTasks = expanded ? tasks : tasks.slice(0, MAX_CHIPS_DEFAULT)
  const hiddenCount = tasks.length - visibleTasks.length

  return (
    <div
      ref={setNodeRef}
      className={cn(
        'flex min-h-[96px] flex-col gap-[3px] p-[5px] pb-1.5 transition-colors',
        isCurrentMonth ? 'bg-bg-alt' : 'bg-tint',
        isOver && 'bg-amber/[0.08] shadow-[inset_0_0_0_1px_rgb(var(--amber)/0.5)]',
      )}
    >
      <div className="flex items-center justify-between">
        <span
          className={cn(
            'inline-flex h-[22px] min-w-[22px] items-center justify-center rounded-md px-1 font-mono text-[12px]',
            isToday ? 'bg-amber font-bold text-on-amber' : 'text-text2',
          )}
          aria-current={isToday ? 'date' : undefined}
        >
          {dayNumber}
        </span>
      </div>

      <div className="flex flex-col gap-[3px]">
        {visibleTasks.map((task) => (
          <CalendarTaskBar
            key={`${task.id}|${day}`}
            task={task}
            day={day}
            onClick={() => onTaskClick(task.id)}
          />
        ))}
        {hiddenCount > 0 && (
          <button
            type="button"
            onClick={() => setExpanded(true)}
            className="rounded px-1 py-0.5 text-left text-[12px] text-text2 hover:bg-glass hover:text-text"
          >
            +{hiddenCount} ещё
          </button>
        )}
      </div>
    </div>
  )
}
