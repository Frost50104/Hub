import { useEffect, useState } from 'react'

import { QueryError } from '@/components/QueryError'
import { MobileTaskRow } from '@/components/task/MobileTaskRow'
import { TaskInlineCreate } from '@/components/task/TaskInlineCreate'
import { TaskRow } from '@/components/task/TaskRow'
import { hasTaskContext } from '@/components/task/TaskContextLine'
import { usePersonalTasks } from '@/hooks/usePersonalTasks'
import { useToggleDone } from '@/hooks/useTasks'
import { cn } from '@/lib/cn'
import { personalListView } from '@/lib/personalTasks'
import { requestInlineCreate } from '@/lib/quickCreate'
import { MY_TASKS_GRID } from '@/lib/taskGrid'
import { type Task } from '@/lib/tasks'

/**
 * Вкладка «Личные» на «Моих задачах».
 *
 * Пришла на смену секции «ЛИЧНОЕ», которая висела НАД вкладками и им не
 * подчинялась. Секция была единственным входом в скрытое личное пространство и
 * ровно поэтому не нашлась: свою личную задачу за всё время завели 9 человек
 * из 178, а 145 видели там только задачу-инструкцию, которую Hub заводит сам.
 * Теперь личные задачи идут в общих окнах наравне с рабочими, а эта вкладка —
 * их отдельный срез: инбокс, куда можно писать.
 *
 * Строка создания — СВЕРХУ, в отличие от прежней секции. Снизу она оказывалась
 * под клавиатурой iOS, под FAB и под плавающей пилюлей вкладок, а на почти
 * пустой вкладке читалась как подвал, а не как главное действие.
 *
 * Список берётся из ручки ПРОЕКТА (`usePersonalTasks` → `['tasks', id]`), а не
 * из `/me/tasks?scope=personal`: так остаются чипы комментариев, сворачивание
 * подзадач в «k/N» у родителя и общий кэш с инлайн-созданием.
 */
export function PersonalTaskList({
  variant,
  onOpenTask,
  selectedTaskId,
  focusCreate = false,
  onFocusHandled,
}: {
  variant: 'desktop' | 'mobile'
  onOpenTask: (task: Task) => void
  selectedTaskId?: string | null
  /** Пришли по `?new=personal` из FAB — сфокусировать строку создания. */
  focusCreate?: boolean
  onFocusHandled?: () => void
}) {
  const { projectId, query } = usePersonalTasks()
  const [showAllDone, setShowAllDone] = useState(false)
  const toggleDone = useToggleDone(projectId ?? '')
  const desktop = variant === 'desktop'

  useEffect(() => {
    if (!focusCreate || !projectId) return
    // Тиком позже: из шторки FAB фокус в этот момент держит её триггер.
    const timer = window.setTimeout(() => {
      requestInlineCreate(projectId)
      onFocusHandled?.()
    }, 0)
    return () => window.clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusCreate, projectId])

  if (!projectId) return null

  // Выполненные по умолчанию скрыты и раскрываются чипом (ОС 15.09): личный
  // список — инбокс, и за полгода под инпутом накопилась бы стена «Готово».
  const view = personalListView(query.data, { doneLimit: 0, showAllDone })
  const rows = [...view.open, ...view.done]
  // Полосу контекста резервируем, только если хоть одной строке есть что в ней
  // показать: у личных задач обычно нет ни меток, ни счётчиков, и пустая
  // полоса поднимала заголовок над чекбоксом (ОС 24.08).
  const reserveContext = rows.some((t) =>
    hasTaskContext(t, { subtasks: view.subtasksByParent.get(t.id), fallback: null }),
  )

  return (
    <section aria-label="Личные задачи">
      <div className={desktop ? 'py-2 pl-[11px] pr-6' : 'px-4 py-2'}>
        <TaskInlineCreate
          projectId={projectId}
          placeholder="+ Новая личная задача"
          quickCreateTarget
        />
      </div>

      <header
        className={cn(
          'flex items-center gap-2 pb-[7px] pt-1.5',
          desktop ? 'px-[11px]' : 'px-4',
        )}
      >
        <span className="text-[13px] font-bold uppercase tracking-[0.06em] text-text2">
          Только для вас
        </span>
        <span className="font-mono text-[13px] text-text2">{view.counts.open}</span>
        {/* Чип, а не строка «Показать все выполненные» внизу списка (ОС 15.09):
            выполненных в списке по умолчанию нет, и число обязано остаться на
            виду — иначе человек решит, что задачи пропали. */}
        {view.counts.done > 0 && (
          <button
            type="button"
            onClick={() => setShowAllDone((v) => !v)}
            aria-pressed={showAllDone}
            className={cn(
              'ml-auto inline-flex h-7 shrink-0 items-center gap-1.5 rounded-full border px-2.5 text-[12px] font-semibold transition-colors',
              showAllDone
                ? 'border-amber/45 bg-amber/10 text-text'
                : 'border-glass-border text-text2 hover:text-text',
            )}
          >
            Выполненные
            <span className="font-mono">{view.counts.done}</span>
          </button>
        )}
      </header>

      {query.isError && (
        <QueryError
          error={query.error}
          onRetry={() => void query.refetch()}
          title="Не удалось загрузить личные задачи"
          className={desktop ? '' : 'm-4'}
        />
      )}

      {query.data && rows.length === 0 && (
        <p className={cn('pb-1 text-[13px] text-text2', desktop ? 'px-[11px]' : 'px-4')}>
          Только для вас — коллеги этих задач не увидят.
        </p>
      )}

      {rows.map((task) =>
        desktop ? (
          <TaskRow
            key={task.id}
            task={task}
            compact
            gridColumns={MY_TASKS_GRID.columns}
            subtasks={view.subtasksByParent.get(task.id)}
            // Четвёртый элемент грида обязателен: без него аватары уехали бы в
            // трек «Проект», а срок — в трек аватаров.
            cells={<span aria-hidden />}
            fallback={null}
            reserveContext={reserveContext}
            selected={selectedTaskId === task.id}
            onClick={() => onOpenTask(task)}
            onToggleDone={() => toggleDone(task)}
          />
        ) : (
          <MobileTaskRow
            key={task.id}
            task={task}
            subtasks={view.subtasksByParent.get(task.id)}
            fallback={null}
            reserveContext={reserveContext}
            selected={selectedTaskId === task.id}
            onClick={() => onOpenTask(task)}
            onToggleDone={() => toggleDone(task)}
          />
        ),
      )}
    </section>
  )
}
