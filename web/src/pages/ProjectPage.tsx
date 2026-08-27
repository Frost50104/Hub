import {
  Link as LinkIcon,
  Loader2,
  MoreHorizontal,
  Plus,
  Settings2,
  Star,
  Tags,
} from 'lucide-react'
import { lazy, Suspense, useMemo, useState, type ReactNode } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'

// `recharts` is ~370KB minified. Lazy-load the entire dashboard chunk so
// the main bundle stays light for users who never open this tab.
const ProjectDashboard = lazy(
  () => import('@/components/dashboard/ProjectDashboard'),
)

import { CalendarView } from '@/components/calendar/CalendarView'
import { BoardView } from '@/components/kanban/BoardView'
import { FloatingActionButton } from '@/components/layout/FloatingActionButton'
import { MobileViewControlBar } from '@/components/layout/MobileViewControlBar'
import { ColumnsMenu } from '@/components/project/ColumnsMenu'
import { CustomFieldsManager } from '@/components/project/CustomFieldsManager'
import { LabelsManager } from '@/components/project/LabelsManager'
import { MembersTab } from '@/components/project/MembersTab'
import { MobileFilterSheet } from '@/components/project/MobileFilterSheet'
import { summarizeProjectDescription } from '@/lib/projectAbout'
import { AboutTab } from '@/components/project/AboutTab'
import { ProjectKeyChip } from '@/components/project/ProjectKeyChip'
import { TaskFilterBar } from '@/components/project/TaskFilterBar'
import { Skeleton } from '@/components/ui/Skeleton'
import { ShareDialog } from '@/components/share/ShareDialog'
import { MobileTaskRow } from '@/components/task/MobileTaskRow'
import { TaskDetailDrawer } from '@/components/task/TaskDetailDrawer'
import { TaskListHeader } from '@/components/task/TaskListHeader'
import {
  TaskEmptyState,
  TaskListSkeleton,
} from '@/components/task/TaskListStates'
import { CreateTaskDialog } from '@/components/task/CreateTaskDialog'
import { ImportTasksDialog } from '@/components/task/ImportTasksDialog'
import { TaskInlineCreate } from '@/components/task/TaskInlineCreate'
import { TaskRow } from '@/components/task/TaskRow'
import { TimelineView } from '@/components/timeline/TimelineView'
import { Badge } from '@/components/ui/Badge'
import { BottomSheet, BottomSheetItem } from '@/components/ui/BottomSheet'
import { Button } from '@/components/ui/Button'
import {
  useCustomFieldDefinitions,
  useProjectCustomValues,
} from '@/hooks/useCustomFields'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import {
  useProject,
  useSetFavorite,
  useProjectMembers,
} from '@/hooks/useProjects'
import { useLabelAssignments, useLabels } from '@/hooks/useLabels'
import { useStages } from '@/hooks/useStages'
import { useTasks, useToggleDone } from '@/hooks/useTasks'
import { cn } from '@/lib/cn'
import { type Label } from '@/lib/labels'
import { type CustomFieldDefinition, type CustomFieldValue } from '@/lib/customFields'
import { formatCustomFieldValue } from '@/lib/formatCustomField'
import { PROJECT_ROLE_LABEL, type Project } from '@/lib/projects'
import {
  type NarrowableFilter,
  type TaskViewFilters,
  activeFilterCount,
  applyFiltersToSearchParams,
  describeFilters,
  filtersFromSearchParams,
  narrowableFilter,
  sinkDone,
  toListFilters,
} from '@/lib/taskFilters'
import { projectTaskGrid } from '@/lib/taskGrid'
import { dataAgeLabel } from '@/lib/dates'
import { requestInlineCreate } from '@/lib/quickCreate'
import { type Task, DONE_FILTER_LABEL, PRIORITY_LABEL } from '@/lib/tasks'
import { plural } from '@/lib/typography'
import { useViewConfig } from '@/stores/viewConfig'

type TabKey =
  | 'list'
  | 'board'
  | 'calendar'
  | 'timeline'
  | 'dashboard'
  | 'members'
  | 'about'

