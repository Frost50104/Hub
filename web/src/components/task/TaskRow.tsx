import { Plus } from 'lucide-react'

import { TaskContextLine } from '@/components/task/TaskContextLine'
import { TaskStatusControl } from '@/components/task/TaskStatusControl'
import { PriorityBar } from '@/components/task/PriorityBar'
import { AvatarStack } from '@/components/ui/AvatarStack'
import { cn } from '@/lib/cn'
import { type Label } from '@/lib/labels'
import { taskAssignees } from '@/lib/taskAssignees'
import { isOverdue, shortDate } from '@/lib/taskDates'
import { type SubtaskStats, type Task } from '@/lib/tasks'

interface TaskRowProps {
  task: Task
  /** Треки из `lib/taskGrid.ts` — те же, что у шапки колонок. */
  gridColumns: string
  /** Ячейки между заголовком и исполнителями: кастом-поля или проект. */
  cells?: React.ReactNode
  labels?: Label[]
  subtasks?: SubtaskStats
  /** Чем занять строку контекста, когда рассказывать нечего. */
  fallback?: string | null
  /** Строка, открытая в карточке задачи. */
  selected?: boolean
  onClick?: () => void
  onToggleDone?: () => void
  /** «Мои задачи» — узкие отбивки: колонок кастом-полей там нет. */
  compact?: boolean
}

/**
 * Строка списка задач (десктоп): фиксированные 64px, две строки внутри.
 *
 * Высота фиксирована, а строка контекста рендерится всегда — иначе список
 * «дышит» и перестаёт сканироваться. Слева 21px вместо 24px: три пикселя
 * отданы планке приоритета.
 *
 * Выделение — обводка всей строки, а не полоса слева: левый край принадлежит
 * приоритету, и красная планка `urgent` перекрывала бы амбер, из-за чего
 * «выбрано» выглядело бы по-разному на разных приоритетах.
 */
export function TaskRow({
  task,
  gridColumns,
  cells,
  labels,
  subtasks,
  fallback,
  selected = false,
  onClick,
  onToggleDone,
  compact = false,
}: TaskRowProps) {
  const done = task.status === 'done'
  const overdue = isOverdue(task.due_at, task.status)
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
      style={{ gridTemplateColumns: gridColumns }}
      className={cn(
        'relative grid h-16 items-center border-b border-hair transition-colors',
        compact ? 'pl-[11px] pr-2' : 'pl-[21px] pr-6',
        onClick && 'cursor-pointer hover:bg-glass',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-amber',
        selected && 'bg-surface shadow-[inset_0_0_0_1px_rgb(var(--amber))]',
      )}
    >
      <PriorityBar priority={task.priority} />

      <span className="flex min-w-0 items-center gap-3 pl-[3px]">
        <TaskStatusControl status={task.status} onToggle={onToggleDone} />
        <span className="flex min-w-0 flex-1 flex-col gap-[3px]">
          <span
            className={cn(
              'min-w-0 truncate text-[17px] font-medium leading-[1.35]',
              done ? 'text-text2 line-through' : 'text-text',
            )}
          >
            {task.title}
          </span>
          <TaskContextLine
            task={task}
            labels={labels}
            subtasks={subtasks}
            fallback={fallback}
          />
        </span>
      </span>

      {cells}

      <span className="flex items-center justify-end">
        {assignees.length === 0 ? (
          <button
            type="button"
            aria-label="Назначить исполнителя"
            title="Назначить исполнителя"
            onClick={(e) => {
              e.stopPropagation()
              // Пикер живёт в карточке задачи: держать поповер в каждой из
              // сотен строк дороже, чем открыть карточку.
              onClick?.()
            }}
            className="flex h-6 w-6 items-center justify-center rounded-full border border-dashed border-glass-border text-text2 hover:border-amber hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
          >
            <Plus className="h-[14px] w-[14px]" strokeWidth={2} />
          </button>
        ) : (
          <AvatarStack people={assignees} max={3} />
        )}
      </span>

      <span
        className={cn(
          'text-right text-[14px] tabular-nums',
          overdue ? 'font-semibold text-red' : 'text-text2',
        )}
      >
        {task.due_at ? shortDate(task.due_at) : '—'}
      </span>
    </div>
  )
}
