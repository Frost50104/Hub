import { ChevronDown, Plus } from 'lucide-react'
import { useEffect, useState } from 'react'

import { QueryError } from '@/components/QueryError'
import { MobileTaskRow } from '@/components/task/MobileTaskRow'
import { TaskInlineCreate } from '@/components/task/TaskInlineCreate'
import { hasTaskContext } from '@/components/task/TaskContextLine'
import { TaskRow } from '@/components/task/TaskRow'
import { usePersonalTasks } from '@/hooks/usePersonalTasks'
import { useToggleDone } from '@/hooks/useTasks'
import { cn } from '@/lib/cn'
import { personalSectionState } from '@/lib/personalTasks'
import { requestInlineCreate } from '@/lib/quickCreate'
import { MY_TASKS_GRID } from '@/lib/taskGrid'
import { type Task } from '@/lib/tasks'
import { PERSONAL_SECTION_KEY, useViewConfig } from '@/stores/viewConfig'

interface PersonalTasksSectionProps {
  /** Десктоп рисует TaskRow по MY_TASKS_GRID, мобилка — MobileTaskRow. */
  variant: 'desktop' | 'mobile'
  onOpenTask: (task: Task) => void
  selectedTaskId?: string | null
  /** FAB привёл сюда с просьбой поставить курсор в поле создания. */
  focusCreate?: boolean
  /** Просьбу обработали — страница вычищает `?new=personal`. */
  onFocusHandled?: () => void
}

/**
 * Секция «ЛИЧНОЕ» на «Моих задачах» — единственный вход в личное пространство:
 * сам проект скрыт из сайдбара, /projects и селекта создания задачи.
 *
 * Стоит НАД вкладками окон дедлайнов и им не подчиняется: типичная личная
 * задача без срока, и под дефолтной вкладкой «Предстоит» секция была бы пустой
 * у большинства. Заодно она не размонтируется при переключении вкладки —
 * TaskInlineCreate коммитит черновик на unmount, и переключение посреди набора
 * создавало бы задачу из полуфразы.
 */
