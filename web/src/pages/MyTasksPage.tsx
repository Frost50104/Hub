import { ChevronDown, Filter } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'

import { FloatingActionButton } from '@/components/layout/FloatingActionButton'
import { MobilePageHeader } from '@/components/layout/MobilePageHeader'
import { QueryError } from '@/components/QueryError'
import { MobileTaskRow } from '@/components/task/MobileTaskRow'
import { PersonalTasksSection } from '@/components/task/PersonalTasksSection'
import { TaskDetailDrawer } from '@/components/task/TaskDetailDrawer'
import { TaskEmptyState, TaskListSkeleton } from '@/components/task/TaskListStates'
import { TaskListHeader } from '@/components/task/TaskListHeader'
import { TaskRow } from '@/components/task/TaskRow'
import { BottomSheet, BottomSheetItem } from '@/components/ui/BottomSheet'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { useMyTasks, type DueWindow } from '@/hooks/useMyTasks'
import { usePersonalTasks } from '@/hooks/usePersonalTasks'
import { useProjects } from '@/hooks/useProjects'
import { useToggleDone } from '@/hooks/useTasks'
import { cn } from '@/lib/cn'
import {
  resolvePersonalTaskParam,
  shouldFocusPersonalCreate,
} from '@/lib/personalTasks'
import { addDaysKey, dayKey, todayKey } from '@/lib/taskDates'
import { MY_TASKS_GRID } from '@/lib/taskGrid'
import { type Task } from '@/lib/tasks'

const TABS: { key: DueWindow; label: string }[] = [
  { key: 'upcoming', label: 'Предстоит' },
  { key: 'overdue', label: 'Просрочено' },
  { key: 'today', label: 'Сегодня' },
  { key: 'all', label: 'Все' },
]

// ─── Группировка «Все» по срокам ────────────────────────────────────────────

type GroupKey = 'overdue' | 'today' | 'week' | 'later' | 'nodate'

const GROUP_LABEL: Record<GroupKey, string> = {
  overdue: 'Просрочено',
  today: 'Сегодня',
  week: 'Ближайшая неделя',
  later: 'Позже',
  nodate: 'Без срока',
}

const GROUP_ORDER: GroupKey[] = ['overdue', 'today', 'week', 'later', 'nodate']

