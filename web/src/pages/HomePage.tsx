import { LayoutGrid } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { FloatingActionButton } from '@/components/layout/FloatingActionButton'
import { MobilePageHeader } from '@/components/layout/MobilePageHeader'
import { SpaceSwitcher } from '@/components/layout/SpaceSwitcher'
import { ProjectKeyChip, projectMeta } from '@/components/project/ProjectKeyChip'
import { PushPermissionPrompt } from '@/components/PushPermissionPrompt'
import { QueryError } from '@/components/QueryError'
import { SkeletonRows } from '@/components/ui/Skeleton'
import { MobileTaskRow } from '@/components/task/MobileTaskRow'
import { CompactTaskRow } from '@/components/task/CompactTaskRow'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { useMe } from '@/hooks/useMe'
import { useMyTasks, type DueWindow } from '@/hooks/useMyTasks'
import { useProjects } from '@/hooks/useProjects'
import { useToggleDone } from '@/hooks/useTasks'
import { cn } from '@/lib/cn'
import { capitalizeFirst } from '@/lib/dates'
import { NBSP, plural } from '@/lib/typography'

function greeting(): string {
  const h = new Date().getHours()
  if (h < 6) return 'Доброй ночи'
  if (h < 12) return 'Доброе утро'
  if (h < 18) return 'Добрый день'
  return 'Добрый вечер'
}

function todayLabel(): string {
  return new Date()
    .toLocaleDateString('ru-RU', { weekday: 'short', day: 'numeric', month: 'long' })
    .replace('.', '')
}

const TASK_TABS: { key: DueWindow; label: string }[] = [
  { key: 'upcoming', label: 'Предстоит' },
  { key: 'overdue', label: 'Просрочено' },
  { key: 'today', label: 'Сегодня' },
]

function emptyText(tab: DueWindow): string {
  if (tab === 'overdue') return 'Нет просроченных — отлично!'
  if (tab === 'today') return 'На сегодня задач нет.'
  return 'Свободно — задач в ближайшее время нет.'
}

export function HomePage() {
  const isDesktop = useIsDesktop()
  return isDesktop ? <DesktopHome /> : <MobileHome />
}

function useHomeData(tab: DueWindow) {
  const me = useMe()
  const projects = useProjects()
  const myTasks = useMyTasks({ due_window: tab })
  const toggleDone = useToggleDone('')
  const navigate = useNavigate()
  const projectsById = useMemo(
    () => new Map((projects.data ?? []).map((p) => [p.id, p])),
    [projects.data],
  )
  return {
    // Перенос строки в приветствии обязан идти по запятой: на 390px «Добрый
    // день, Ирина» ломалось после «Добрый» и оставляло «день, Ирина».
    greetingText: `${greeting().replace(' ', NBSP)}, ${me.data?.full_name?.split(/\s+/)[0] ?? 'друг'}`,
    projects,
    myTasks,
    toggleDone,
    openTask: (id: string, projectId: string) =>
      navigate(`/projects/${projectId}?task=${id}`),
    projectName: (projectId: string) => projectsById.get(projectId)?.name ?? null,
  }
}

// ─── Десктоп ────────────────────────────────────────────────────────────────

function Panel({
  title,
  href,
  children,
}: {
  title: string
  href: string
  children: React.ReactNode
}) {
  return (
    <section className="flex flex-col gap-3 rounded-[14px] border border-glass-border bg-tint p-[18px]">
      <div className="flex items-center justify-between gap-3">
        <h2 className="font-display text-[17px] font-bold leading-[1.25] text-text">
          {title}
        </h2>
        {/* Краска --text, не амбер: амбер светлый в обеих темах и на светлом
            полотне даёт 1,73:1. Он остаётся заливкам и активным индикаторам. */}
        <Link to={href} className="text-[14px] font-semibold text-text hover:underline">
          Все →
        </Link>
      </div>
      {children}
    </section>
  )
}