export function PersonalTasksSection({
  variant,
  onOpenTask,
  selectedTaskId,
  focusCreate = false,
  onFocusHandled,
}: PersonalTasksSectionProps) {
  const { projectId, query, meIsPending } = usePersonalTasks()
  const [showAllDone, setShowAllDone] = useState(false)
  const collapsed = useViewConfig((s) =>
    projectId
      ? (s.byProject[projectId]?.collapsedSections?.includes(PERSONAL_SECTION_KEY) ??
        false)
      : false,
  )
  const toggleSection = useViewConfig((s) => s.toggleSection)
  // projectId, а не '': иначе useUpdateTask патчил бы кэш ['tasks',''] —
  // префикс не совпал бы с ['tasks', <uuid>], и чекбокс не сработал бы до
  // рефетча по фокусу окна.
  const toggleDone = useToggleDone(projectId ?? '')

  const state = personalSectionState({
    meIsPending,
    personalProjectId: projectId,
    isPending: query.isPending,
    isError: query.isError,
    tasks: query.data,
    showAllDone,
  })

  const expand = () => {
    if (collapsed && projectId) toggleSection(projectId, PERSONAL_SECTION_KEY)
  }

  useEffect(() => {
    if (!focusCreate || !projectId) return
    expand()
    // Тиком позже: инпут свёрнутой секции ещё не смонтирован, а из шторки FAB
    // фокус в этот момент держит её триггер (приём из ProjectPage).
    const timer = window.setTimeout(() => {
      requestInlineCreate(projectId)
      onFocusHandled?.()
    }, 0)
    return () => window.clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusCreate, projectId])

  if (state.kind === 'hidden') return null

  const counts = state.kind === 'ready' ? state.view.counts : null
  const desktop = variant === 'desktop'
  const rows =
    state.kind === 'ready' ? [...state.view.open, ...state.view.done] : []
  // Полосу контекста резервируем, только если хоть одной строке есть что в
  // ней показать: у личных задач обычно нет ни меток, ни счётчиков, и пустая
  // полоса поднимала заголовок над чекбоксом (ОС 24.08).
  const reserveContext =
    state.kind === 'ready' &&
    rows.some((t) =>
      hasTaskContext(t, {
        subtasks: state.view.subtasksByParent.get(t.id),
        fallback: null,
      }),
    )

  return (
    <section aria-label="Личные задачи">
      <header
        className={cn(
          'flex items-center gap-2 pb-[7px] pt-[18px]',
          desktop ? 'px-[11px]' : 'px-4',
        )}
      >
        <button
          type="button"
          onClick={() => toggleSection(state.projectId, PERSONAL_SECTION_KEY)}
          aria-expanded={!collapsed}
          className="flex min-h-11 flex-1 items-center gap-2 text-left lg:min-h-0"
        >
          <ChevronDown
            className={cn(
              'h-[15px] w-[15px] shrink-0 text-text2 transition-transform',
              collapsed && '-rotate-90',
            )}
            strokeWidth={2.2}
          />
          <span className="text-[13px] font-bold uppercase tracking-[0.06em] text-text2">
            Личное
          </span>
          {counts && (
            <span className="font-mono text-[13px] text-text2">{counts.open}</span>
          )}
        </button>
        {/* Чип, а не строка «Показать все выполненные» внизу списка (ОС 15.09):
            выполненных в списке по умолчанию нет, и число обязано остаться на
            виду — иначе человек решит, что задачи пропали. Переключается в обе
            стороны; прежняя ссылка была односторонней. */}
        {!collapsed && counts && counts.done > 0 && (
          <button
            type="button"
            onClick={() => setShowAllDone((v) => !v)}
            aria-pressed={showAllDone}
            className={cn(
              'inline-flex h-7 shrink-0 items-center gap-1.5 rounded-full border px-2.5 text-[12px] font-semibold transition-colors',
              showAllDone
                ? 'border-amber/45 bg-amber/10 text-text'
                : 'border-glass-border text-text2 hover:text-text',
            )}
          >
            Выполненные
            <span className="font-mono">{counts.done}</span>
          </button>
        )}
        {collapsed && (
          <button
            type="button"
            aria-label="Новая личная задача"
            onClick={() => {
              expand()
              window.setTimeout(() => requestInlineCreate(state.projectId), 0)
            }}
            className="-m-1.5 inline-flex h-11 w-11 items-center justify-center text-text2 hover:text-text lg:h-8 lg:w-8"
          >
            <Plus className="h-4 w-4" strokeWidth={2.4} />
          </button>
        )}
      </header>

      {!collapsed && (
        <>
          {state.kind === 'error' && (
            <QueryError
              error={query.error}
              onRetry={() => void query.refetch()}
              title="Не удалось загрузить личные задачи"
              className={desktop ? '' : 'm-4'}
            />
          )}

          {state.kind === 'ready' && (
            <>
              {state.view.counts.open === 0 && state.view.counts.done === 0 && (
                <p
                  className={cn(
                    'pb-1 text-[13px] text-text2',
                    desktop ? 'px-[11px]' : 'px-4',
                  )}
                >
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
                    subtasks={state.view.subtasksByParent.get(task.id)}
                    // Четвёртый элемент грида обязателен: без него аватары
                    // уехали бы в трек «Проект», а срок — в трек аватаров.
                    cells={<span aria-hidden />}
                    // Контекст уже назван шапкой секции.
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
                    subtasks={state.view.subtasksByParent.get(task.id)}
                    fallback={null}
                    reserveContext={reserveContext}
                    selected={selectedTaskId === task.id}
                    onClick={() => onOpenTask(task)}
                    onToggleDone={() => toggleDone(task)}
                  />
                ),
              )}

            </>
          )}

          <div className={desktop ? 'py-2 pl-[11px] pr-6' : 'px-4 py-2'}>
            <TaskInlineCreate
              projectId={state.projectId}
                  placeholder="+ Новая личная задача"
              quickCreateTarget
            />
          </div>
        </>
      )}
    </section>
  )
}
