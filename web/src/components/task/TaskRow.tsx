import { CheckCircle2, Circle, ClipboardCheck, Clock, ListTree, MessageSquare } from 'lucide-react'

import { Avatar } from '@/components/ui/Avatar'
import { Badge } from '@/components/ui/Badge'
import { cn } from '@/lib/cn'
import { type CustomFieldDefinition, type CustomFieldValue } from '@/lib/customFields'
import { formatCustomFieldValue } from '@/lib/formatCustomField'
import { type Label } from '@/lib/labels'
import {
  PRIORITY_LABEL,
  STATUS_LABEL,
  type SubtaskStats,
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
  subtasks?: SubtaskStats
  labels?: Label[]
  onClick?: () => void
  onToggleDone?: () => void
  /** Custom field definitions to render as trailing columns, in display order. */
  visibleFields?: CustomFieldDefinition[]
  /** Map field_id → stored value for THIS task (parent fetches once). */
  customValues?: Map<string, CustomFieldValue>
}

/**
 * List-view task row (Asana-style table line).
 *
 * Columns: status | title (+ badges) | assignee | <custom fields...> | due.
 * Custom-field cells are read-only — click propagates to onClick which
 * opens the task drawer (full editor lives there). Inline editing in the
 * table is a future enhancement.
 */
export function TaskRow({
  task,
  subtasks,
  labels,
  onClick,
  onToggleDone,
  visibleFields = [],
  customValues,
}: TaskRowProps) {
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
        {subtasks && subtasks.total > 0 && (
          <span
            className="inline-flex shrink-0 items-center gap-0.5 text-[10px] text-text3"
            title={`Подзадачи: ${subtasks.done} из ${subtasks.total} готово`}
          >
            <ListTree className="h-3 w-3" /> {subtasks.done}/{subtasks.total}
          </span>
        )}
        {labels?.slice(0, 3).map((l) => (
          <span
            key={l.id}
            className="hidden shrink-0 items-center gap-1 rounded-full border border-glass-border px-1.5 text-[10px] text-text2 lg:inline-flex"
            title={l.name}
          >
            <span
              className="h-1.5 w-1.5 rounded-full"
              style={{ backgroundColor: l.color }}
              aria-hidden
            />
            {l.name}
          </span>
        ))}
        {labels && labels.length > 3 && (
          <span className="hidden shrink-0 text-[10px] text-text3 lg:inline">
            +{labels.length - 3}
          </span>
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

      <div className="flex items-center gap-3 text-right text-xs">
        {visibleFields.map((f) => {
          const v = customValues?.get(f.id)?.value
          return (
            <span
              key={f.id}
              className="hidden w-24 truncate text-text2 lg:inline-block"
              title={`${f.name}: ${formatCustomFieldValue(f, v)}`}
            >
              {formatCustomFieldValue(f, v)}
            </span>
          )
        })}
        <span className="inline-block w-14 lg:w-24">
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
        </span>
      </div>
    </div>
  )
}