function DesktopHome() {
  const [taskTab, setTaskTab] = useState<DueWindow>('upcoming')
  const { greetingText, projects, myTasks, toggleDone, openTask, projectName } =
    useHomeData(taskTab)

  const today = capitalizeFirst(
    new Date().toLocaleDateString('ru-RU', {
      weekday: 'long',
      day: 'numeric',
      month: 'long',
    }),
  )
  const recent = (projects.data ?? []).slice(0, 6)
  const total = myTasks.data?.length ?? 0
  const done = (myTasks.data ?? []).filter((t) => t.status === 'done').length

  return (
    <div className="mx-auto flex max-w-[1080px] flex-col gap-[26px] px-6 pb-10 pt-8">
      <PushPermissionPrompt />
      <header className="flex flex-col gap-1.5 text-center">
        <p className="text-[15px] text-text2">{today}</p>
        <h1 className="font-display text-[30px] font-bold leading-[1.18] text-text">
          {greetingText}
        </h1>
        <p className="text-[15px] text-text2">
          {plural(total, 'задача', 'задачи', 'задач')} · выполнено {done}
        </p>
      </header>

      <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-2">
        <Panel title="Мои задачи" href="/my">
          <nav className="flex gap-0.5 border-b border-hair">
            {TASK_TABS.map(({ key, label }) => (
              <button
                key={key}
                type="button"
                onClick={() => setTaskTab(key)}
                aria-current={taskTab === key ? 'page' : undefined}
                className={cn(
                  'inline-flex h-[38px] items-center border-b-2 px-3 text-[15px] font-semibold transition-colors',
                  taskTab === key
                    ? 'border-amber text-text'
                    : 'border-transparent text-text2 hover:text-text',
                )}
              >
                {label}
              </button>
            ))}
          </nav>
          <div className="flex flex-col">
            {myTasks.isLoading && <SkeletonRows rows={4} className="py-2" />}
            {myTasks.isError && (
              <QueryError
                error={myTasks.error}
                onRetry={() => void myTasks.refetch()}
                title="Не удалось загрузить задачи"
              />
            )}
            {myTasks.data && myTasks.data.length === 0 && (
              <p className="px-1 py-4 text-[15px] text-text2">{emptyText(taskTab)}</p>
            )}
            {myTasks.data?.slice(0, 5).map((t) => (
              <CompactTaskRow
                key={t.id}
                task={t}
                subtitle={projectName(t.project_id)}
                onClick={() => openTask(t.id, t.project_id)}
                onToggleDone={() => toggleDone(t)}
              />
            ))}
          </div>
        </Panel>

        <Panel title="Недавние проекты" href="/projects">
          {/* Порядок веток: грузим → ошибка → пусто → список. Без первой ветки
              экран во время загрузки утверждал «Проектов ещё нет». */}
          {projects.isLoading ? (
            <SkeletonRows rows={4} className="py-2" />
          ) : projects.isError ? (
            <QueryError
              error={projects.error}
              onRetry={() => void projects.refetch()}
              title="Не удалось загрузить проекты"
            />
          ) : recent.length === 0 ? (
            <p className="px-1 py-4 text-[15px] text-text2">
              Проектов пока нет — создайте первый из левого меню.
            </p>
          ) : (
            <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
              {recent.map((p) => (
                <Link
                  key={p.id}
                  to={`/projects/${p.id}`}
                  className="flex min-h-[60px] items-center gap-[11px] rounded-xl border border-glass-border px-3 py-2.5 transition-colors hover:bg-surface"
                >
                  <ProjectKeyChip project={p} />
                  <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <span className="truncate text-[16px] font-medium leading-[1.3] text-text">
                      {p.name}
                    </span>
                    <span className="truncate text-[13px] leading-[1.35] text-text2">
                      {projectMeta(p) ?? p.key}
                    </span>
                  </span>
                </Link>
              ))}
            </div>
          )}
        </Panel>
      </div>
    </div>
  )
}

// ─── Мобильный ──────────────────────────────────────────────────────────────

function MobilePanel({
  title,
  href,
  children,
}: {
  title: string
  href: string
  children: React.ReactNode
}) {
  return (
    <section className="overflow-hidden rounded-2xl border border-glass-border bg-tint">
      <header className="flex items-center justify-between gap-2 px-4 pb-1 pt-3.5">
        <h2 className="text-[17px] font-semibold leading-[1.3] text-text">{title}</h2>
        <Link
          to={href}
          className="-mx-2.5 -my-[11px] inline-flex min-h-11 items-center px-2.5 text-[15px] font-semibold text-text"
        >
          Все →
        </Link>
      </header>
      {children}
    </section>
  )
}

function MobileHome() {
  const { greetingText, projects, myTasks, toggleDone, openTask, projectName } =
    useHomeData('upcoming')
  const recentProjects = (projects.data ?? []).slice(0, 6)
  const tasks = (myTasks.data ?? []).slice(0, 5)

  return (
    <>
      <MobilePageHeader
        topSlot={<SpaceSwitcher />}
        eyebrow={todayLabel()}
        title={greetingText}
        trailing={
          <button
            type="button"
            className="inline-flex h-11 w-11 items-center justify-center rounded-[10px] text-text2 hover:bg-glass hover:text-text"
            aria-label="Виджеты"
          >
            <LayoutGrid className="h-5 w-5" />
          </button>
        }
      />

      <div className="flex flex-col gap-3.5 px-3 py-3.5">
        <PushPermissionPrompt />

        <MobilePanel title="Недавние" href="/my">
          {myTasks.isLoading ? (
            <SkeletonRows rows={3} className="p-4" />
          ) : myTasks.isError ? (
            <QueryError
              error={myTasks.error}
              onRetry={() => void myTasks.refetch()}
              title="Не удалось загрузить задачи"
              className="m-3"
            />
          ) : tasks.length === 0 ? (
            <p className="px-4 py-6 text-center text-[15px] text-text2">
              Все задачи разобраны.
            </p>
          ) : (
            <div>
              {tasks.map((t) => (
                <MobileTaskRow
                  key={t.id}
                  task={t}
                  context="fallback"
                  fallback={projectName(t.project_id)}
                  onClick={() => openTask(t.id, t.project_id)}
                  onToggleDone={() => toggleDone(t)}
                />
              ))}
            </div>
          )}
        </MobilePanel>

        <MobilePanel title="Проекты" href="/projects">
          {projects.isLoading ? (
            <SkeletonRows rows={3} className="p-4" />
          ) : projects.isError ? (
            <QueryError
              error={projects.error}
              onRetry={() => void projects.refetch()}
              title="Не удалось загрузить проекты"
              className="m-3"
            />
          ) : recentProjects.length === 0 ? (
            <p className="px-4 py-6 text-center text-[15px] text-text2">
              Проектов ещё нет. Нажмите «+» внизу, чтобы создать первый.
            </p>
          ) : (
            <ul className="pb-1.5">
              {recentProjects.map((p) => (
                <li key={p.id}>
                  <Link
                    to={`/projects/${p.id}`}
                    className="flex min-h-14 items-center gap-3 px-4 py-2 active:bg-glass"
                  >
                    <ProjectKeyChip project={p} />
                    <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                      <span className="truncate text-[16px] font-medium leading-[1.3] text-text">
                        {p.name}
                      </span>
                      <span className="truncate text-[13px] leading-[1.35] text-text2">
                        {projectMeta(p) ?? p.key}
                      </span>
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </MobilePanel>
      </div>

      <FloatingActionButton />
    </>
  )
}
