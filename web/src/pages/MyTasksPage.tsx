import { useEffect, useMemo } from 'react'
import { useLocation, useSearchParams } from 'react-router-dom'

import { FloatingActionButton } from '@/components/layout/FloatingActionButton'
import { MobilePageHeader } from '@/components/layout/MobilePageHeader'
import { MobileViewControlBar } from '@/components/layout/MobileViewControlBar'
import { QueryError } from '@/components/QueryError'
import { AssignedByMeList } from '@/components/task/AssignedByMeList'
import { MobileTaskRow } from '@/components/task/MobileTaskRow'
import { PersonalTaskList } from '@/components/task/PersonalTaskList'
import { TaskDetailDrawer } from '@/components/task/TaskDetailDrawer'
import { TaskEmptyState, TaskListSkeleton } from '@/components/task/TaskListStates'
import { TaskListHeader } from '@/components/task/TaskListHeader'
import { TaskRow } from '@/components/task/TaskRow'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { useMe } from '@/hooks/useMe'
import { useMyTasks } from '@/hooks/useMyTasks'
import { useProjects } from '@/hooks/useProjects'
import { useToggleDone } from '@/hooks/useTasks'
import { cn } from '@/lib/cn'
import { GROUP_LABEL, groupTasksByDue } from '@/lib/myTasksGroups'
import { compareDue } from '@/lib/taskDates'
import {
  MY_TASKS_TABS,
  clearNewPersonalParams,
  isDueWindowTab,
  isGroupedTab,
  myTasksEmptyText,
  resolveMyTasksTab,
  setMyTasksTab,
  type MyTasksTab,
} from '@/lib/myTasksTabs'
import { MY_TASKS_GRID } from '@/lib/taskGrid'
import { taskProjectLabel, type TaskProjectLabel } from '@/lib/taskProjectLabel'
import { type Task } from '@/lib/tasks'

/**
 * «Мои задачи» — единственный вход в личную работу (16.09).
 *
 * До этого на одну идею приходились две сущности: кросс-проектный экран и
 * скрытый проект «Личное», приклеенный к нему секцией сверху. Личное так и не
 * нашли — свою задачу завели 9 человек из 178, — а сам экран был пуст у 136
 * человек из 154 ровно потому, что их единственная задача личная, а личные из
 * него вырезались. Теперь экран поглотил проект: личные задачи идут вперемешку
 * с рабочими, `/projects/{мой личный}` редиректит сюда, а у личного
 * пространства больше нет ни доски, ни участников, ни «Поделиться».
 *
 * Карточка задачи открывается ЗДЕСЬ, в drawer'е, а не уводит на страницу
 * проекта: экран перестал быть оглавлением.
 */
export function MyTasksPage() {
  const isDesktop = useIsDesktop()
  const pane = useMyTasksPane()
  return (
    <>
      {isDesktop ? <DesktopMyTasks pane={pane} /> : <MobileMyTasks pane={pane} />}
      <TaskDetailDrawer
        taskId={pane.openTaskId}
        // Проект НАЖАТОЙ строки, а не личный: drawer считает всё от проекта
        // задачи (`task?.project_id ?? projectId`), и пока задача летит с
        // сервера, фолбэк определяет, за чьими колонками уйдёт первый запрос.
        projectId={pane.openTaskProjectId ?? ''}
        onClose={pane.closeTask}
        onOpenTask={pane.openTaskById}
      />
    </>
  )
}

interface MyTasksPane {
  tab: MyTasksTab
  setTab: (tab: MyTasksTab) => void
  personalProjectId: string | undefined
  openTaskId: string | null
  openTaskProjectId: string | null
  openTask: (task: Task) => void
  openTaskById: (taskId: string) => void
  closeTask: () => void
  focusCreate: boolean
  clearFocusCreate: () => void
  projectLabel: (task: Task) => TaskProjectLabel
}

/**
 * Состояние экрана в адресе: `?tab=`, `?task=`, `?new=personal`.
 *
 * Три параметра, которые обязаны уживаться, поэтому все правила — в чистом
 * `lib/myTasksTabs.ts`, а здесь только их применение. Смена вкладки идёт через
 * `replace`: «назад» на этом экране уже занят закрытием карточки, а ещё
 * `TaskInlineCreate` коммитит черновик на unmount — переключение вкладки
 * браузерным «назад» превратило бы недописанную фразу в задачу.
 */
