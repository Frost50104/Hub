import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { ListTree, Plus } from 'lucide-react'
import type { CSSProperties } from 'react'

import { PriorityBar } from '@/components/task/PriorityBar'
import { TaskLabelChip } from '@/components/task/TaskLabelChip'
import { TaskStatusControl } from '@/components/task/TaskStatusControl'
import { AvatarStack } from '@/components/ui/AvatarStack'
import { cn } from '@/lib/cn'
import { taskAssignees } from '@/lib/taskAssignees'
import { isOverdue, shortDate } from '@/lib/taskDates'
import { type Label } from '@/lib/labels'
import { type SubtaskStats, type Task } from '@/lib/tasks'

interface KanbanCardProps {
  task: Task
  subtasks?: SubtaskStats
  labels?: Label[]
  onClick?: () => void
  onToggleDone?: () => void
  /** Карточка в DragOverlay: без sortable-обвязки и без обработчиков. */
  overlay?: boolean
}

/**
 * Карточка доски. Геометрия из спеки: радиус 12, рамка `--glass-border`, фон
 * `--bg-alt`, отбивки 11/12/11/14 (слева больше — там планка приоритета).
 *
 * Просрочка показывается ТАК ЖЕ, как в списке: плотный красный текст, а не
 * серая подпись 10px. Один факт не имеет права выглядеть в двух представлениях
 * по-разному — это и был главный дефект прежней доски. Ключа «KEY-42» на
 * карточке нет: он живёт в карточке задачи.
 */
export function KanbanCard({
  task,
  subtasks,
  labels,
  onClick,
  onToggleDone,
  overlay = false,
}: KanbanCardProps) {
  const sortable = useSortable({ id: task.id, disabled: overlay })
  const style: CSSProperties = overlay
    ? {}
    : {
        transform: CSS.Transform.toString(sortable.transform),
        transition: sortable.transition,
        opacity: sortable.isDragging ? 0.4 : 1,
      }
  const assignees = taskAssignees(task)
  const done = task.status === 'done'
  const overdue = isOverdue(task.due_at, task.status)
  const hasMeta = (labels?.length ?? 0) > 0 || (subtasks?.total ?? 0) > 0

  return (
    <div
      ref={overlay ? undefined : sortable.setNodeRef}
      style={style}
      {...(overlay ? {} : sortable.attributes)}
      {...(overlay ? {} : sortable.listeners)}
      onClick={onClick}
      role="button"
      tabIndex={overlay ? -1 : 0}
      aria-roledescription="draggable task"
      aria-grabbed={sortable.isDragging || undefined}
      aria-label={task.title}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onClick?.()
        }
      }}
      className={cn(
        'relative flex cursor-grab flex-col gap-[9px] rounded-xl border border-glass-border bg-bg-alt py-[11px] pl-[14px] pr-3 transition-colors',
        'hover:bg-glass active:cursor-grabbing',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60 focus-visible:ring-offset-2 focus-visible:ring-offset-bg',
        sortable.isDragging && 'ring-1 ring-amber',
      )}
    >
      <PriorityBar priority={task.priority} className="inset-y-[10px]" />

      <div className="flex items-start gap-2.5">
        <TaskStatusControl status={task.status} size="card" onToggle={onToggleDone} />
        <span
          className={cn(
            'min-w-0 flex-1 text-[16px] font-semibold leading-[1.35]',
            done ? 'text-text2 line-through' : 'text-text',
          )}
        >
          {task.title}
        </span>
      </div>

      {hasMeta && (
        <div className="flex flex-wrap items-center gap-1.5">
          {labels?.map((l) => (
            <TaskLabelChip key={l.id} label={l} />
          ))}
          {subtasks && subtasks.total > 0 && (
            <span
              className="inline-flex h-[22px] items-center gap-1 text-[13px] text-text2"
              title={`Подзадачи: ${subtasks.done} из ${subtasks.total}`}
            >
              <ListTree className="h-[13px] w-[13px]" strokeWidth={1.9} />
              {subtasks.done}/{subtasks.total}
            </span>
          )}
        </div>
      )}

      <div className="flex items-center justify-between gap-2 border-t border-hair pt-[9px]">
        <span
          className={cn(
            'text-[13px] tabular-nums',
            overdue ? 'font-semibold text-red' : 'text-text2',
          )}
        >
          {task.due_at ? shortDate(task.due_at) : 'Без срока'}
        </span>
        {assignees.length === 0 ? (
          <button
            type="button"
            aria-label="Назначить исполнителя"
            title="Назначить исполнителя"
            onClick={(e) => {
              e.stopPropagation()
              onClick?.()
            }}
            onPointerDown={(e) => e.stopPropagation()}
            className="flex h-6 w-6 items-center justify-center rounded-full border border-dashed border-glass-border text-text2 hover:border-amber hover:text-text"
          >
            <Plus className="h-[14px] w-[14px]" strokeWidth={2} />
          </button>
        ) : (
          <AvatarStack people={assignees} max={2} />
        )}
      </div>
    </div>
  )
}
