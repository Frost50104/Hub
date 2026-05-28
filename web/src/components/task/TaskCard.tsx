import { CheckCircle2, Circle, Clock, ClipboardCheck } from 'lucide-react'

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
  todo: 'text-text3',
  in_progress: 'text-amber',
  in_review: 'text-amber',
  done: 'text-green',
}

interface TaskCardProps {
  task: Task
  onClick?: () => void
  onToggleDone?: () => void
}

export function TaskCard({ task, onClick, onToggleDone }: TaskCardProps) {
  const StatusIcon = STATUS_ICON[task.status]
  return (
    <div
      className={cn(
        'glass flex items-center gap-3 p-3 transition-colors',
        onClick && 'cursor-pointer hover:bg-surface',
        task.status === 'done' && 'opacity-70',
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
          'flex h-5 w-5 shrink-0 items-center justify-center',
          STATUS_TONE[task.status],
        )}
        title={STATUS_LABEL[task.status]}
        aria-label={STATUS_LABEL[task.status]}
      >
        <StatusIcon className="h-5 w-5" />
      </button>
      <div className="min-w-0 flex-1">
        <p
          className={cn(
            'truncate text-sm font-medium text-text',
            task.status === 'done' && 'line-through',
          )}
        >
          {task.title}
        </p>
        {(task.priority !== 'medium' || task.due_at) && (
          <div className="mt-1 flex items-center gap-2 text-xs text-text3">
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
            {task.due_at && (
              <span>до {new Date(task.due_at).toLocaleDateString('ru-RU')}</span>
            )}
          </div>
        )}
      </div>
      {task.assignee && (
        <Avatar
          name={task.assignee.full_name}
          email={task.assignee.email}
          className="h-7 w-7 text-[10px]"
        />
      )}
    </div>
  )
}