const TABS: { key: TabKey; label: string }[] = [
  { key: 'list', label: 'Список' },
  { key: 'board', label: 'Доска' },
  { key: 'calendar', label: 'Календарь' },
  { key: 'timeline', label: 'Хронология' },
  { key: 'dashboard', label: 'Дашборд' },
  { key: 'members', label: 'Участники' },
  { key: 'about', label: 'О проекте' },
]

// ─── Шапка проекта ──────────────────────────────────────────────────────────

function ProjectHeader({
  project,
  onOpenFields,
  onOpenLabels,
  onOpenShare,
  onCreateTask,
  tab,
  onTab,
  mobileFilters,
}: {
  project: Project
  onOpenFields: () => void
  onOpenLabels: () => void
  onOpenShare: () => void
  onCreateTask: () => void
  tab: TabKey
  onTab: (t: TabKey) => void
  /** Телефон: чип «Фильтры (N)» → шторка (MobileFilterSheet); на вкладках без фильтров — нет. */
  mobileFilters?: React.ReactNode
}) {
  const isArchived = !!project.archived_at
  const setFavorite = useSetFavorite(project.id)
  // Телефон: действия проекта (Поделиться/Поля/Метки) — те же, что в
  // десктопной шапке, шторкой «Действия»; без неё менеджер на телефоне не мог
  // создать метку вовсе (ОС 2026-08).
  const [actionsOpen, setActionsOpen] = useState(false)
  const mobileActions: { label: string; icon: ReactNode; onClick: () => void }[] = []
  if (project.can_edit)
    mobileActions.push({
      label: 'Поделиться',
      icon: <LinkIcon className="h-5 w-5" />,
      onClick: onOpenShare,
    })
  if (project.can_manage) {
    mobileActions.push({
      label: 'Поля',
      icon: <Settings2 className="h-5 w-5" />,
      onClick: onOpenFields,
    })
    mobileActions.push({ label: 'Метки', icon: <Tags className="h-5 w-5" />, onClick: onOpenLabels })
  }
  // «Импорт из CSV» и «Архивировать» переехали на вкладку «О проекте».
  const summary = summarizeProjectDescription(project.description)
  const counts = [
    project.task_count != null ? plural(project.task_count, 'задача', 'задачи', 'задач') : null,
  ].filter((c): c is string => Boolean(c))

  const favoriteButton = project.my_role && (
    <button
      type="button"
      onClick={() => setFavorite.mutate(!project.is_favorite)}
      disabled={setFavorite.isPending}
      className={cn(
        'flex h-7 w-7 shrink-0 items-center justify-center rounded-lg hover:bg-glass',
        project.is_favorite ? 'text-amber' : 'text-text2',
      )}
      aria-label={project.is_favorite ? 'Убрать из избранного' : 'В избранное'}
    >
      <Star className={cn('h-4 w-4', project.is_favorite && 'fill-amber')} />
    </button>
  )

  return (
    <header className="shrink-0 border-b border-hair bg-bg px-4 pt-4 lg:px-6">
      {/* Телефон — компактная шапка макета «Доска · мобильный»: eyebrow
          «KEY · N задач», название, бейджи; описание и кнопки
          действий — десктопу, фильтры — чипом в шторку (QA-0821 #13). */}
      <div className="lg:hidden">
        <div className="flex items-center justify-between gap-3">
          <p className="min-w-0 truncate text-[12px] font-semibold uppercase tracking-[0.08em] text-text2">
            {[project.key, ...counts].join(' · ')}
          </p>
          <span className="flex shrink-0 items-center gap-1.5">
            {mobileFilters}
            {mobileActions.length > 0 && (
              <button
                type="button"
                onClick={() => setActionsOpen(true)}
                aria-label="Действия проекта"
                className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-glass-border bg-glass text-text2 hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
              >
                <MoreHorizontal className="h-4 w-4" />
              </button>
            )}
          </span>
        </div>
        {mobileActions.length > 0 && (
          <BottomSheet open={actionsOpen} onOpenChange={setActionsOpen} title="Действия">
            {mobileActions.map((a) => (
              <BottomSheetItem
                key={a.label}
                icon={a.icon}
                onClick={() => {
                  setActionsOpen(false)
                  a.onClick()
                }}
              >
                {a.label}
              </BottomSheetItem>
            ))}
          </BottomSheet>
        )}
        <div className="mt-1 flex items-start gap-2">
          <h1 className="min-w-0 flex-1 font-display text-[22px] font-bold leading-[1.2] text-text [text-wrap:balance]">
            {project.name}
          </h1>
          {favoriteButton}
        </div>
        {(isArchived || project.my_role) && (
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            {isArchived && <Badge variant="secondary">архив</Badge>}
            {project.my_role && (
              <Badge variant="secondary">{PROJECT_ROLE_LABEL[project.my_role]}</Badge>
            )}
          </div>
        )}
      </div>

      <div className="hidden items-start gap-3.5 lg:flex">
        {/* items-start, а не items-center: блок с названием, бейджами и
            описанием может занимать две строки, и центрированная плашка ключа
            уезжала бы к описанию, а не к названию. */}
        <div className="flex min-w-0 flex-1 items-start gap-3">
          <ProjectKeyChip project={project} size="lg" className="mt-0.5" />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="min-w-0 font-display text-[22px] font-bold leading-[1.2] text-text">
                {project.name}
              </h1>
              {favoriteButton}
              <Badge variant="outline" className="font-mono tracking-[0.04em]">
                {project.key}
              </Badge>
              {isArchived && <Badge variant="secondary">архив</Badge>}
              {project.my_role && (
                <Badge variant="secondary">{PROJECT_ROLE_LABEL[project.my_role]}</Badge>
              )}
            </div>
            {/* Описание и счётчики — ОДНА строка: длинное описание режется
                многоточием (полный текст — в title), счётчики не переносятся
                на второй этаж (QA-0821 #3). */}
            <p className="mt-[3px] flex min-w-0 flex-nowrap items-center gap-x-[7px] text-[13px] text-text2">
              {summary && (
                // И текст, и title — сводка: описание выросло до 20 000
                // знаков, и нативный тултип на две страницы это издевательство,
                // а не подсказка. Полное описание живёт на вкладке «О проекте».
                <span className="min-w-0 truncate" title={summary}>
                  {summary}
                </span>
              )}
              {summary && counts.length > 0 && <span aria-hidden>·</span>}
              {counts.map((c, i) => (
                <span key={c} className="shrink-0 whitespace-nowrap">
                  {i > 0 && <span className="pr-[7px]">·</span>}
                  {c}
                </span>
              ))}
            </p>
          </div>
        </div>
        {(project.can_edit || project.can_manage) && (
          <div className="hidden shrink-0 items-center gap-2 pt-1.5 lg:flex">
            {project.can_edit && (
              <Button variant="secondary" size="sm" onClick={onOpenShare}>
                <LinkIcon className="h-[15px] w-[15px]" />
                Поделиться
              </Button>
            )}
            {project.can_manage && (
              <>
                <Button variant="secondary" size="sm" onClick={onOpenFields}>
                  <Settings2 className="h-[15px] w-[15px]" />
                  Поля
                </Button>
                <Button variant="secondary" size="sm" onClick={onOpenLabels}>
                  <Tags className="h-[15px] w-[15px]" />
                  Метки
                </Button>
              </>
            )}
            {/* Меню «…» здесь больше нет: «Импорт из CSV» и «Архивировать»
                переехали на вкладку «О проекте», и оно осталось пустым. */}
            {project.can_edit && (
              <Button size="sm" onClick={onCreateTask}>
                <Plus className="h-4 w-4" strokeWidth={2.2} />
                Задача
              </Button>
            )}
          </div>
        )}
      </div>
      <ViewTabs tab={tab} onTab={onTab} />
    </header>
  )
}

