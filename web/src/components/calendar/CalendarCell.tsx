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
        'flex min-h-[88px] flex-col gap-1 border border-glass-border/40 p-1.5 transition-colors md:min-h-[112px]',
        isOver && 'bg-amber/5 ring-1 ring-amber/40',
        !isCurrentMonth && 'bg-bg-alt/40',
      )}
    >
      <div className="flex items-center justify-between">
        <span
          className={cn(
            'inline-flex h-5 w-5 items-center justify-center text-xs',
            isToday && 'rounded-full bg-amber font-semibold text-bg',
            !isToday && isCurrentMonth && 'text-text2',
            !isCurrentMonth && 'text-text3',
          )}
          aria-current={isToday ? 'date' : undefined}
        >
          {dayNumber}
        </span>
      </div>

      <div className="flex flex-col gap-0.5">
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
            className="rounded px-1 py-0.5 text-left text-[10px] text-text3 hover:bg-glass hover:text-text"
          >
            +{hiddenCount} ещё
          </button>
        )}
      </div>
    </div>
  )
}
