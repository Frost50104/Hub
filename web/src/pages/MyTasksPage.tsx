import { ChevronDown } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { FloatingActionButton } from '@/components/layout/FloatingActionButton'
import { MobilePageHeader } from '@/components/layout/MobilePageHeader'
import { QueryError } from '@/components/QueryError'
import { MobileTaskRow } from '@/components/task/MobileTaskRow'
import { TaskEmptyState, TaskListSkeleton } from '@/components/task/TaskListStates'
import { TaskListHeader } from '@/components/task/TaskListHeader'
import { TaskRow } from '@/components/task/TaskRow'
import { BottomSheet, BottomSheetItem } from '@/components/ui/BottomSheet'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { useMyTasks, type DueWindow } from '@/hooks/useMyTasks'
import { useProjects } from '@/hooks/useProjects'
import { useToggleDone } from '@/hooks/useTasks'
import { cn } from '@/lib/cn'
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
  const now = new Date()
  const startToday = new Date(now)
  startToday.setHours(0, 0, 0, 0)
  const endToday = new Date(now)
  endToday.setHours(23, 59, 59, 999)
  const endWeek = new Date(endToday)
  endWeek.setDate(endWeek.getDate() + 7)

  const buckets = new Map<GroupKey, Task[]>(GROUP_ORDER.map((k) => [k, []]))
  for (const t of tasks) {
    let key: GroupKey
    if (!t.due_at) key = 'nodate'
    else {
      const due = new Date(t.due_at)
      // Готовые задачи не считаем просроченными — оставляем в своей дате.
      if (due < startToday && t.status !== 'done') key = 'overdue'
      else if (due <= endToday) key = 'today'
      else if (due <= endWeek) key = 'week'
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
  return isDesktop ? <DesktopMyTasks /> : <MobileMyTasks />
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
    projectName: (t: Task) => projectsById.get(t.project_id)?.name ?? null,
  }
}

function emptyText(tab: DueWindow): string {
  if (tab === 'overdue') return 'Нет просроченных — отлично!'
  if (tab === 'today') return 'На сегодня задач нет.'
  return 'Здесь пока пусто.'
}

function DesktopMyTasks() {
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

function MobileMyTasks() {
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
      fallback={projectName(t)}
      onClick={() => openTask(t)}
      onToggleDone={() => toggleDone(t)}
    />
  )

  return (
    <>
      <MobilePageHeader title="Мои задачи" withOverflowMenu />

      <div className="border-b border-hair px-4 py-2.5">
        <button
          type="button"
          onClick={() => setPickerOpen(true)}
          className="inline-flex min-h-11 items-center gap-1.5 rounded-[11px] border border-glass-border px-4 text-[14px] font-semibold text-text active:bg-surface"
        >
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