function groupTasksByDue(tasks: Task[]): { key: GroupKey; items: Task[] }[] {
  // Ключи дней display tz (lib/taskDates) — та же семантика, что у окон
  // сервера: день срока, а не мгновение.
  const today = todayKey()
  const weekEnd = addDaysKey(today, 7)

  const buckets = new Map<GroupKey, Task[]>(GROUP_ORDER.map((k) => [k, []]))
  for (const t of tasks) {
    let key: GroupKey
    if (!t.due_at) key = 'nodate'
    else {
      const day = dayKey(t.due_at)
      // Выполненные задачи не считаем просроченными — оставляем в своей дате.
      if (day < today && !t.done) key = 'overdue'
      else if (day <= today) key = 'today'
      else if (day <= weekEnd) key = 'week'
      else key = 'later'
    }
    buckets.get(key)!.push(t)
  }
  return GROUP_ORDER.map((key) => ({ key, items: buckets.get(key)! }))
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

export function MyTasksPage() {
  const isDesktop = useIsDesktop()
  const personal = usePersonalPane()
  return (
    <>
      {isDesktop ? (
        <DesktopMyTasks personal={personal} />
      ) : (
        <MobileMyTasks personal={personal} />
      )}
      {/* Карточка личной задачи живёт ЗДЕСЬ, а не на странице проекта:
          личного проекта по продукту «не существует», и открывать его целиком
          (вкладки, участники, «Поделиться») было бы противоречием. */}
      <TaskDetailDrawer
        taskId={personal.openTaskId}
        projectId={personal.projectId ?? ''}
        onClose={personal.closeTask}
        onOpenTask={personal.openTaskById}
      />
    </>
  )
}

interface PersonalPane {
  projectId: string | undefined
  /** id задачи, которую показывает карточка (null — карточка закрыта). */
  openTaskId: string | null
  openTask: (task: Task) => void
  openTaskById: (taskId: string) => void
  closeTask: () => void
  focusCreate: boolean
  clearFocusCreate: () => void
}

/** `?task=` и `?new=personal` в URL: deep-link, системное «назад» на телефоне
 *  и точка входа из шторки FAB. */
function usePersonalPane(): PersonalPane {
  const [searchParams, setSearchParams] = useSearchParams()
  const location = useLocation()
  const { projectId, query } = usePersonalTasks()
  const requested = searchParams.get('task')
  // Диалог создания кладёт сюда id только что заведённой личной задачи: списка
  // с ней ещё нет, и без этого карточка закрылась бы сама.
  const nav = location.state as { justCreatedTaskId?: string; at?: number } | null
  const hint =
    nav?.justCreatedTaskId && typeof nav.at === 'number'
      ? { taskId: nav.justCreatedTaskId, at: nav.at }
      : null
  const resolved = resolvePersonalTaskParam(
    requested,
    { tasks: query.data, isPending: query.isPending },
    hint,
  )

  const setParam = (mutate: (next: URLSearchParams) => void, replace: boolean) => {
    const next = new URLSearchParams(searchParams)
    mutate(next)
    setSearchParams(next, { replace })
  }

  // Чужая или несуществующая задача: карточка получила бы чужие этапы и чужой
  // can_edit — параметр вычищаем. В эффекте, а не в рендере: setSearchParams
  // во время рендера роняет предупреждение React об обновлении чужого стейта.
  const shouldDrop = resolved.kind === 'drop'
  useEffect(() => {
    if (shouldDrop) setParam((next) => next.delete('task'), true)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shouldDrop])

  return {
    projectId,
    openTaskId: resolved.kind === 'open' ? resolved.taskId : null,
    openTask: (task) => setParam((next) => next.set('task', task.id), false),
    openTaskById: (taskId) => setParam((next) => next.set('task', taskId), false),
    closeTask: () => setParam((next) => next.delete('task'), true),
    focusCreate: shouldFocusPersonalCreate(searchParams),
    clearFocusCreate: () => setParam((next) => next.delete('new'), true),
  }
}

function personalSection(personal: PersonalPane, variant: 'desktop' | 'mobile') {
  return (
    <PersonalTasksSection
      variant={variant}
      onOpenTask={personal.openTask}
      selectedTaskId={personal.openTaskId}
      focusCreate={personal.focusCreate}
      onFocusHandled={personal.clearFocusCreate}
    />
  )
}

function useMyTasksData(tab: DueWindow) {
  const tasks = useMyTasks({ due_window: tab })
  const projects = useProjects()
  const navigate = useNavigate()
  const toggleDone = useToggleDone('')
  const projectsById = useMemo(
    () => new Map((projects.data ?? []).map((p) => [p.id, p])),
    [projects.data],
  )
  return {
    tasks,
    toggleDone,
    // Карточка задачи живёт на странице проекта — deep-link (ОС 13.08: строки
    // были некликабельны, до вложений было не добраться).
    openTask: (t: Task) => navigate(`/projects/${t.project_id}?task=${t.id}`),
    // Фолбэк на project_key: задача, назначенная мне в ЧУЖОМ личном проекте,
    // в useProjects() не найдётся — личные скрыты из списка.
    projectName: (t: Task) =>
      projectsById.get(t.project_id)?.name ?? t.project_key ?? null,
  }
}

function emptyText(tab: DueWindow): string {
  if (tab === 'overdue') return 'Нет просроченных — отлично!'
  if (tab === 'today') return 'На сегодня задач нет — и просроченных тоже.'
  return 'Здесь пока пусто.'
}

function DesktopMyTasks({ personal }: { personal: PersonalPane }) {
  const [tab, setTab] = useState<DueWindow>('upcoming')
  const { tasks, toggleDone, openTask, projectName } = useMyTasksData(tab)
  const grouped = tab === 'all'
  const groups = useMemo(() => groupTasksByDue(tasks.data ?? []), [tasks.data])

  const row = (t: Task) => (
    <TaskRow
      key={t.id}
      task={t}
      compact
      gridColumns={MY_TASKS_GRID.columns}
      // Проект уже стоит колонкой справа — во второй раз в строке контекста
      // он был бы дублем. На мобильном колонок нет, там fallback остаётся.
      fallback={null}
      // Имя колонки чужого проекта приходит с сервера (/me/tasks): своих
      // `useStages` для него у страницы нет.
      stage={t.stage_name}
      cells={
        <span
          className="min-w-0 truncate pr-3.5 text-[14px] text-text2"
          title={projectName(t) ?? undefined}
        >
          {projectName(t)}
        </span>
      }
      onClick={() => openTask(t)}
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
          Всё, что назначено на вас, в одном месте.
        </p>
      </header>

      {personalSection(personal, 'desktop')}

      {/* Граница вкладок читается как «фильтр, и всё под ним — его результат»:
          секция «ЛИЧНОЕ» стоит ВЫШЕ неё и окнам дедлайнов не подчиняется. */}
      <nav className="flex gap-0.5 border-b border-hair">
        {TABS.map(({ key, label }) => (
          <button
            key={key}
            type="button"
            onClick={() => setTab(key)}
            aria-current={tab === key ? 'page' : undefined}
            className={cn(
              'inline-flex h-[38px] items-center border-b-2 px-3 text-[15px] font-semibold transition-colors',
              tab === key
                ? 'border-amber text-text'
                : 'border-transparent text-text2 hover:text-text',
            )}
          >
            {label}
          </button>
        ))}
      </nav>

      {tasks.isLoading && <TaskListSkeleton />}
      {tasks.isError && (
        <QueryError
          error={tasks.error}
          onRetry={() => void tasks.refetch()}
          title="Не удалось загрузить задачи"
        />
      )}
      {tasks.data && tasks.data.length === 0 && (
        <TaskEmptyState title={emptyText(tab)} text="Новые задачи появятся здесь." />
      )}

      {tasks.data && tasks.data.length > 0 && (
        <div className="flex flex-col">
          <TaskListHeader
            gridColumns={MY_TASKS_GRID.columns}
            fieldNames={[]}
            leadLabel="Проект"
            compact
          />
          {grouped
            ? groups.map(
                (g) =>
                  g.items.length > 0 && (
                    <section key={g.key}>
                      <GroupHeader label={GROUP_LABEL[g.key]} count={g.items.length} />
                      {g.items.map(row)}
                    </section>
                  ),
              )
            : tasks.data.map(row)}
        </div>
      )}
    </div>
  )
}

function MobileMyTasks({ personal }: { personal: PersonalPane }) {
  const [tab, setTab] = useState<DueWindow>('upcoming')
  const [pickerOpen, setPickerOpen] = useState(false)
  const { tasks, toggleDone, openTask, projectName } = useMyTasksData(tab)
  const grouped = tab === 'all'
  const groups = useMemo(() => groupTasksByDue(tasks.data ?? []), [tasks.data])
  const current = TABS.find((t) => t.key === tab)!

  const row = (t: Task) => (
    <MobileTaskRow
      key={t.id}
      task={t}
      stage={t.stage_name}
      fallback={projectName(t)}
      onClick={() => openTask(t)}
      onToggleDone={() => toggleDone(t)}
    />
  )

  return (
    <>
      <MobilePageHeader title="Мои задачи" />

      {personalSection(personal, 'mobile')}

      {/* Полоса на --tint с одной пилюлей-фильтром (иконка Filter): это
          фильтр выборки, а не вкладка — и выглядит как фильтр. */}
      <div className="border-b border-glass-border bg-tint px-4 py-2">
        <button
          type="button"
          onClick={() => setPickerOpen(true)}
          className="inline-flex min-h-11 items-center gap-2 rounded-full border border-glass-border px-4 text-[14px] font-semibold text-text active:bg-surface"
        >
          <Filter className="h-[15px] w-[15px] text-text2" strokeWidth={2} />
          {current.label}
          <ChevronDown className="h-3.5 w-3.5 text-text2" />
        </button>
      </div>

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
        <TaskEmptyState title={emptyText(tab)} text="Новые задачи появятся здесь." />
      )}
      {tasks.data &&
        tasks.data.length > 0 &&
        (grouped
          ? groups.map(
              (g) =>
                g.items.length > 0 && (
                  <section key={g.key}>
                    <GroupHeader label={GROUP_LABEL[g.key]} count={g.items.length} />
                    {g.items.map(row)}
                  </section>
                ),
            )
          : tasks.data.map(row))}

      <BottomSheet open={pickerOpen} onOpenChange={setPickerOpen} title="Окно дедлайнов">
        {TABS.map((t) => (
          <BottomSheetItem
            key={t.key}
            onClick={() => {
              setTab(t.key)
              setPickerOpen(false)
            }}
            trailing={tab === t.key ? '✓' : null}
          >
            {t.label}
          </BottomSheetItem>
        ))}
      </BottomSheet>

      <FloatingActionButton />
    </>
  )
}
