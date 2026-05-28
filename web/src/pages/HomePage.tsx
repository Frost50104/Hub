import { useState } from 'react'
import { Link } from 'react-router-dom'

import { PushPermissionPrompt } from '@/components/PushPermissionPrompt'
import { TaskRow } from '@/components/task/TaskRow'
import { useMe } from '@/hooks/useMe'
import { useMyTasks, type DueWindow } from '@/hooks/useMyTasks'
import { useProjects } from '@/hooks/useProjects'
import { useUpdateTask } from '@/hooks/useTasks'
import { cn } from '@/lib/cn'
import { type Project } from '@/lib/projects'

function greeting(): string {
  const h = new Date().getHours()
  if (h < 6) return 'Доброй ночи'
  if (h < 12) return 'Доброе утро'
  if (h < 18) return 'Добрый день'
  return 'Добрый вечер'
}

const TASK_TABS: { key: DueWindow; label: string }[] = [
  { key: 'upcoming', label: 'Предстоит' },
  { key: 'overdue', label: 'Просрочено' },
  { key: 'today', label: 'Сегодня' },
]

function projectColor(p: Project): string {
  let hash = 0
  for (const ch of p.id) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0
  const palette = [
    'bg-amber/30 text-amber',
    'bg-green/20 text-green',
    'bg-blue-500/20 text-blue-300',
    'bg-pink-500/20 text-pink-300',
    'bg-purple-500/20 text-purple-300',
    'bg-cyan-500/20 text-cyan-300',
  ]
  return palette[hash % palette.length] ?? palette[0]!
}

export function HomePage() {
  const me = useMe()
  const projects = useProjects()
  const [taskTab, setTaskTab] = useState<DueWindow>('upcoming')
  const myTasks = useMyTasks({ due_window: taskTab })
  // updateTask isn't tied to a single project for me-tasks invalidation;
  // pass empty string — invalidate global ['tasks'] still works thanks to
  // queryKey prefix.
  const update = useUpdateTask('')

  const firstName = me.data?.full_name?.split(/\s+/)[0] ?? ''
  const today = new Date().toLocaleDateString('ru-RU', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
  })

  const recent = (projects.data ?? []).slice(0, 4)
  const completedCount =
    (myTasks.data ?? []).filter((t) => t.status === 'done').length
  const totalCount = myTasks.data?.length ?? 0

  return (
    <div className="space-y-8 p-6">
      <PushPermissionPrompt />
      <header className="space-y-2 text-center">
        <p className="text-sm capitalize text-text2">{today}</p>
        <h1 className="font-display text-3xl font-semibold">
          {greeting()}, {firstName || 'друг'}
        </h1>
        <p className="text-xs text-text3">
          {totalCount} {totalCount === 1 ? 'задача' : 'задач'} • выполнено {completedCount}
        </p>
      </header>

      <div className="mx-auto grid max-w-5xl grid-cols-1 gap-4 lg:grid-cols-2">
        {/* My Tasks widget */}
        <section className="glass space-y-3 p-5">
          <div className="flex items-center justify-between">
            <h2 className="font-display text-base font-semibold">Мои задачи</h2>
            <Link to="/my" className="text-xs text-amber hover:underline">
              Все →
            </Link>
          </div>
          <div className="flex gap-1 border-b border-glass-border">
            {TASK_TABS.map(({ key, label }) => (
              <button
                key={key}
                onClick={() => setTaskTab(key)}
                className={cn(
                  '-mb-px border-b-2 px-2 py-1 text-xs font-medium transition-colors',
                  taskTab === key
                    ? 'border-amber text-text'
                    : 'border-transparent text-text2 hover:text-text',
                )}
              >
                {label}
              </button>
            ))}
          </div>
          <div>
            {myTasks.isLoading && (
              <p className="px-2 py-2 text-xs text-text2">Загружаем…</p>
            )}
            {myTasks.data && myTasks.data.length === 0 && (
              <p className="px-2 py-3 text-xs text-text3">
                {taskTab === 'overdue'
                  ? 'Нет просроченных — отлично!'
                  : taskTab === 'today'
                    ? 'На сегодня задач нет.'
                    : 'Свободно — задач в ближайшее время нет.'}
              </p>
            )}
            {myTasks.data?.slice(0, 6).map((t) => (
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
            ))}
          </div>
        </section>

        {/* Recent projects */}
        <section className="glass space-y-3 p-5">
          <div className="flex items-center justify-between">
            <h2 className="font-display text-base font-semibold">Недавние проекты</h2>
            <Link to="/projects" className="text-xs text-amber hover:underline">
              Все →
            </Link>
          </div>
          {recent.length === 0 ? (
            <p className="px-2 py-3 text-xs text-text3">
              Проектов пока нет — создайте первый из левого меню.
            </p>
          ) : (
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {recent.map((p) => (
                <Link
                  key={p.id}
                  to={`/projects/${p.id}`}
                  className="flex items-center gap-3 rounded-lg border border-glass-border p-3 transition-colors hover:bg-surface"
                >
                  <span
                    className={cn(
                      'flex h-9 w-9 shrink-0 items-center justify-center rounded-lg font-display text-sm font-black uppercase',
                      projectColor(p),
                    )}
                  >
                    {p.key.slice(0, 2)}
                  </span>
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-text">{p.name}</p>
                    <p className="truncate text-xs text-text3">{p.key}</p>
                  </div>
                </Link>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  )
}