function useMyTasksPane(): MyTasksPane {
  const [searchParams, setSearchParams] = useSearchParams()
  const location = useLocation()
  const me = useMe()
  const projects = useProjects()
  const personalProjectId = me.data?.personal_project_id
  const tab = resolveMyTasksTab(searchParams, { hasPersonal: !!personalProjectId })

  const setParam = (mutate: (next: URLSearchParams) => void, replace: boolean) => {
    const next = new URLSearchParams(searchParams)
    mutate(next)
    setSearchParams(next, { replace })
  }

  // id проекта открытой задачи: нужен drawer'у как фолбэк на время загрузки.
  // Берём из `history.state` — строка, по которой кликнули, его знает, а при
  // холодном заходе по ссылке не знает никто, и фолбэк остаётся пустым.
  const navState = location.state as { taskProjectId?: string } | null

  return {
    tab,
    setTab: (next) => setSearchParams(setMyTasksTab(searchParams, next), { replace: true }),
    personalProjectId: personalProjectId ?? undefined,
    openTaskId: searchParams.get('task'),
    openTaskProjectId: navState?.taskProjectId ?? null,
    openTask: (task) => {
      const next = new URLSearchParams(searchParams)
      next.set('task', task.id)
      setSearchParams(next, { state: { taskProjectId: task.project_id } })
    },
    openTaskById: (taskId) => setParam((next) => next.set('task', taskId), false),
    closeTask: () => setParam((next) => next.delete('task'), true),
    focusCreate: searchParams.get('new') === 'personal',
    // Снять `new` и поставить `tab=personal` ОДНИМ движением: иначе вкладка
    // отскочит на дефолт сразу после того, как человек попросил создать
    // личную задачу (ссылка из FAB приходит без `?tab=`).
    clearFocusCreate: () =>
      setSearchParams(clearNewPersonalParams(searchParams), { replace: true }),
    projectLabel: (task) =>
      taskProjectLabel(task, {
        namesById: new Map((projects.data ?? []).map((p) => [p.id, p.name])),
        personalProjectId,
      }),
  }
}

/**
 * Заголовок группы сроков. «Просрочено» красный — это главный факт экрана;
 * группы не сворачиваются: свернуть просрочку значит спрятать её.
 */
function GroupHeader({ label, count }: { label: string; count: number }) {
  return (
    <div className="flex items-baseline gap-2 px-[11px] pb-[7px] pt-[18px]">
      <span
        className={cn(
          'text-[13px] font-bold uppercase tracking-[0.06em]',
          label === GROUP_LABEL.overdue ? 'text-red' : 'text-text2',
        )}
      >
        {label}
      </span>
      <span className="font-mono text-[13px] text-text2">{count}</span>
    </div>
  )
}

/** Данные вкладок-окон. На «Личных» и «Назначенных мной» запрос не нужен. */
function useWindowTasks(tab: MyTasksTab) {
  const enabled = isDueWindowTab(tab)
  const tasks = useMyTasks(enabled ? { due_window: tab } : {})
  const toggleDoneWork = useToggleDone('')
  // Внутри дня — «весь день», потом по времени (0061): сервер сортирует по
  // мгновению, и срок без времени (условный полдень) вставал между 11:00 и 13:00.
  const sorted = useMemo(() => [...(tasks.data ?? [])].sort(compareDue), [tasks.data])
  return { tasks, sorted, enabled, toggleDoneWork }
}

function DesktopMyTasks({ pane }: { pane: MyTasksPane }) {
  const { tab } = pane
  const { tasks, sorted } = useWindowTasks(tab)
  const groups = useMemo(() => groupTasksByDue(sorted), [sorted])
  const toggleDone = useTabToggleDone(pane)

  const row = (t: Task) => (
    <TaskRow
      key={t.id}
      task={t}
      compact
      gridColumns={MY_TASKS_GRID.columns}
      // Проект — чипом-ссылкой под заголовком, рядом с колонкой, как на
      // телефоне (16.09): отдельный столбец «Проект» справа владелец попросил
      // заменить этой парой — там имя стояло в 400px от задачи и читалось
      // отдельно.
      project={pane.projectLabel(t)}
      // Имя колонки чужого проекта приходит с сервера (/me/tasks): своих
      // `useStages` для него у страницы нет.
      stage={t.stage_name}
      selected={pane.openTaskId === t.id}
      onClick={() => pane.openTask(t)}
      onToggleDone={() => toggleDone(t)}
    />
  )

  return (
    <div className="mx-auto flex max-w-[940px] flex-col gap-[18px] px-6 pb-10 pt-7">
      <header className="flex flex-col gap-[5px]">
        <h1 className="font-display text-[26px] font-bold leading-[1.2] text-text">
          Мои задачи
        </h1>
        <p className="text-[16px] leading-[1.5] text-text2">
          Всё, что назначено на вас, и ваши личные дела — в одном месте.
        </p>
      </header>

      <nav className="flex gap-0.5 overflow-x-auto border-b border-hair">
        {MY_TASKS_TABS.map(({ key, label }) => (
          <button
            key={key}
            type="button"
            onClick={() => pane.setTab(key)}
            aria-current={tab === key ? 'page' : undefined}
            className={cn(
              'inline-flex h-[38px] shrink-0 items-center border-b-2 px-3 text-[15px] font-semibold transition-colors',
              tab === key
                ? 'border-amber text-text'
                : 'border-transparent text-text2 hover:text-text',
            )}
          >
            {label}
          </button>
        ))}
      </nav>

      {tab === 'personal' && (
        <PersonalTaskList
          variant="desktop"
          onOpenTask={pane.openTask}
          selectedTaskId={pane.openTaskId}
          focusCreate={pane.focusCreate}
          onFocusHandled={pane.clearFocusCreate}
        />
      )}

      {tab === 'assigned' && (
        <AssignedByMeList
          variant="desktop"
          onOpenTask={pane.openTask}
          selectedTaskId={pane.openTaskId}
          projectLabel={pane.projectLabel}
        />
      )}

      {isDueWindowTab(tab) && (
        <>
          {tasks.isLoading && <TaskListSkeleton />}
          {tasks.isError && (
            <QueryError
              error={tasks.error}
              onRetry={() => void tasks.refetch()}
              title="Не удалось загрузить задачи"
            />
          )}
          {tasks.data && tasks.data.length === 0 && (
            <TaskEmptyState
              title={myTasksEmptyText(tab)}
              text="Новые задачи появятся здесь."
            />
          )}
          {tasks.data && tasks.data.length > 0 && (
            <div className="flex flex-col">
              <TaskListHeader
                gridColumns={MY_TASKS_GRID.columns}
                fieldNames={[]}
                compact
              />
              {isGroupedTab(tab)
                ? groups.map(
                    (g) =>
                      g.items.length > 0 && (
                        <section key={g.key}>
                          <GroupHeader
                            label={GROUP_LABEL[g.key]}
                            count={g.items.length}
                          />
                          {g.items.map(row)}
                        </section>
                      ),
                  )
                : sorted.map(row)}
            </div>
          )}
        </>
      )}
    </div>
  )
}

