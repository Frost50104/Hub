import { LayoutGrid, Star } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { FloatingActionButton } from '@/components/layout/FloatingActionButton'
import { MobilePageHeader } from '@/components/layout/MobilePageHeader'
import { SpaceSwitcher } from '@/components/layout/SpaceSwitcher'
import { ProjectKeyChip, projectMeta } from '@/components/project/ProjectKeyChip'
import { UserStatsCard } from '@/components/home/UserStatsCard'
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
import { favoriteProjects } from '@/lib/favoriteProjects'
import { myTasksWindowFilters } from '@/lib/myTasksTabs'
import { type Project } from '@/lib/projects'
import { taskLocation } from '@/lib/taskLinks'
import { taskProjectLabel } from '@/lib/taskProjectLabel'
import { type Task } from '@/lib/tasks'
import { NBSP } from '@/lib/typography'

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

// Те же четыре окна, что на «Моих задачах»: панель — её срез, а не другой фильтр.
const TASK_TABS: { key: DueWindow; label: string }[] = [
  { key: 'upcoming', label: 'Предстоит' },
  { key: 'overdue', label: 'Просрочено' },
  { key: 'today', label: 'Сегодня' },
  { key: 'all', label: 'Все' },
]

function emptyText(tab: DueWindow): string {
  if (tab === 'overdue') return 'Нет просроченных — отлично!'
  if (tab === 'today') return 'На сегодня задач нет — и просроченных тоже.'
  if (tab === 'all') return 'Задач на вас пока нет.'
  return 'Свободно — задач в ближайшее время нет.'
}

export function HomePage() {
  const isDesktop = useIsDesktop()
  return isDesktop ? <DesktopHome /> : <MobileHome />
}

