import { ChevronDown, LayoutGrid } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import { FloatingActionButton } from '@/components/layout/FloatingActionButton'
import { MobilePageHeader } from '@/components/layout/MobilePageHeader'
import { PushPermissionPrompt } from '@/components/PushPermissionPrompt'
import { QueryError } from '@/components/QueryError'
import { SkeletonRows } from '@/components/ui/Skeleton'
import { MobileTaskRow } from '@/components/task/MobileTaskRow'
import { TaskRow } from '@/components/task/TaskRow'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { useMe } from '@/hooks/useMe'
import { useMyTasks, type DueWindow } from '@/hooks/useMyTasks'
import { useProjects } from '@/hooks/useProjects'
import { useToggleDone } from '@/hooks/useTasks'
import { cn } from '@/lib/cn'
import { capitalizeFirst } from '@/lib/dates'
import { type Project } from '@/lib/projects'

function greeting(): string {
  const h = new Date().getHours()
  if (h < 6) return 'Доброй ночи'
  if (h < 12) return 'Доброе утро'
  if (h < 18) return 'Добрый день'
  return 'Добрый вечер'
}

function todayLabel(): string {
  return new Date()
    .toLocaleDateString('ru-RU', {
      weekday: 'short',
      day: 'numeric',
      month: 'long',
    })
    .replace('.', '')
}

const PROJECT_PALETTE: { bg: string; text: string }[] = [
  { bg: 'bg-amber/20', text: 'text-amber' },
  { bg: 'bg-green/20', text: 'text-green' },
  { bg: 'bg-blue-500/20', text: 'text-blue-500' },
  { bg: 'bg-pink-500/20', text: 'text-pink-500' },
  { bg: 'bg-purple-500/20', text: 'text-purple-500' },
  { bg: 'bg-cyan-500/20', text: 'text-cyan-500' },
]

function projectColor(p: Project): { bg: string; text: string } {
  let hash = 0
  for (const ch of p.id) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0
  return PROJECT_PALETTE[hash % PROJECT_PALETTE.length] ?? PROJECT_PALETTE[0]!
}

const TASK_TABS: { key: DueWindow; label: string }[] = [
  { key: 'upcoming', label: 'Предстоит' },
  { key: 'overdue', label: 'Просрочено' },
  { key: 'today', label: 'Сегодня' },
]

export function HomePage() {
  const isDesktop = useIsDesktop()
  return isDesktop ? <DesktopHome /> : <MobileHome />
}

// ─── Mobile (Asana-style) ───────────────────────────────────────────────────

function MobileHome() {
  const me = useMe()
  const projects = useProjects()
  const recentTasks = useMyTasks({ due_window: 'upcoming' })
  const toggleDone = useToggleDone('')

  const firstName = me.data?.full_name?.split(/\s+/)[0] ?? ''
  const recentProjects = (projects.data ?? []).slice(0, 6)
  const tasks = (recentTasks.data ?? []).slice(0, 5)
  const projectsById = new Map((projects.data ?? []).map((p) => [p.id, p]))

  return (
    <>
      <MobilePageHeader
        eyebrow={todayLabel()}
        title={`${greeting()}, ${firstName || 'друг'}`}
        trailing={
          <button
            type="button"
            className="inline-flex h-9 w-9 items-center justify-center rounded-md text-text3 hover:bg-glass hover:text-text"
            aria-label="Виджеты"
          >
            <LayoutGrid className="h-5 w-5" />
          </button>
        }
      />

      <div className="space-y-4 px-3">
        <PushPermissionPrompt />

        <Section title="Недавние">
          {recentTasks.isLoading ? (
            <SkeletonRows rows={3} className="p-4" />
          ) : recentTasks.isError ? (
            <QueryError
              error={recentTasks.error}
              onRetry={() => void recentTasks.refetch()}
              title="Не удалось загрузить задачи"
              className="m-3"
            />
          ) : tasks.length === 0 ? (
            <p className="px-4 py-6 text-center text-sm text-text3">
              Все задачи разобраны.
            </p>
          ) : (
            <div>
              {tasks.map((t) => (
                <MobileTaskRow
                  key={t.id}
                  task={t}
                  subtitle={
                    t.project_id
                      ? projectsById.get(t.project_id)?.name
                      : undefined
                  }
                  onToggleDone={() => toggleDone(t)}
                />
              ))}
            </div>
          )}
        </Section>

        <Section
          title="Проекты"
          trailing={
            <Link
              to="/projects"
              className="flex items-center gap-0.5 text-xs text-text3 hover:text-text"
            >
              Все <ChevronDown className="-rotate-90 h-3 w-3" />
            </Link>
          }
        >
          {projects.isError ? (
            <QueryError
              error={projects.error}
              onRetry={() => void projects.refetch()}
              title="Не удалось загрузить проекты"
              className="m-3"
            />
          ) : recentProjects.length === 0 ? (
            <p className="px-4 py-6 text-center text-sm text-text3">
              Проектов ещё нет. Нажмите «+» внизу, чтобы создать первый.
            </p>
          ) : (
            <ul>
              {recentProjects.map((p) => {
                const c = projectColor(p)
                return (
                  <li key={p.id}>
                    <Link
                      to={`/projects/${p.id}`}
                      className="flex items-center gap-3 px-4 py-3 active:bg-glass"
                    >
                      <span
                        className={cn(
                          'flex h-9 w-9 shrink-0 items-center justify-center rounded-lg font-display text-sm font-black uppercase',
                          c.bg,
                          c.text,
                        )}
                      >
                        {p.key.slice(0, 2)}
                      </span>
                      <span className="truncate text-[15px] text-text">
                        {p.name}
                      </span>
                    </Link>
                  </li>
                )
              })}
            </ul>
          )}
        </Section>
      </div>

      <FloatingActionButton />
    </>
  )
}

