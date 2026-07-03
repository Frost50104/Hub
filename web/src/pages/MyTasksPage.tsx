import { Filter } from 'lucide-react'
import { useMemo, useState } from 'react'

import { FloatingActionButton } from '@/components/layout/FloatingActionButton'
import { MobilePageHeader } from '@/components/layout/MobilePageHeader'
import { QueryError } from '@/components/QueryError'
import { MobileTaskRow } from '@/components/task/MobileTaskRow'
import { SkeletonRows } from '@/components/ui/Skeleton'
import { TaskRow } from '@/components/task/TaskRow'
import {
  BottomSheet,
  BottomSheetItem,
} from '@/components/ui/BottomSheet'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { useMyTasks, type DueWindow } from '@/hooks/useMyTasks'
import { useProjects } from '@/hooks/useProjects'
import { useUpdateTask } from '@/hooks/useTasks'
import { cn } from '@/lib/cn'
import { type Task } from '@/lib/tasks'

const TABS: { key: DueWindow; label: string }[] = [
  { key: 'upcoming', label: 'Предстоит' },
  { key: 'overdue', label: 'Просрочено' },
  { key: 'today', label: 'Сегодня' },
  { key: 'all', label: 'Все' },
]

// ─── Группировка «Все» по срокам (как секции My Tasks в Asana) ──────────────

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

function GroupedTaskList({
  tasks,
  renderTask,
}: {
  tasks: Task[]
  renderTask: (t: Task) => React.ReactNode
}) {
  const groups = useMemo(() => groupTasksByDue(tasks), [tasks])
  return (
    <div className="space-y-4">
      {groups.map(
        (g) =>
          g.items.length > 0 && (
            <section key={g.key}>
              <h2
                className={cn(
                  'flex items-baseline gap-2 px-1 pb-1 text-[11px] font-semibold uppercase tracking-wider',
                  g.key === 'overdue' ? 'text-red' : 'text-text3',
                )}
              >
                {GROUP_LABEL[g.key]}
                <span className="font-normal">{g.items.length}</span>
              </h2>
              <div>{g.items.map(renderTask)}</div>
            </section>
          ),
      )}
    </div>
  )
}

export function MyTasksPage() {
  const isDesktop = useIsDesktop()
  return isDesktop ? <DesktopMyTasks /> : <MobileMyTasks />
}

function MobileMyTasks() {
  const [tab, setTab] = useState<DueWindow>('upcoming')
  const [pickerOpen, setPickerOpen] = useState(false)
  const tasks = useMyTasks({ due_window: tab })
  const projects = useProjects()
  const update = useUpdateTask('')
  const projectsById = new Map((projects.data ?? []).map((p) => [p.id, p]))

  const current = TABS.find((t) => t.key === tab)!

  return (
    <>
      <MobilePageHeader title="Мои задачи" withOverflowMenu />

      <div className="border-y border-glass-border bg-bg-alt/80 px-4 py-2">
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => setPickerOpen(true)}
            className="inline-flex items-center gap-1.5 rounded-full border border-glass-border bg-glass px-3 py-2 text-sm text-text active:bg-surface"
          >
            <Filter className="h-3.5 w-3.5" /> {current.label}
          </button>
        </div>
      </div>

      <div>
        {tasks.isLoading && <SkeletonRows rows={6} className="p-4" />}
        {tasks.isError && (
          <QueryError
            error={tasks.error}
            onRetry={() => void tasks.refetch()}
            title="Не удалось загрузить задачи"
            className="m-4"
          />
        )}
        {tasks.data && tasks.data.length === 0 && (
          <p className="px-4 py-10 text-center text-sm text-text3">
            {tab === 'overdue' ? 'Нет просроченных — отлично!' : 'Здесь пока пусто.'}
          </p>
        )}
        {tasks.data &&
          (tab === 'all' ? (
            <GroupedTaskList
              tasks={tasks.data}
              renderTask={(t) => (
                <MobileTaskRow
                  key={t.id}
                  task={t}
                  subtitle={
                    t.project_id ? projectsById.get(t.project_id)?.name : undefined
                  }
                  onToggleDone={() =>
                    update.mutate({
                      id: t.id,
                      status: t.status === 'done' ? 'todo' : 'done',
                    })
                  }
                />
              )}
            />
          ) : (
            tasks.data.map((t) => (
              <MobileTaskRow
                key={t.id}
                task={t}
                subtitle={
                  t.project_id ? projectsById.get(t.project_id)?.name : undefined
                }
                onToggleDone={() =>
                  update.mutate({
                    id: t.id,
                    status: t.status === 'done' ? 'todo' : 'done',
                  })
                }
              />
            ))
          ))}
      </div>

      <BottomSheet
        open={pickerOpen}
        onOpenChange={setPickerOpen}
        title="Окно дедлайнов"
      >
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

function DesktopMyTasks() {
  const [tab, setTab] = useState<DueWindow>('upcoming')
  const tasks = useMyTasks({ due_window: tab })
  const update = useUpdateTask('')

  return (
    <div className="mx-auto max-w-4xl space-y-4 p-6">
      <header>
        <h1 className="font-display text-2xl font-semibold">Мои задачи</h1>
        <p className="text-sm text-text2">
          Всё, что назначено на вас, в одном месте.
        </p>
      </header>

      <div className="flex gap-1 border-b border-glass-border">
        {TABS.map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={cn(
              '-mb-px border-b-2 px-3 py-2 text-sm font-medium transition-colors',
              tab === key
                ? 'border-amber text-text'
                : 'border-transparent text-text2 hover:text-text',
            )}
          >
            {label}
          </button>
        ))}
      </div>

      <div>
        {tasks.isLoading && <SkeletonRows rows={6} />}
        {tasks.isError && (
          <QueryError
            error={tasks.error}
            onRetry={() => void tasks.refetch()}
            title="Не удалось загрузить задачи"
          />
        )}
        {tasks.data && tasks.data.length === 0 && (
          <p className="rounded-lg border border-glass-border p-6 text-center text-sm text-text3">
            {tab === 'overdue'
              ? 'Нет просроченных задач — отлично!'
              : 'Здесь пока пусто.'}
          </p>
        )}
        {tasks.data &&
          (tab === 'all' ? (
            <GroupedTaskList
              tasks={tasks.data}
              renderTask={(t) => (
                <TaskRow
                  key={t.id}
                  task={t}
                  onToggleDone={() =>
                    update.mutate({
                      id: t.id,
                      status: t.status === 'done' ? 'todo' : 'done',
                    })
                  }
                />
              )}
            />
          ) : (
            tasks.data.map((t) => (
              <TaskRow
                key={t.id}
                task={t}
                onToggleDone={() =>
                  update.mutate({
                    id: t.id,
                    status: t.status === 'done' ? 'todo' : 'done',
                  })
                }
              />
            ))
          ))}
      </div>
    </div>
  )
}
