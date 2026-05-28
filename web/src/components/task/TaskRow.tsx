import { CheckCircle2, Circle, ClipboardCheck, Clock, MessageSquare } from 'lucide-react'

import { Avatar } from '@/components/ui/Avatar'
import { Badge } from '@/components/ui/Badge'
import { cn } from '@/lib/cn'
import {
  PRIORITY_LABEL,
  STATUS_LABEL,
  type Task,
  type TaskStatus,
} from '@/lib/tasks'

const STATUS_ICON: Record<TaskStatus, typeof Circle> = {
  todo: Circle,
  in_progress: Clock,
  in_review: ClipboardCheck,
  done: CheckCircle2,
}

const STATUS_TONE: Record<TaskStatus, string> = {
  todo: 'text-text3 hover:text-text2',
  in_progress: 'text-amber hover:text-amber/80',
  in_review: 'text-amber hover:text-amber/80',
  done: 'text-green hover:text-green/80',
}

interface TaskRowProps {
  task: Task
  onClick?: () => void
  onToggleDone?: () => void
}

/**
 * List-view task row (Asana-style table line).
 * Columns: status-checkbox | title (+ badges) | assignee | due date.
 * Used inside SectionBlock — full-width borderless row.
 */
export function TaskRow({ task, onClick, onToggleDone }: TaskRowProps) {
  const StatusIcon = STATUS_ICON[task.status]
  const overdue =
    task.due_at &&
    task.status !== 'done' &&
    new Date(task.due_at).getTime() < Date.now()

  return (
    <div
      className={cn(
        'group grid grid-cols-[auto_1fr_auto_auto] items-center gap-3 border-b border-glass-border px-2 py-2 transition-colors',
        onClick && 'cursor-pointer hover:bg-glass',
        task.status === 'done' && 'opacity-60',
      )}
      onClick={onClick}
    >
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation()
          onToggleDone?.()
        }}
        className={cn(
          'flex h-5 w-5 shrink-0 items-center justify-center rounded-full transition-colors',
          STATUS_TONE[task.status],
        )}
        title={STATUS_LABEL[task.status]}
        aria-label={STATUS_LABEL[task.status]}
      >
        <StatusIcon className="h-5 w-5" />
      </button>

      <div className="flex min-w-0 items-center gap-2">
        <span
          className={cn(
            'truncate text-sm text-text',
            task.status === 'done' && 'line-through',
          )}
        >
          {task.title}
        </span>
        {task.priority !== 'medium' && (
          <Badge
            variant={
              task.priority === 'urgent' || task.priority === 'high'
                ? 'destructive'
                : 'secondary'
            }
          >
            {PRIORITY_LABEL[task.priority]}
          </Badge>
        )}
      </div>

      <div className="flex h-7 w-7 shrink-0 items-center justify-center text-text3">
        {task.assignee ? (
          <Avatar
            name={task.assignee.full_name}
            email={task.assignee.email}
            className="h-7 w-7 text-[10px]"
          />
        ) : (
          <span
            className="flex h-7 w-7 items-center justify-center rounded-full border border-dashed border-glass-border opacity-50"
            title="Не назначено"
          >
            <MessageSquare className="hidden h-3 w-3" />
          </span>
        )}
      </div>

      <div className="w-24 text-right text-xs">
        {task.due_at ? (
          <span className={cn(overdue ? 'text-red' : 'text-text2')}>
            {new Date(task.due_at).toLocaleDateString('ru-RU', {
              day: 'numeric',
              month: 'short',
            })}
          </span>
        ) : (
          <span className="text-text3">—</span>
        )}
      </div>
    </div>
  )
}
