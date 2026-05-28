import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { CheckCircle2, Circle, ClipboardCheck, Clock } from 'lucide-react'
import type { CSSProperties } from 'react'

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

interface KanbanCardProps {
  task: Task
  onClick?: () => void
  onToggleDone?: () => void
}

/**
 * Compact card for board view. Sortable via @dnd-kit.
 * Click anywhere → open task drawer (drag won't trigger thanks to
 * `activationConstraint: { distance: 5 }` on the PointerSensor).
 * Status-icon stops propagation to handle done-toggle independently.
 */
export function KanbanCard({ task, onClick, onToggleDone }: KanbanCardProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: task.id })
  const style: CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.4 : 1,
  }
  const StatusIcon = STATUS_ICON[task.status]

  return (
    <div
      ref={setNodeRef}
      style={style}
      {...attributes}
      {...listeners}
      onClick={onClick}
      className={cn(
        'glass cursor-grab space-y-2 p-3 active:cursor-grabbing',
        task.status === 'done' && 'opacity-70',
        isDragging && 'shadow-glass ring-1 ring-amber',
      )}
    >
      <div className="flex items-start gap-2">
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation()
            onToggleDone?.()
          }}
          onPointerDown={(e) => e.stopPropagation()}
          className={cn('mt-0.5 shrink-0', STATUS_TONE[task.status])}
          title={STATUS_LABEL[task.status]}
          aria-label={STATUS_LABEL[task.status]}
        >
          <StatusIcon className="h-4 w-4" />
        </button>
        <p
          className={cn(
            'flex-1 text-sm font-medium leading-tight text-text',
            task.status === 'done' && 'line-through',
          )}
        >
          {task.title}
        </p>
      </div>

      {(task.priority !== 'medium' || task.due_at || task.assignee) && (
        <div className="flex items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-1">
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
              <span className="text-[10px] text-text3">
                {new Date(task.due_at).toLocaleDateString('ru-RU', {
                  day: 'numeric',
                  month: 'short',
                })}
              </span>
            )}
          </div>
          {task.assignee && (
            <Avatar
              name={task.assignee.full_name}
              email={task.assignee.email}
              className="h-6 w-6 text-[9px]"
            />
          )}
        </div>
      )}
    </div>
  )
}
