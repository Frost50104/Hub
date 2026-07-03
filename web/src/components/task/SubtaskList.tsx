import { CheckCircle2, Circle } from 'lucide-react'
import { useMemo } from 'react'

import { TaskInlineCreate } from '@/components/task/TaskInlineCreate'
import { cn } from '@/lib/cn'
import { useTasks, useToggleDone } from '@/hooks/useTasks'

interface SubtaskListProps {
  /** Родительская задача. */
  taskId: string
  projectId: string
  canEdit: boolean
  /** Открыть подзадачу в drawer (тот же URL-механизм ?task=). */
  onOpenTask?: (id: string) => void
}

/**
 * Секция «Подзадачи» в карточке задачи. Данные — из общего кэша списка
 * задач проекта (GET /tasks отдаёт всё плоско), фильтруем по parent_task_id.
 * Глубина — один уровень (enforced на backend), поэтому у подзадач
 * этой секции нет.
 */
export function SubtaskList({ taskId, projectId, canEdit, onOpenTask }: SubtaskListProps) {
  const tasks = useTasks(projectId)
  const toggleDone = useToggleDone(projectId)

  const subtasks = useMemo(
    () =>
      (tasks.data ?? []).filter(
        (t) => t.parent_task_id === taskId && !t.archived_at,
      ),
    [tasks.data, taskId],
  )

  const doneCount = subtasks.filter((t) => t.status === 'done').length

  if (!canEdit && subtasks.length === 0) return null

  return (
    <section className="space-y-2">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-text3">
        Подзадачи{subtasks.length > 0 ? ` (${doneCount}/${subtasks.length})` : ''}
      </h3>

      <div>
        {subtasks.map((t) => (
          <div
            key={t.id}
            className="flex items-center gap-2 border-b border-glass-border py-1.5"
          >
            <button
              type="button"
              onClick={() => toggleDone(t)}
              disabled={!canEdit}
              aria-label={t.status === 'done' ? 'Вернуть в работу' : 'Завершить'}
              className={cn(
                'flex h-5 w-5 shrink-0 items-center justify-center rounded-full',
                t.status === 'done'
                  ? 'text-green hover:text-green/80'
                  : 'text-text3 hover:text-text2',
              )}
            >
              {t.status === 'done' ? (
                <CheckCircle2 className="h-4 w-4" />
              ) : (
                <Circle className="h-4 w-4" />
              )}
            </button>
            <button
              type="button"
              onClick={() => onOpenTask?.(t.id)}
              className={cn(
                'min-w-0 flex-1 truncate text-left text-sm text-text hover:text-amber',
                t.status === 'done' && 'line-through opacity-60',
              )}
            >
              {t.title}
            </button>
          </div>
        ))}
      </div>

      {canEdit && (
        <TaskInlineCreate
          projectId={projectId}
          sectionId={null}
          parentTaskId={taskId}
          placeholder="+ Подзадача"
        />
      )}
    </section>
  )
}