function Section({
  title,
  trailing,
  children,
}: {
  title: string
  trailing?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <section className="rounded-2xl border border-glass-border bg-bg-alt/60 shadow-sm">
      <header className="flex items-center justify-between px-4 pb-1 pt-3">
        <h2 className="text-[15px] font-semibold text-text">{title}</h2>
        {trailing}
      </header>
      {children}
    </section>
  )
}

// ─── Desktop (preserved) ────────────────────────────────────────────────────

function DesktopHome() {
  const me = useMe()
  const projects = useProjects()
  const [taskTab, setTaskTab] = useState<DueWindow>('upcoming')
  const myTasks = useMyTasks({ due_window: taskTab })
  const toggleDone = useToggleDone('')

  const firstName = me.data?.full_name?.split(/\s+/)[0] ?? ''
  const today = capitalizeFirst(
    new Date().toLocaleDateString('ru-RU', {
      weekday: 'long',
      day: 'numeric',
      month: 'long',
    }),
  )

  const recent = (projects.data ?? []).slice(0, 4)
  const completedCount =
    (myTasks.data ?? []).filter((t) => t.status === 'done').length
  const totalCount = myTasks.data?.length ?? 0

  return (
    <div className="space-y-8 p-6">
      <PushPermissionPrompt />
      <header className="space-y-2 text-center">
        <p className="text-sm text-text2">{today}</p>
        <h1 className="font-display text-3xl font-semibold">
          {greeting()}, {firstName || 'друг'}
        </h1>
        <p className="text-xs text-text3">
          {totalCount} {totalCount === 1 ? 'задача' : 'задач'} • выполнено{' '}
          {completedCount}
        </p>
      </header>

      <div className="mx-auto grid max-w-5xl grid-cols-1 gap-4 lg:grid-cols-2">
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
            {myTasks.isLoading && <SkeletonRows rows={4} className="py-2" />}
            {myTasks.isError && (
              <QueryError
                error={myTasks.error}
                onRetry={() => void myTasks.refetch()}
                title="Не удалось загрузить задачи"
              />
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
              <TaskRow key={t.id} task={t} onToggleDone={() => toggleDone(t)} />
            ))}
          </div>
        </section>

        <section className="glass space-y-3 p-5">
          <div className="flex items-center justify-between">
            <h2 className="font-display text-base font-semibold">Недавние проекты</h2>
            <Link to="/projects" className="text-xs text-amber hover:underline">
              Все →
            </Link>
          </div>
          {projects.isError ? (
            <QueryError
              error={projects.error}
              onRetry={() => void projects.refetch()}
              title="Не удалось загрузить проекты"
            />
          ) : recent.length === 0 ? (
            <p className="px-2 py-3 text-xs text-text3">
              Проектов пока нет — создайте первый из левого меню.
            </p>
          ) : (
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {recent.map((p) => {
                const c = projectColor(p)
                return (
                  <Link
                    key={p.id}
                    to={`/projects/${p.id}`}
                    className="flex items-center gap-3 rounded-lg border border-glass-border p-3 transition-colors hover:bg-surface"
                  >
                    <span
                      className={cn(
                        'flex h-9 w-9 shrink-0 items-center justify-center rounded-lg font-display text-sm font-black uppercase',
                        c.bg,
                        c.text,
                      )}
                    >
                      {p.key.slice(0, 2)}
                    </span>
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-text">{p.name}</p>
                      <p className="truncate text-xs text-text3">{p.key}</p>
                    </div>
                  </Link>
                )
              })}
            </div>
          )}
        </section>
      </div>
    </div>
  )
}
