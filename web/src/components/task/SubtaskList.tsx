import { Check } from 'lucide-react'
import { useMemo } from 'react'

import { DrawerSection } from '@/components/task/DrawerSection'
import { TaskInlineCreate } from '@/components/task/TaskInlineCreate'
import { AvatarStack } from '@/components/ui/AvatarStack'
import { useTasks, useToggleDone } from '@/hooks/useTasks'
import { cn } from '@/lib/cn'
import { taskAssignees } from '@/lib/taskAssignees'

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
    <DrawerSection
      title="Подзадачи"
      count={subtasks.length > 0 ? `${doneCount}/${subtasks.length}` : null}
    >
      <div className="flex flex-col">
        {subtasks.map((t) => {
          const done = t.status === 'done'
          return (
            <div
              key={t.id}
              className="flex min-h-12 items-center gap-[11px] border-b border-hair py-2"
            >
              {/* Отметка выполнения — плотный зелёный круг 22px: зелёный в
                  редизайне означает ровно «сделано». */}
              <button
                type="button"
                onClick={() => toggleDone(t)}
                disabled={!canEdit}
                aria-label={done ? 'Вернуть в работу' : 'Завершить'}
                className={cn(
                  'flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-full',
                  done
                    ? 'bg-green-deep text-bg'
                    : 'border border-glass-border text-transparent hover:border-amber',
                )}
              >
                <Check className="h-[13px] w-[13px]" strokeWidth={3} />
              </button>
              <button
                type="button"
                onClick={() => onOpenTask?.(t.id)}
                className={cn(
                  'min-w-0 flex-1 truncate text-left text-[16px] leading-[1.4] hover:text-amber',
                  done ? 'text-text2 line-through' : 'text-text',
                )}
              >
                {t.title}
              </button>
              <AvatarStack people={taskAssignees(t)} max={2} />
            </div>
          )
        })}
      </div>

      {canEdit && (
        <TaskInlineCreate
          projectId={projectId}
          sectionId={null}
          parentTaskId={taskId}
          placeholder="+ Подзадача"
        />
      )}
    </DrawerSection>
  )
}