/**
 * Галочка «готово» с диспетчеризацией по проекту задачи.
 *
 * `useToggleDone(projectId)` патчит кэш `['tasks', projectId]`, и один хук на
 * весь экран означал бы, что галочка, поставленная на «Все», не долетает до
 * вкладки «Личные» (та живёт на `['tasks', personalId]`) — и наоборот.
 */
function useTabToggleDone(pane: MyTasksPane) {
  const togglePersonal = useToggleDone(pane.personalProjectId ?? '')
  const toggleOther = useToggleDone('')
  return (task: Task) =>
    pane.personalProjectId && task.project_id === pane.personalProjectId
      ? togglePersonal(task)
      : toggleOther(task)
}

function MobileMyTasks({ pane }: { pane: MyTasksPane }) {
  const { tab } = pane
  const { tasks, sorted } = useWindowTasks(tab)
  const groups = useMemo(() => groupTasksByDue(sorted), [sorted])
  const toggleDone = useTabToggleDone(pane)

  // Скроллим в начало при смене вкладки: с «Все» (десятки строк) на «Личные»
  // (одна-две) человек иначе оказывается в конце короткого списка.
  useEffect(() => {
    window.scrollTo({ top: 0 })
  }, [tab])

  const row = (t: Task) => (
    <MobileTaskRow
      key={t.id}
      task={t}
      stage={t.stage_name}
      project={pane.projectLabel(t)}
      selected={pane.openTaskId === t.id}
      onClick={() => pane.openTask(t)}
      onToggleDone={() => toggleDone(t)}
    />
  )

  return (
    <>
      <MobilePageHeader title="Мои задачи" />

      {tab === 'personal' && (
        <PersonalTaskList
          variant="mobile"
          onOpenTask={pane.openTask}
          selectedTaskId={pane.openTaskId}
          focusCreate={pane.focusCreate}
          onFocusHandled={pane.clearFocusCreate}
        />
      )}

      {tab === 'assigned' && (
        <AssignedByMeList
          variant="mobile"
          onOpenTask={pane.openTask}
          selectedTaskId={pane.openTaskId}
          projectLabel={pane.projectLabel}
        />
      )}

      {isDueWindowTab(tab) && (
        <>
          {tasks.isLoading && <TaskListSkeleton compact />}
          {tasks.isError && (
            <QueryError
              error={tasks.error}
              onRetry={() => void tasks.refetch()}
              title="Не удалось загрузить задачи"
              className="m-4"
            />
          )}
          {tasks.data && tasks.data.length === 0 && (
            <TaskEmptyState
              title={myTasksEmptyText(tab)}
              text="Новые задачи появятся здесь."
            />
          )}
          {tasks.data &&
            tasks.data.length > 0 &&
            (isGroupedTab(tab)
              ? groups.map(
                  (g) =>
                    g.items.length > 0 && (
                      <section key={g.key}>
                        <GroupHeader label={GROUP_LABEL[g.key]} count={g.items.length} />
                        {g.items.map(row)}
                      </section>
                    ),
                )
              : sorted.map(row))}
        </>
      )}

      {/* Плавающая пилюля, а не полоса вкладок: шесть подписей дают ~560px при
          экране 390. Тот же компонент, что на странице проекта, — и он же
          лечит прежнюю беду, когда фильтр стоял в потоке и уезжал вверх на
          длинном списке. */}
      <MobileViewControlBar
        options={MY_TASKS_TABS}
        value={tab}
        onChange={pane.setTab}
      />

      <FloatingActionButton />
    </>
  )
}