function ViewTabs({ tab, onTab }: { tab: TabKey; onTab: (t: TabKey) => void }) {
  return (
    <>
      {/* overflow-x-auto — не перестраховка, а замер: шесть вкладок
          занимают 588px, седьмая добавляет ~113px, а при окне 1024px
          полосе достаётся 680px (минус сайдбар 260, зазоры оболочки и
          отступы шапки). Без прокрутки обрезалась бы «О проекте». */}
      <nav className="mt-3.5 hidden gap-0.5 overflow-x-auto [scrollbar-width:none] lg:flex [&::-webkit-scrollbar]:hidden">
        {TABS.map(({ key, label }) => (
          <button
            key={key}
            type="button"
            onClick={() => onTab(key)}
            aria-current={tab === key ? 'page' : undefined}
            className={cn(
              'inline-flex h-[38px] shrink-0 items-center whitespace-nowrap border-b-2 px-3.5 text-[15px] font-semibold transition-colors',
              tab === key
                ? 'border-amber text-text'
                : 'border-transparent text-text2 hover:text-text',
            )}
          >
            {label}
          </button>
        ))}
      </nav>
      {/* Мобильный выбор представления — плавающая пилюля по центру над
          таб-баром (MobileViewControlBar), а не кнопка в шапке: стоит на всех
          представлениях, из календаря/Ганта/дашборда можно вернуться. */}
      <MobileViewControlBar
        options={TABS.map(({ key, label }) => ({ key, label }))}
        value={tab}
        onChange={onTab}
      />
    </>
  )
}