function useHomeData(tab: DueWindow) {
  const me = useMe()
  const projects = useProjects()
  // Фильтры окна — те же, что у «Моих задач» (`myTasksWindowFilters`): «Все»
  // без выполненных и с тем же ключом кэша, иначе панель и `/my` слали бы
  // два запроса одного и того же.
  const myTasks = useMyTasks(myTasksWindowFilters(tab) ?? { due_window: tab })
  const toggleDone = useToggleDone('')
  const navigate = useNavigate()
  const namesById = useMemo(
    () => new Map((projects.data ?? []).map((p) => [p.id, p.name])),
    [projects.data],
  )
  return {
    // Перенос строки в приветствии обязан идти по запятой: на 390px «Добрый
    // день, Ирина» ломалось после «Добрый» и оставляло «день, Ирина».
    greetingText: `${greeting().replace(' ', NBSP)}, ${me.data?.full_name?.split(/\s+/)[0] ?? 'друг'}`,
    projects,
    myTasks,
    toggleDone,
    // Личные задачи приезжают и сюда (16.09), а страницы личного проекта
    // больше нет — адрес считает общая `taskLocation`.
    openTask: (id: string, projectId: string) => {
      const to = taskLocation({
        taskId: id,
        projectId,
        personalProjectId: me.data?.personal_project_id,
      })
      navigate(`${to.pathname}${to.search}`)
    },
    // Подпись и адрес проекта — общие с «Моими задачами» (`taskProjectLabel`).
    // Раньше имя искалось в `GET /projects`, где личных проектов нет ни у
    // кого, и личные задачи с поручениями оставались вовсе без подписи.
    projectLabel: (t: Task) =>
      taskProjectLabel(t, { namesById, personalProjectId: me.data?.personal_project_id }),
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
  const { greetingText, projects, myTasks, toggleDone, openTask, projectLabel } =
    useHomeData(taskTab)

  const today = capitalizeFirst(
    new Date().toLocaleDateString('ru-RU', {
      weekday: 'long',
      day: 'numeric',
      month: 'long',
    }),
  )
  const recent = (projects.data ?? []).slice(0, 6)

  return (
    <div className="mx-auto flex max-w-[1080px] flex-col gap-[26px] px-6 pb-10 pt-8">
      <PushPermissionPrompt />
      <header className="flex flex-col gap-1.5 text-center">
        <p className="text-[15px] text-text2">{today}</p>
        <h1 className="font-display text-[30px] font-bold leading-[1.18] text-text">
          {greetingText}
        </h1>
      </header>

      <UserStatsCard />

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
                project={projectLabel(t)}
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
  icon,
  href,
  children,
}: {
  title: string
  /** Иконка перед заголовком (амбер-звезда у «Избранного», как в сайдбаре). */
  icon?: React.ReactNode
  /** Без адреса шапка остаётся без «Все →»: у «Избранного» показано всё, что
   *  есть, а на `/projects` группы избранного нет — ссылка вела бы в никуда.
   *  Высота шапки при этом та же: `min-h-11` с `-my-[11px]` даёт 22px, как
   *  line-height заголовка. */
  href?: string
  children: React.ReactNode
}) {
  return (
    <section className="overflow-hidden rounded-2xl border border-glass-border bg-tint">
      <header className="flex items-center justify-between gap-2 px-4 pb-1 pt-3.5">
        <h2 className="inline-flex items-center gap-1.5 text-[17px] font-semibold leading-[1.3] text-text">
          {icon}
          {title}
        </h2>
        {href && (
          <Link
            to={href}
            className="-mx-2.5 -my-[11px] inline-flex min-h-11 items-center px-2.5 text-[15px] font-semibold text-text"
          >
            Все →
          </Link>
        )}
      </header>
      {children}
    </section>
  )
}

/** Строка проекта в карточках «Избранное» и «Проекты» — одна на оба блока. */
function MobileProjectRow({ project }: { project: Project }) {
  return (
    <li>
      <Link
        to={`/projects/${project.id}`}
        className="flex min-h-14 items-center gap-3 px-4 py-2 active:bg-glass"
      >
        <ProjectKeyChip project={project} />
        <span className="flex min-w-0 flex-1 flex-col gap-0.5">
          <span className="truncate text-[16px] font-medium leading-[1.3] text-text">
            {project.name}
          </span>
          <span className="truncate text-[13px] leading-[1.35] text-text2">
            {projectMeta(project) ?? project.key}
          </span>
        </span>
      </Link>
    </li>
  )
}

function MobileHome() {
  const { greetingText, projects, myTasks, toggleDone, openTask, projectLabel } =
    useHomeData('upcoming')
  const recentProjects = (projects.data ?? []).slice(0, 6)
  // Избранное — только на телефоне: на десктопе оно живёт в сайдбаре, а
  // сайдбара ниже 1024px нет, и до 30.09 избранное на телефоне не было собрано
  // нигде. Порядок и отбор — общий с сайдбаром хелпер.
  const favorites = favoriteProjects(projects.data)
  const tasks = (myTasks.data ?? []).slice(0, 5)

  return (
    <>
      <MobilePageHeader
        topSlot={<SpaceSwitcher size="lg" />}
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

        <UserStatsCard />

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
                  context="plain"
                  project={projectLabel(t)}
                  onClick={() => openTask(t.id, t.project_id)}
                  onToggleDone={() => toggleDone(t)}
                />
              ))}
            </div>
          )}
        </MobilePanel>

        {/* Без избранных блока нет (решение владельца 30.09, прецедент
            сайдбара): у большинства сотрудников избранного нет, а постоянная
            пустая карточка сдвигала бы «Проекты» — единственный вход в
            `/projects` с телефона. Гейт `isSuccess`, а не `data`: при упавшем
            рефетче TanStack v5 держит старые данные с `isError`, и блок из
            протухшего кэша стоял бы рядом с ошибкой в «Проектах». Своих
            веток загрузки/ошибки у блока нет — их несёт «Проекты» ниже.
            Избранный проект остаётся и в «Проектах», как в сайдбаре. */}
        {projects.isSuccess && favorites.length > 0 && (
          <MobilePanel
            title="Избранное"
            icon={<Star className="h-4 w-4 fill-amber text-amber" aria-hidden />}
          >
            <ul className="pb-1.5">
              {favorites.map((p) => (
                <MobileProjectRow key={p.id} project={p} />
              ))}
            </ul>
          </MobilePanel>
        )}

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
                <MobileProjectRow key={p.id} project={p} />
              ))}
            </ul>
          )}
        </MobilePanel>
      </div>

      <FloatingActionButton />
    </>
  )
}
