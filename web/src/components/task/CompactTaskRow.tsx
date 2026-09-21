import { ProjectChip } from '@/components/task/ProjectChip'
import { TaskDoneControl } from '@/components/task/TaskDoneControl'
import { PriorityBar } from '@/components/task/PriorityBar'
import { cn } from '@/lib/cn'
import { shortDate, taskOverdue } from '@/lib/taskDates'
import { type TaskProjectLabel } from '@/lib/taskProjectLabel'
import { type Task } from '@/lib/tasks'

/**
 * Узкая строка задачи для панели «Мои задачи» на «Главной»: 60px, без колонок.
 * Панель узкая, поэтому проект уходит во вторую строку чипом-ссылкой, а
 * исполнители и кастом-поля не показываются вовсе — на них нет места, а не
 * «они не важны».
 */
export function CompactTaskRow({
  task,
  project,
  onClick,
  onToggleDone,
}: {
  task: Task
  project?: TaskProjectLabel | null
  onClick?: () => void
  onToggleDone?: () => void
}) {
  const done = task.done
  const overdue = taskOverdue(task)
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
        'relative flex min-h-[60px] cursor-pointer items-center gap-[11px] border-b border-hair py-2 pl-[11px] pr-1 transition-colors last:border-b-0 hover:bg-glass',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-amber',
      )}
    >
      <PriorityBar priority={task.priority} />
      <TaskDoneControl done={task.done} onToggle={onToggleDone} />
      <span className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span
          className={cn(
            'min-w-0 truncate text-[17px] font-medium leading-[1.35]',
            done ? 'text-text2 line-through' : 'text-text',
          )}
        >
          {task.title}
        </span>
        {/* `self-start`: контейнер — flex-col, и без него чип растянулся бы на
            всю ширину строки (align-self: stretch по умолчанию). */}
        <ProjectChip label={project} className="max-w-full self-start" />
      </span>
      <span
        className={cn(
          'shrink-0 text-right text-[14px] tabular-nums',
          overdue ? 'font-semibold text-red' : 'text-text2',
        )}
      >
        {task.due_at ? shortDate(task.due_at) : '—'}
      </span>
    </div>
  )
}