// ─── Секция списка ──────────────────────────────────────────────────────────

function TaskListBlock({
  projectId,
  tasks,
  gridColumns,
  visibleFields,
  valuesByTask,
  childrenByParent,
  labelsByTask,
  stageNames,
  canEditFlag,
  isDesktop,
  selectedTaskId,
  onTaskClick,
}: {
  projectId: string
  tasks: Task[]
  gridColumns: string
  visibleFields: CustomFieldDefinition[]
  valuesByTask: Map<string, Map<string, CustomFieldValue>>
  childrenByParent?: Map<string, { total: number; done: number }>
  labelsByTask?: Map<string, Label[]>
  /** id колонки → имя: чип в строке контекста, единственный признак движения
   *  задачи по доске после 0044. */
  stageNames?: Map<string, string>
  canEditFlag: boolean
  isDesktop: boolean
  selectedTaskId: string | null
  onTaskClick: (id: string) => void
}) {
  const toggleDone = useToggleDone(projectId)

  return (
    <section>
      {/* Инлайн-поле СВЕРХУ, а не под списком. Кнопка «Новая задача» в
          сайдбаре наводится на него через `scrollIntoView` (lib/quickCreate),
          и в плоском списке на 2 500 строк поле внизу швыряло бы человека в
          самый конец проекта. Раньше поле было в первом блоке секции, то есть
          тоже наверху — поведение сохраняем, а не меняем. */}
      {canEditFlag && (
        <div className="px-4 py-2 lg:pl-[21px] lg:pr-6">
          <TaskInlineCreate projectId={projectId} quickCreateTarget />
        </div>
      )}
      {tasks.map((t) =>
        isDesktop ? (
          <TaskRow
            key={t.id}
            task={t}
            gridColumns={gridColumns}
            labels={labelsByTask?.get(t.id)}
            subtasks={childrenByParent?.get(t.id)}
            stage={t.stage_id ? stageNames?.get(t.stage_id) : null}
            selected={selectedTaskId === t.id}
            onClick={() => onTaskClick(t.id)}
            // Сервер сказал «нельзя» — контрол не рисуем вовсе (у
            // TaskDoneControl нет disabled: без onToggle он рендерит
            // неинтерактивную иконку). undefined ≠ false: «не знаем» —
            // показываем, как раньше.
            onToggleDone={t.can_complete === false ? undefined : () => toggleDone(t)}
            cells={visibleFields.map((f) => {
              const v = valuesByTask.get(t.id)?.get(f.id)?.value
              const text = formatCustomFieldValue(f, v)
              return (
                <span
                  key={f.id}
                  className={cn(
                    'truncate pr-3.5 text-[14px] text-text2',
                    f.type === 'number' && 'font-mono',
                  )}
                  title={`${f.name}: ${text}`}
                >
                  {text}
                </span>
              )
            })}
          />
        ) : (
          <MobileTaskRow
            key={t.id}
            task={t}
            labels={labelsByTask?.get(t.id)}
            subtasks={childrenByParent?.get(t.id)}
            stage={t.stage_id ? stageNames?.get(t.stage_id) : null}
            selected={selectedTaskId === t.id}
            onClick={() => onTaskClick(t.id)}
            onToggleDone={t.can_complete === false ? undefined : () => toggleDone(t)}
          />
        ),
      )}
    </section>
  )
}

