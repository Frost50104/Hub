import { QueryError } from '@/components/QueryError'
import { MobileTaskRow } from '@/components/task/MobileTaskRow'
import { TaskEmptyState, TaskListSkeleton } from '@/components/task/TaskListStates'
import { TaskRow } from '@/components/task/TaskRow'
import { useAssignedByMe } from '@/hooks/useAssignedByMe'
import { MY_TASKS_GRID } from '@/lib/taskGrid'
import { type TaskProjectLabel } from '@/lib/taskProjectLabel'
import { type Task } from '@/lib/tasks'

/**
 * Вкладка «Назначенные мной»: что я поручил другим и это ещё не закрыто.
 *
 * Пришла на смену секции «Я поставил», которая видела только поручения в чужое
 * личное пространство — на проде это 2 задачи из 37. Теперь сюда попадает всё,
 * что я создал и назначил человеку, в любом проекте.
 *
 * Вкладка остаётся в полосе, даже когда пуста (секция при нуле пряталась, и для
 * секции это было верно): иначе полоса дёргается после загрузки, а ссылка
 * `?tab=assigned` из чужого сообщения упирается в несуществующую вкладку.
 */
export function AssignedByMeList({
  variant,
  onOpenTask,
  selectedTaskId,
  projectLabel,
}: {
  variant: 'desktop' | 'mobile'
  onOpenTask: (task: Task) => void
  selectedTaskId?: string | null
  /** Подпись и адрес проекта для чипа в строке — общие с остальными вкладками. */
  projectLabel: (task: Task) => TaskProjectLabel
}) {
  const query = useAssignedByMe()
  const desktop = variant === 'desktop'

  if (query.isLoading) return <TaskListSkeleton compact={!desktop} />
  if (query.isError) {
    return (
      <QueryError
        error={query.error}
        onRetry={() => void query.refetch()}
        title="Не удалось загрузить поручения"
        className={desktop ? '' : 'm-4'}
      />
    )
  }
  const tasks = query.data ?? []
  if (tasks.length === 0) {
    return (
      <TaskEmptyState
        title="Вы пока никому не ставили задач."
        text="Здесь появятся задачи, которые вы создали и назначили коллегам."
      />
    )
  }

  return (
    <div className="flex flex-col">
      {tasks.map((task) =>
        desktop ? (
          <TaskRow
            key={task.id}
            task={task}
            compact
            gridColumns={MY_TASKS_GRID.columns}
            // Проект — подписью под заголовком, как на остальных вкладках и на
            // телефоне; кому поручено — видно по аватарам исполнителей.
            project={projectLabel(task)}
            stage={task.stage_name}
            selected={selectedTaskId === task.id}
            onClick={() => onOpenTask(task)}
          />
        ) : (
          <MobileTaskRow
            key={task.id}
            task={task}
            stage={task.stage_name}
            project={projectLabel(task)}
            selected={selectedTaskId === task.id}
            onClick={() => onOpenTask(task)}
          />
        ),
      )}
    </div>
  )
}
