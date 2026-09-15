import { Plus } from 'lucide-react'

import { TaskContextLine } from '@/components/task/TaskContextLine'
import { TaskDoneControl } from '@/components/task/TaskDoneControl'
import { PriorityBar } from '@/components/task/PriorityBar'
import { AvatarStack } from '@/components/ui/AvatarStack'
import { cn } from '@/lib/cn'
import { type Label } from '@/lib/labels'
import { taskAssignees } from '@/lib/taskAssignees'
import { type TaskContextMode } from '@/lib/taskContext'
import { isOverdue, shortDate } from '@/lib/taskDates'
import { type TaskProjectLabel } from '@/lib/taskProjectLabel'
import { type SubtaskStats, type Task } from '@/lib/tasks'

interface MobileTaskRowProps {
  task: Task
  labels?: Label[]
  subtasks?: SubtaskStats
  /** Проект — чип-ссылка в строке контекста рядом с колонкой (16.09). */
  project?: TaskProjectLabel | null
  /** Имя колонки доски — текстом в строке контекста. */
  stage?: string | null
  selected?: boolean
  onClick?: () => void
  onToggleDone?: () => void
  /** `plain` — в строке контекста только проект (узкие списки «Главной»). */
  context?: TaskContextMode
  /** См. TaskContextLine.reserve. */
  reserveContext?: boolean
}

/**
 * Мобильная строка задачи: та же модель, другая раскладка.
 *
 * На 390px заголовок в 64 знака в одну строку не влезает физически (nowrap
 * показывал 37-49% текста) — две строки с обрезкой на третьей. Колонок нет:
 * срок уходит вправо, остальное — в строку контекста, где по месту помещается
 * одна метка, а прочие схлопываются в «+N».
 *
 * Раньше строка была `<Link>` с `<button>` внутри — невалидная вложенность,
 * из-за которой кнопка статуса была недостижима частью скринридеров.
 */
export function MobileTaskRow({
  task,
  labels,
  subtasks,
  project,
  stage,
  selected = false,
  onClick,
  onToggleDone,
  context = 'auto',
  reserveContext = true,
}: MobileTaskRowProps) {
  const done = task.done
  const overdue = isOverdue(task.due_at, task.done)
  const assignees = taskAssignees(task)

  return (
    <div
      role="button"
      tabIndex={0}
      aria-label={task.title}
      onClick={onClick}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onClick?.()
        }
      }}
      className={cn(
        'relative flex min-h-16 items-center gap-3 border-b border-hair py-[9px] pl-[13px] pr-4 active:bg-glass',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-amber',
        selected && 'bg-surface shadow-[inset_0_0_0_1px_rgb(var(--amber))]',
      )}
    >
      <PriorityBar priority={task.priority} />

      <TaskDoneControl done={task.done} size="mobile" onToggle={onToggleDone} />

      <span className="flex min-w-0 flex-1 flex-col gap-1">
        <span
          className={cn(
            'line-clamp-2 min-w-0 text-[16px] font-medium leading-[1.35] [text-wrap:pretty]',
            done ? 'text-text2 line-through' : 'text-text',
          )}
        >
          {task.title}
        </span>
        <TaskContextLine
          stage={stage}
          task={task}
          labels={labels}
          subtasks={subtasks}
          project={project}
          compact
          mode={context}
          reserve={reserveContext}
        />
      </span>

      <span className="flex shrink-0 flex-col items-end gap-1.5">
        <span
          className={cn(
            'whitespace-nowrap text-[13px] tabular-nums',
            overdue ? 'font-semibold text-red' : 'text-text2',
          )}
        >
          {task.due_at ? shortDate(task.due_at) : '—'}
        </span>
        {assignees.length === 0 ? (
          <span
            aria-hidden
            className="flex h-6 w-6 items-center justify-center rounded-full border border-dashed border-glass-border text-text2"
          >
            <Plus className="h-[14px] w-[14px]" strokeWidth={2} />
          </span>
        ) : (
          <AvatarStack people={assignees} max={2} />
        )}
      </span>
    </div>
  )
}