// ─── Список ─────────────────────────────────────────────────────────────────

function ListTab({
  projectId,
  project,
  onTaskClick,
  selectedTaskId,
  filters,
  onResetFilters,
  onDropFilter,
  onCreateTask,
  onImport,
}: {
  projectId: string
  project: Project
  onTaskClick: (id: string) => void
  selectedTaskId: string | null
  filters: TaskViewFilters
  onResetFilters: () => void
  onDropFilter: (key: NarrowableFilter) => void
  /** Создать задачу, когда инлайн-поля на экране нет (пустой проект). */
  onCreateTask: () => void
  /** «Импорт из CSV» — вторая кнопка пустого состояния (макет). */
  onImport: () => void
}) {
  const isDesktop = useIsDesktop()
  const listFilters = useMemo(() => toListFilters(filters), [filters])
  const tasks = useTasks(projectId, listFilters)
  const defs = useCustomFieldDefinitions(projectId)
  const values = useProjectCustomValues(projectId)
  const visibleIds = useViewConfig(
    (s) => s.byProject[projectId]?.visibleCustomFields ?? [],
  )

  const canEditFlag = project.can_edit

  // Плоский список: секций больше нет, группировать не по чему. Порядок
  // задаёт сервер (`position`, тай-брейкер `seq`), а выполненные тонут вниз —
  // решение владельца 2026-08-21.
  const rows = useMemo(
    () => sinkDone((tasks.data ?? []).filter((t) => !t.parent_task_id)),
    [tasks.data],
  )

  // Счётчик k/N для чипа на строке родителя. При активных фильтрах дети
  // могут быть отфильтрованы — чип занижен; полный счёт виден в карточке.
  const childrenByParent = useMemo(() => {
    const m = new Map<string, { total: number; done: number }>()
    for (const t of tasks.data ?? []) {
      if (!t.parent_task_id) continue
      const s = m.get(t.parent_task_id) ?? { total: 0, done: 0 }
      s.total += 1
      if (t.done) s.done += 1
      m.set(t.parent_task_id, s)
    }
    return m
  }, [tasks.data])

  const labels = useLabels(projectId)
  const labelAssignments = useLabelAssignments(projectId)
  // Имена для строки «Исполнитель: … · Метка: …» в пустом состоянии фильтров.
  const members = useProjectMembers(projectId)
  const labelsByTask = useMemo(() => {
    const byId = new Map((labels.data ?? []).map((l) => [l.id, l]))
    const m = new Map<string, Label[]>()
    for (const a of labelAssignments.data ?? []) {
      const l = byId.get(a.label_id)
      if (!l) continue
      const list = m.get(a.task_id) ?? []
      list.push(l)
      m.set(a.task_id, list)
    }
    return m
  }, [labels.data, labelAssignments.data])

  const visibleFields = useMemo(() => {
    if (!defs.data) return []
    const byId = new Map(defs.data.map((d) => [d.id, d]))
    return visibleIds
      .map((id) => byId.get(id))
      .filter((d): d is CustomFieldDefinition => d !== undefined)
  }, [defs.data, visibleIds])

  const valuesByTask = useMemo(() => {
    const m = new Map<string, Map<string, CustomFieldValue>>()
    for (const v of values.data ?? []) {
      const bucket = m.get(v.task_id) ?? new Map()
      bucket.set(v.field_id, v)
      m.set(v.task_id, bucket)
    }
    return m
  }, [values.data])

  const grid = useMemo(() => projectTaskGrid(visibleFields), [visibleFields])

  // Имена колонок доски для чипа в строке списка: состояние задачи после 0044
  // схлопнулось в галочку, и без колонки список не отличает «взяли в работу»
  // от «лежит нетронутой».
  const stages = useStages(projectId)
  const stageNames = useMemo(
    () => new Map((stages.data ?? []).map((s) => [s.id, s.name])),
    [stages.data],
  )


  if (tasks.isLoading) {
    return <TaskListSkeleton compact={!isDesktop} />
  }
  if (tasks.isError) {
    return (
      <TaskEmptyState
        tone="error"
        title="Не удалось загрузить задачи"
        text="Проверьте соединение и попробуйте ещё раз."
        meta={dataAgeLabel(tasks.dataUpdatedAt)}
        cta="Повторить"
        onCta={() => void tasks.refetch()}
      />
    )
  }

  const visibleTasks = rows
  const filtersActive = activeFilterCount(filters) > 0
  const narrowable = narrowableFilter(filters)

  if (visibleTasks.length === 0) {
    return filtersActive ? (
      <TaskEmptyState
        title="Под фильтры не попала ни одна задача"
        // Перечисляем, ЧТО отсекло: «Исполнитель: Дмитрий Фёдоров · Приоритет:
        // срочно. Из 312 задач — ни одной.»
        text={[
          describeFilters(
            filters,
            {
              assignee: members.data?.find((m) => m.employee_id === filters.assignee)
                ?.full_name,
              label: labels.data?.find((l) => l.id === filters.label)?.name,
            },
            { done: DONE_FILTER_LABEL, priority: PRIORITY_LABEL },
          ),
          project.task_count
            ? `Из ${project.task_count} задач проекта — ни одной.`
            : 'В проекте пока нет задач.',
        ]
          .filter(Boolean)
          .join('. ')}
        cta="Сбросить фильтры"
        onCta={onResetFilters}
        secondaryCta={narrowable ? `Снять ${narrowable.label}` : undefined}
        onSecondary={narrowable ? () => onDropFilter(narrowable.key) : undefined}
      />
    ) : (
      <TaskEmptyState
        title="Пока нет задач. Создайте первую."
        // Обещание секций пережило их самих: секций нет с 0047/0048, список
        // плоский всегда. Вместо мёртвой функции — то, что правда полезно
        // знать в пустом проекте.
        text="Задача может жить без колонки — на доску её кладут, когда доска понадобится."
        cta={canEditFlag ? 'Создать задачу' : undefined}
        // Та же точка входа, что у «Новой задачи» в сайдбаре: курсор в
        // инлайн-поле первого блока; в пустом проекте поля нет — диалог.
        onCta={
          canEditFlag
            ? () => {
                if (!requestInlineCreate(projectId)) onCreateTask()
              }
            : undefined
        }
        secondaryCta={canEditFlag ? 'Импорт из CSV' : undefined}
        onSecondary={canEditFlag ? onImport : undefined}
      />
    )
  }

  const blocks = (
    <TaskListBlock
      projectId={projectId}
      tasks={visibleTasks}
      gridColumns={grid.columns}
      visibleFields={visibleFields}
      valuesByTask={valuesByTask}
      childrenByParent={childrenByParent}
      labelsByTask={labelsByTask}
      stageNames={stageNames}
      canEditFlag={canEditFlag}
      isDesktop={isDesktop}
      selectedTaskId={selectedTaskId}
      onTaskClick={onTaskClick}
    />
  )

  return (
    <div className="min-w-0 flex-1 lg:overflow-auto">
      {/* Треки фиксированные, поэтому на десяти включённых полях таблица шире
          рабочей области: скроллим её целиком, вместе с шапкой колонок —
          иначе подписи разъедутся со значениями. */}
      <div style={isDesktop ? { minWidth: grid.minWidth } : undefined}>
        {isDesktop && (
          <div className="sticky top-0 z-10">
            <TaskListHeader
              gridColumns={grid.columns}
              fieldNames={visibleFields.map((f) => f.name)}
            />
          </div>
        )}
        {blocks}
      </div>
    </div>
  )
}

