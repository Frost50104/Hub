import { MobileTaskRow } from '@/components/task/MobileTaskRow'
import { TaskRow } from '@/components/task/TaskRow'
import { useDelegated } from '@/hooks/useDelegated'
import { cn } from '@/lib/cn'
import { MY_TASKS_GRID } from '@/lib/taskGrid'
import { type Task } from '@/lib/tasks'

/**
 * «Я поставил» — задачи, которые я положил людям в ЛИЧНОЕ (15.09).
 *
 * Без этой секции автор свою же задачу не найдёт: `personal_visible_to`
 * («не личный ИЛИ МОЙ личный») режет её и в поиске, и в комментариях, и у
 * ассистента, а в «Моих задачах» он не исполнитель — остаются только
 * уведомления и прямая ссылка.
 *
 * Секция стоит рядом с «ЛИЧНЫМ» и окнам дедлайнов не подчиняется: это не срез
 * моей работы, а список поручений. Выполненные сюда не приходят вовсе —
 * отдал и забыл.
 *
 * Пустая секция не рендерится: у большинства поручений нет, и постоянный
 * заголовок «Я поставил 0» был бы шумом.
 */
export function DelegatedSection({
  variant,
  onOpenTask,
  selectedTaskId,
}: {
  variant: 'desktop' | 'mobile'
  onOpenTask: (task: Task) => void
  selectedTaskId?: string | null
}) {
  const query = useDelegated()
  const tasks = query.data ?? []
  if (tasks.length === 0) return null
  const desktop = variant === 'desktop'

  return (
    <section aria-label="Задачи, поручённые лично">
      <div
        className={cn(
          'flex items-baseline gap-2 pb-[7px] pt-[18px]',
          desktop ? 'px-[11px]' : 'px-4',
        )}
      >
        <span className="text-[13px] font-bold uppercase tracking-[0.06em] text-text2">
          Я поставил
        </span>
        <span className="font-mono text-[13px] text-text2">{tasks.length}</span>
      </div>
      {tasks.map((task) =>
        desktop ? (
          <TaskRow
            key={task.id}
            task={task}
            compact
            gridColumns={MY_TASKS_GRID.columns}
            // Имя человека берётся из исполнителей задачи — чьё это личное
            // пространство, клиенту не сообщают и сообщать не нужно.
            fallback={null}
            cells={<span className="min-w-0 truncate pr-3.5 text-[14px] text-text2" />}
            selected={selectedTaskId === task.id}
            onClick={() => onOpenTask(task)}
          />
        ) : (
          <MobileTaskRow
            key={task.id}
            task={task}
            fallback={null}
            selected={selectedTaskId === task.id}
            onClick={() => onOpenTask(task)}
          />
        ),
      )}
    </section>
  )
}