// ─── Страница ───────────────────────────────────────────────────────────────

export function ProjectPage() {
  const { id } = useParams<{ id: string }>()
  const [searchParams, setSearchParams] = useSearchParams()
  const project = useProject(id)
  // Вид живёт в URL рядом с фильтрами: ссылка на доску проекта должна
  // открывать доску, а не список.
  const tabParam = searchParams.get('view')
  const tab: TabKey = TABS.some((t) => t.key === tabParam)
    ? (tabParam as TabKey)
    : 'list'
  const setTab = (next: TabKey) => {
    const sp = new URLSearchParams(searchParams)
    if (next === 'list') sp.delete('view')
    else sp.set('view', next)
    setSearchParams(sp, { replace: true })
  }
  const [fieldsOpen, setFieldsOpen] = useState(false)
  const [labelsOpen, setLabelsOpen] = useState(false)
  const [shareOpen, setShareOpen] = useState(false)
  const [createTaskOpen, setCreateTaskOpen] = useState(false)
  const [importOpen, setImportOpen] = useState(false)

  const selectedTaskId = searchParams.get('task')
  const openTask = (taskId: string) => {
    const next = new URLSearchParams(searchParams)
    next.set('task', taskId)
    setSearchParams(next, { replace: false })
  }
  const closeTask = () => {
    const next = new URLSearchParams(searchParams)
    next.delete('task')
    setSearchParams(next, { replace: true })
  }

  // Фильтры видов живут в URL — переживают F5 и шарятся ссылкой.
  const filters = useMemo(() => filtersFromSearchParams(searchParams), [searchParams])
  const setFilters = (next: TaskViewFilters) => {
    const sp = new URLSearchParams(searchParams)
    applyFiltersToSearchParams(sp, next)
    setSearchParams(sp, { replace: true })
  }

  if (!id) return null
  if (project.isLoading) {
    return (
      <div className="space-y-4 p-6">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-8 w-96" />
        <TaskListSkeleton />
      </div>
    )
  }
  if (project.error) {
    return (
      <div className="mx-auto max-w-xl space-y-4 p-8 text-center">
        <h2 className="font-display text-xl text-red">Не удалось открыть проект</h2>
        <p className="text-text2">{(project.error as Error).message}</p>
        <Link to="/projects" className="text-amber underline">
          Назад к списку
        </Link>
      </div>
    )
  }
  if (!project.data) return null

  const p = project.data
  const isArchived = !!p.archived_at
  const readOnlyReason = isArchived
    ? 'Проект в архиве: правки закрыты.'
    : !p.can_edit
      ? 'Только чтение: вы наблюдатель проекта.'
      : null

  /** Тулбар фильтров — отдельная полоса под шапкой, как в макете (десктоп);
   *  на телефоне те же фильтры — чип «Фильтры (N)» в шапке → шторка. */
  const toolbar = (trailing?: React.ReactNode, showSort?: boolean, showLabel = true) => (
    <div className="hidden shrink-0 border-b border-hair bg-bg px-4 py-2.5 lg:block lg:px-6">
      <TaskFilterBar
        projectId={id}
        value={filters}
        onChange={setFilters}
        showSort={showSort}
        showLabel={showLabel}
        trailing={trailing}
      />
    </div>
  )
  const mobileFilters = (showSort: boolean, showLabel: boolean) => (
    <MobileFilterSheet
      projectId={id}
      value={filters}
      onChange={setFilters}
      showSort={showSort}
      showLabel={showLabel}
    />
  )

  return (
    <div className="flex flex-col lg:h-full lg:overflow-hidden">
      <ProjectHeader
        project={p}
        tab={tab}
        onTab={setTab}
        mobileFilters={
          tab === 'list'
            ? mobileFilters(true, true)
            : tab === 'board'
              ? mobileFilters(false, true)
              : tab === 'calendar'
                ? mobileFilters(false, false)
                : undefined
        }
        onOpenFields={() => setFieldsOpen(true)}
        onOpenLabels={() => setLabelsOpen(true)}
        onOpenShare={() => setShareOpen(true)}
        // «Задача» в шапке — та же точка входа, что «Новая задача» в сайдбаре:
        // курсор в инлайн-поле списка; если поля нет (пустой проект, другая
        // вкладка ещё не перерисовалась) — диалог создания.
        onCreateTask={() => {
          setTab('list')
          setTimeout(() => {
            if (!requestInlineCreate(id)) setCreateTaskOpen(true)
          }, 0)
        }}
      />

      {readOnlyReason && (
        <p className="shrink-0 border-b border-hair bg-tint px-4 py-2 text-[14px] text-text2 lg:px-6">
          {readOnlyReason}
        </p>
      )}

      {tab === 'list' && (
        <>
          {toolbar(<ColumnsMenu projectId={id} />, true)}
          <ListTab
            projectId={id}
            project={p}
            onTaskClick={openTask}
            selectedTaskId={selectedTaskId}
            filters={filters}
            onResetFilters={() => setFilters({ sort: filters.sort, order: filters.order })}
            onDropFilter={(key) => setFilters({ ...filters, [key]: undefined })}
            onCreateTask={() => setCreateTaskOpen(true)}
            onImport={() => setImportOpen(true)}
          />
        </>
      )}
      {tab === 'board' && (
        <>
          {toolbar()}
          <div className="min-w-0 flex-1 px-4 pb-6 pt-4 lg:overflow-auto lg:px-6">
            <BoardView
              projectId={id}
              canEdit={p.can_edit}
              onTaskClick={openTask}
              filters={filters}
              onResetFilters={() =>
                setFilters({ sort: filters.sort, order: filters.order })
              }
            />
          </div>
        </>
      )}
      {tab === 'calendar' && (
        <>
          {toolbar(undefined, false, false)}
          {/* На мобильном календарь — список дней со своими отступами, поэтому
              обёртка без padding; на десктопе — сетка в 24px. */}
          <div className="min-w-0 flex-1 pb-24 pt-2 lg:overflow-auto lg:p-6">
            <CalendarView projectId={id} onTaskClick={openTask} filters={filters} />
          </div>
        </>
      )}
      {tab === 'timeline' && (
        <div className="min-w-0 flex-1 pb-24 pt-2 lg:overflow-auto lg:p-6">
          <TimelineView projectId={id} onTaskClick={openTask} />
        </div>
      )}
      {tab === 'dashboard' && (
        <div className="min-w-0 flex-1 p-4 lg:overflow-auto lg:p-6">
          <Suspense
            fallback={
              <div className="flex items-center gap-2 p-2 text-sm text-text2">
                <Loader2 className="h-4 w-4 animate-spin" /> Загружаем дашборд…
              </div>
            }
          >
            <ProjectDashboard projectId={id} />
          </Suspense>
        </div>
      )}
      {tab === 'members' && (
        <div className="min-w-0 flex-1 p-4 lg:overflow-auto lg:p-6">
          <MembersTab projectId={id} canManage={p.can_manage} />
        </div>
      )}

      {tab === 'about' && (
        // pb-28 на мобильном — под плавающей пилюлей вида, иначе она накрывает
        // «Опасную зону».
        <div className="min-w-0 flex-1 p-4 pb-28 lg:overflow-auto lg:p-6">
          <AboutTab project={p} onImport={() => setImportOpen(true)} />
        </div>
      )}

      {/* FAB над пилюлей вида (132px); только там, где есть куда создавать
          задачу: на дашборде и участниках создание не живёт, в read-only — тоже. */}
      <FloatingActionButton
        bottomOffset={8.25}
        hidden={
          tab === 'dashboard' ||
          tab === 'members' ||
          tab === 'about' ||
          !p.can_edit ||
          isArchived
        }
      />

      <TaskDetailDrawer
        taskId={selectedTaskId}
        projectId={id}
        onClose={closeTask}
        onOpenTask={openTask}
        onManageLabels={() => setLabelsOpen(true)}
      />

      <CustomFieldsManager
        projectId={id}
        open={fieldsOpen}
        onOpenChange={setFieldsOpen}
      />

      <LabelsManager projectId={id} open={labelsOpen} onOpenChange={setLabelsOpen} />

      <CreateTaskDialog
        open={createTaskOpen}
        onOpenChange={setCreateTaskOpen}
        initialProjectId={id}
        openAfterCreate
      />
      <ImportTasksDialog open={importOpen} onOpenChange={setImportOpen} projectId={id} />

      <ShareDialog
        scope="project"
        entityId={id}
        entityLabel={p.name}
        open={shareOpen}
        onOpenChange={setShareOpen}
      />
    </div>
  )
}
