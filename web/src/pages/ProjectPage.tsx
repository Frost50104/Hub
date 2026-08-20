import {
  ChevronDown,
  Link as LinkIcon,
  Loader2,
  MoreHorizontal,
  Plus,
  Settings2,
  Star,
  Tags,
  Trash2,
} from 'lucide-react'
import { lazy, Suspense, useMemo, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'

// `recharts` is ~370KB minified. Lazy-load the entire dashboard chunk so
// the main bundle stays light for users who never open this tab.
const ProjectDashboard = lazy(
  () => import('@/components/dashboard/ProjectDashboard'),
)

import { CalendarView } from '@/components/calendar/CalendarView'
import { BoardView } from '@/components/kanban/BoardView'
import { FloatingActionButton } from '@/components/layout/FloatingActionButton'
import { ColumnsMenu } from '@/components/project/ColumnsMenu'
import { CustomFieldsManager } from '@/components/project/CustomFieldsManager'
import { LabelsManager } from '@/components/project/LabelsManager'
import { MembersTab } from '@/components/project/MembersTab'
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
import { TaskInlineCreate } from '@/components/task/TaskInlineCreate'
import { TaskRow } from '@/components/task/TaskRow'
import { TimelineView } from '@/components/timeline/TimelineView'
import { BottomSheet, BottomSheetItem } from '@/components/ui/BottomSheet'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/DropdownMenu'
import { Input } from '@/components/ui/Input'
import {
  useCustomFieldDefinitions,
  useProjectCustomValues,
} from '@/hooks/useCustomFields'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import {
  useArchiveProject,
  useCreateSection,
  useDeleteSection,
  useProject,
  useProjectSections,
  useSetFavorite,
  useUpdateSection,
} from '@/hooks/useProjects'
import { useLabelAssignments, useLabels } from '@/hooks/useLabels'
import { useTasks, useToggleDone } from '@/hooks/useTasks'
import { cn } from '@/lib/cn'
import { type Label } from '@/lib/labels'
import { type CustomFieldDefinition, type CustomFieldValue } from '@/lib/customFields'
import { formatCustomFieldValue } from '@/lib/formatCustomField'
import { PROJECT_ROLE_LABEL, type Project, type Section } from '@/lib/projects'
import {
  activeFilterCount,
  narrowableFilter,
  type NarrowableFilter,
  applyFiltersToSearchParams,
  filtersFromSearchParams,
  toListFilters,
  type TaskViewFilters,
} from '@/lib/taskFilters'
import { projectTaskGrid } from '@/lib/taskGrid'
import { type Task } from '@/lib/tasks'
import { plural } from '@/lib/typography'
import { ORPHAN_SECTION_KEY, useViewConfig } from '@/stores/viewConfig'

type TabKey = 'list' | 'board' | 'calendar' | 'timeline' | 'dashboard' | 'members'

const TABS: { key: TabKey; label: string }[] = [
  { key: 'list', label: 'Список' },
  { key: 'board', label: 'Доска' },
  { key: 'calendar', label: 'Календарь' },
  { key: 'timeline', label: 'Хронология' },
  { key: 'dashboard', label: 'Дашборд' },
  { key: 'members', label: 'Участники' },
]

// ─── Шапка проекта ──────────────────────────────────────────────────────────

function ProjectHeader({
  project,
  sectionCount,
  onArchive,
  onOpenFields,
  onOpenLabels,
  onOpenShare,
  onCreateTask,
  tab,
  onTab,
}: {
  project: Project
  sectionCount: number
  onArchive: () => void
  onOpenFields: () => void
  onOpenLabels: () => void
  onOpenShare: () => void
  onCreateTask: () => void
  tab: TabKey
  onTab: (t: TabKey) => void
}) {
  const isArchived = !!project.archived_at
  const setFavorite = useSetFavorite(project.id)
  const counts = [
    project.task_count != null ? plural(project.task_count, 'задача', 'задачи', 'задач') : null,
    sectionCount > 0 ? plural(sectionCount, 'секция', 'секции', 'секций') : null,
  ].filter(Boolean)

  return (
    <header className="shrink-0 border-b border-hair bg-bg px-4 pt-4 lg:px-6">
      <div className="flex items-start gap-3.5">
        {/* items-start, а не items-center: на 360px блок с названием, бейджами
            и описанием занимает четыре строки, и центрированная плашка ключа
            уезжала на середину — к описанию, а не к названию. */}
        <div className="flex min-w-0 flex-1 items-start gap-3">
          <span className="mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-[10px] bg-amber font-display text-base font-bold uppercase text-on-amber">
            {project.key.slice(0, 2)}
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="min-w-0 font-display text-[22px] font-bold leading-[1.2] text-text">
                {project.name}
              </h1>
              {project.my_role && (
                <button
                  type="button"
                  onClick={() => setFavorite.mutate(!project.is_favorite)}
                  disabled={setFavorite.isPending}
                  className={cn(
                    'flex h-7 w-7 shrink-0 items-center justify-center rounded-lg hover:bg-glass',
                    project.is_favorite ? 'text-amber' : 'text-text2',
                  )}
                  aria-label={
                    project.is_favorite ? 'Убрать из избранного' : 'В избранное'
                  }
                >
                  <Star className={cn('h-4 w-4', project.is_favorite && 'fill-amber')} />
                </button>
              )}
              <Badge variant="outline" className="font-mono tracking-[0.04em]">
                {project.key}
              </Badge>
              {isArchived && <Badge variant="secondary">архив</Badge>}
              {project.my_role && (
                <Badge variant="secondary">{PROJECT_ROLE_LABEL[project.my_role]}</Badge>
              )}
            </div>
            {/* Описание и счётчики — одна строка на десктопе и две на узком
                экране. Разделитель между ними живёт в `hidden sm:inline`:
                при переносе он остался бы сиротой в начале новой строки. */}
            <p className="mt-[3px] flex flex-wrap items-center gap-x-[7px] text-[13px] text-text2">
              {project.description && (
                <span className="min-w-0 truncate">{project.description}</span>
              )}
              {project.description && counts.length > 0 && (
                <span aria-hidden className="hidden sm:inline">
                  ·
                </span>
              )}
              {counts.map((c, i) => (
                <span key={c} className="whitespace-nowrap">
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
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button variant="secondary" size="icon" aria-label="Действия">
                      <MoreHorizontal className="h-4 w-4" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem onSelect={onArchive}>
                      {isArchived ? 'Разархивировать' : 'Архивировать'}
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </>
            )}
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
  const [sheet, setSheet] = useState(false)
  const current = TABS.find((t) => t.key === tab)!
  return (
    <>
      <nav className="mt-3.5 hidden gap-0.5 lg:flex">
        {TABS.map(({ key, label }) => (
          <button
            key={key}
            type="button"
            onClick={() => onTab(key)}
            aria-current={tab === key ? 'page' : undefined}
            className={cn(
              'inline-flex h-[38px] items-center border-b-2 px-3.5 text-[15px] font-semibold transition-colors',
              tab === key
                ? 'border-amber text-text'
                : 'border-transparent text-text2 hover:text-text',
            )}
          >
            {label}
          </button>
        ))}
      </nav>
      {/* На мобильном переключатель видов — основной контрол, поэтому кнопка
          44px и шторка со строками 52px, а не плавающая пилюля 32px. */}
      <div className="mt-3 flex lg:hidden">
        <button
          type="button"
          onClick={() => setSheet(true)}
          className="inline-flex min-h-11 items-center gap-1.5 rounded-[11px] border border-glass-border px-4 text-[14px] font-semibold text-text"
        >
          {current.label}
          <ChevronDown className="h-3.5 w-3.5 text-text2" />
        </button>
      </div>
      <BottomSheet open={sheet} onOpenChange={setSheet} title="Выберите вид">
        {TABS.map(({ key, label }) => (
          <BottomSheetItem
            key={key}
            onClick={() => {
              onTab(key)
              setSheet(false)
            }}
            trailing={tab === key ? '✓' : null}
          >
            {label}
          </BottomSheetItem>
        ))}
      </BottomSheet>
    </>
  )
}

// ─── Секция списка ──────────────────────────────────────────────────────────

function SectionHeader({
  title,
  count,
  collapsed,
  onToggle,
  actions,
}: {
  title: string
  count: number
  collapsed: boolean
  onToggle: () => void
  actions?: React.ReactNode
}) {
  return (
    <div className="flex items-center border-b border-hair bg-tint">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={!collapsed}
        className="flex min-h-11 flex-1 items-center gap-2.5 py-[9px] pl-[21px] pr-3 text-left hover:bg-glass focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-amber lg:min-h-0"
      >
        <ChevronDown
          className={cn(
            'h-[15px] w-[15px] shrink-0 text-text2 transition-transform',
            collapsed && '-rotate-90',
          )}
          strokeWidth={2.2}
        />
        <span className="truncate text-[13px] font-bold uppercase tracking-[0.06em] text-text2">
          {title}
        </span>
        <span className="font-mono text-[12px] text-text2">{count}</span>
      </button>
      {actions && <div className="pr-3">{actions}</div>}
    </div>
  )
}

function SectionBlock({
  section,
  projectId,
  tasks,
  gridColumns,
  visibleFields,
  valuesByTask,
  childrenByParent,
  labelsByTask,
  canEditFlag,
  canManageFlag,
  isDesktop,
  selectedTaskId,
  onTaskClick,
}: {
  section: Section | null
  projectId: string
  tasks: Task[]
  gridColumns: string
  visibleFields: CustomFieldDefinition[]
  valuesByTask: Map<string, Map<string, CustomFieldValue>>
  childrenByParent?: Map<string, { total: number; done: number }>
  labelsByTask?: Map<string, Label[]>
  canEditFlag: boolean
  canManageFlag: boolean
  isDesktop: boolean
  selectedTaskId: string | null
  onTaskClick: (id: string) => void
}) {
  const key = section ? section.id : ORPHAN_SECTION_KEY
  const collapsed = useViewConfig(
    (s) => s.byProject[projectId]?.collapsedSections?.includes(key) ?? false,
  )
  const toggleSection = useViewConfig((s) => s.toggleSection)
  const [renaming, setRenaming] = useState(false)
  const [draftName, setDraftName] = useState('')
  const del = useDeleteSection(projectId)
  const updateSection = useUpdateSection(projectId)
  const toggleDone = useToggleDone(projectId)
  const title = section ? section.name : 'Без секции'

  const commitRename = async () => {
    if (!section) return
    const trimmed = draftName.trim()
    if (!trimmed || trimmed === section.name) {
      setRenaming(false)
      return
    }
    try {
      await updateSection.mutateAsync({ sectionId: section.id, name: trimmed })
      setRenaming(false)
    } catch {
      // тост показывает глобальный onError мутаций; остаёмся в режиме правки
    }
  }

  return (
    <section>
      {renaming && section ? (
        <div className="border-b border-hair bg-tint py-1.5 pl-[21px] pr-3">
          <Input
            autoFocus
            value={draftName}
            onChange={(e) => setDraftName(e.target.value)}
            onBlur={() => setRenaming(false)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                void commitRename()
              } else if (e.key === 'Escape') {
                setRenaming(false)
              }
            }}
            className="h-8 max-w-[280px] font-display text-base font-semibold"
          />
        </div>
      ) : (
        <SectionHeader
          title={title}
          count={tasks.length}
          collapsed={collapsed}
          onToggle={() => toggleSection(projectId, key)}
          actions={
            section && (canEditFlag || canManageFlag) ? (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="ghost" size="icon" aria-label="Действия с секцией">
                    <MoreHorizontal className="h-4 w-4" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem
                    onSelect={() => {
                      // после закрытия меню Radix вернёт фокус на trigger —
                      // монтируем input тиком позже, чтобы autoFocus сработал
                      setTimeout(() => {
                        setDraftName(section.name)
                        setRenaming(true)
                      }, 0)
                    }}
                  >
                    Переименовать
                  </DropdownMenuItem>
                  {canManageFlag && (
                    <>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem
                        destructive
                        onSelect={async () => {
                          try {
                            await del.mutateAsync(section.id)
                            toast.success(`Секция «${section.name}» удалена`)
                          } catch {
                            // тост показывает глобальный onError мутаций
                          }
                        }}
                      >
                        <Trash2 className="mr-2 h-4 w-4" /> Удалить секцию
                      </DropdownMenuItem>
                    </>
                  )}
                </DropdownMenuContent>
              </DropdownMenu>
            ) : null
          }
        />
      )}

      {!collapsed && (
        <>
          {tasks.map((t) =>
            isDesktop ? (
              <TaskRow
                key={t.id}
                task={t}
                gridColumns={gridColumns}
                labels={labelsByTask?.get(t.id)}
                subtasks={childrenByParent?.get(t.id)}
                fallback={title}
                selected={selectedTaskId === t.id}
                onClick={() => onTaskClick(t.id)}
                onToggleDone={() => toggleDone(t)}
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
                fallback={title}
                selected={selectedTaskId === t.id}
                onClick={() => onTaskClick(t.id)}
                onToggleDone={() => toggleDone(t)}
              />
            ),
          )}
          {canEditFlag && (
            <div className="px-4 py-2 lg:pl-[21px] lg:pr-6">
              <TaskInlineCreate
                projectId={projectId}
                sectionId={section ? section.id : null}
              />
            </div>
          )}
        </>
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
}: {
  projectId: string
  project: Project
  onTaskClick: (id: string) => void
  selectedTaskId: string | null
  filters: TaskViewFilters
  onResetFilters: () => void
  onDropFilter: (key: NarrowableFilter) => void
}) {
  const isDesktop = useIsDesktop()
  const sections = useProjectSections(projectId)
  const listFilters = useMemo(() => toListFilters(filters), [filters])
  const tasks = useTasks(projectId, listFilters)
  const defs = useCustomFieldDefinitions(projectId)
  const values = useProjectCustomValues(projectId)
  const visibleIds = useViewConfig(
    (s) => s.byProject[projectId]?.visibleCustomFields ?? [],
  )
  const create = useCreateSection(projectId)
  const [newSectionName, setNewSectionName] = useState('')
  const [addingSection, setAddingSection] = useState(false)

  const canEditFlag = project.can_edit
  const canManageFlag = project.can_manage

  const tasksBySection = useMemo(() => {
    const map = new Map<string | null, Task[]>()
    for (const t of tasks.data ?? []) {
      // Подзадачи живут в карточке родителя, не отдельными строками.
      if (t.parent_task_id) continue
      const list = map.get(t.section_id) ?? []
      list.push(t)
      map.set(t.section_id, list)
    }
    return map
  }, [tasks.data])

  // Счётчик k/N для чипа на строке родителя. При активных фильтрах дети
  // могут быть отфильтрованы — чип занижен; полный счёт виден в карточке.
  const childrenByParent = useMemo(() => {
    const m = new Map<string, { total: number; done: number }>()
    for (const t of tasks.data ?? []) {
      if (!t.parent_task_id) continue
      const s = m.get(t.parent_task_id) ?? { total: 0, done: 0 }
      s.total += 1
      if (t.status === 'done') s.done += 1
      m.set(t.parent_task_id, s)
    }
    return m
  }, [tasks.data])

  const labels = useLabels(projectId)
  const labelAssignments = useLabelAssignments(projectId)
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

  const onAddSection = async (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = newSectionName.trim()
    if (!trimmed) return
    try {
      await create.mutateAsync({ name: trimmed })
      setNewSectionName('')
      setAddingSection(false)
      toast.success(`Секция «${trimmed}» создана`)
    } catch {
      // ввод сохраняем в поле; тост показывает глобальный onError мутаций
    }
  }

  if (tasks.isLoading || sections.isLoading) {
    return <TaskListSkeleton compact={!isDesktop} />
  }
  if (tasks.isError || sections.isError) {
    return (
      <TaskEmptyState
        tone="error"
        title="Не удалось загрузить задачи"
        text="Проверьте соединение и попробуйте ещё раз."
        cta="Повторить"
        onCta={() => {
          if (tasks.isError) void tasks.refetch()
          if (sections.isError) void sections.refetch()
        }}
      />
    )
  }

  const visibleTasks = (tasks.data ?? []).filter((t) => !t.parent_task_id)
  const filtersActive = activeFilterCount(filters) > 0
  const narrowable = narrowableFilter(filters)

  if (visibleTasks.length === 0) {
    return filtersActive ? (
      <TaskEmptyState
        title="Под фильтры не попала ни одна задача"
        text={
          project.task_count
            ? `Из ${project.task_count} задач проекта — ни одной.`
            : 'В проекте пока нет задач.'
        }
        cta="Сбросить фильтры"
        onCta={onResetFilters}
        secondaryCta={narrowable ? `Снять ${narrowable.label}` : undefined}
        onSecondary={narrowable ? () => onDropFilter(narrowable.key) : undefined}
      />
    ) : (
      <TaskEmptyState
        title="Пока нет задач. Создайте первую."
        text="Секции появятся, когда задач станет больше: до этого список плоский."
        cta={canEditFlag ? 'Создать задачу' : undefined}
        onCta={
          canEditFlag
            ? () => {
                const el = document.querySelector<HTMLInputElement>(
                  'input[aria-label="Новая задача"]',
                )
                el?.focus()
              }
            : undefined
        }
      />
    )
  }

  const orphanTasks = tasksBySection.get(null) ?? []
  const blocks = (
    <>
      {(orphanTasks.length > 0 || canEditFlag) && (
        <SectionBlock
          section={null}
          projectId={projectId}
          tasks={orphanTasks}
          gridColumns={grid.columns}
          visibleFields={visibleFields}
          valuesByTask={valuesByTask}
          childrenByParent={childrenByParent}
          labelsByTask={labelsByTask}
          canEditFlag={canEditFlag}
          canManageFlag={canManageFlag}
          isDesktop={isDesktop}
          selectedTaskId={selectedTaskId}
          onTaskClick={onTaskClick}
        />
      )}
      {sections.data?.map((s) => (
        <SectionBlock
          key={s.id}
          section={s}
          projectId={projectId}
          tasks={tasksBySection.get(s.id) ?? []}
          gridColumns={grid.columns}
          visibleFields={visibleFields}
          valuesByTask={valuesByTask}
          childrenByParent={childrenByParent}
          labelsByTask={labelsByTask}
          canEditFlag={canEditFlag}
          canManageFlag={canManageFlag}
          isDesktop={isDesktop}
          selectedTaskId={selectedTaskId}
          onTaskClick={onTaskClick}
        />
      ))}
    </>
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
        {canEditFlag && (
          <div className="px-4 py-4 lg:pl-[21px] lg:pr-6">
            {!addingSection ? (
              <button
                type="button"
                onClick={() => setAddingSection(true)}
                className="inline-flex min-h-11 items-center gap-1 text-[14px] font-semibold text-text2 hover:text-text lg:min-h-0"
              >
                <Plus className="h-4 w-4" /> Добавить секцию
              </button>
            ) : (
              <form onSubmit={onAddSection} className="flex gap-2">
                <Input
                  autoFocus
                  value={newSectionName}
                  onChange={(e) => setNewSectionName(e.target.value)}
                  placeholder="Название секции…"
                  disabled={create.isPending}
                  onKeyDown={(e) => {
                    if (e.key === 'Escape') {
                      setNewSectionName('')
                      setAddingSection(false)
                    }
                  }}
                />
                <Button type="submit" disabled={create.isPending || !newSectionName.trim()}>
                  Добавить
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => {
                    setNewSectionName('')
                    setAddingSection(false)
                  }}
                >
                  Отмена
                </Button>
              </form>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

// ─── Страница ───────────────────────────────────────────────────────────────

export function ProjectPage() {
  const { id } = useParams<{ id: string }>()
  const [searchParams, setSearchParams] = useSearchParams()
  const project = useProject(id)
  const sections = useProjectSections(id)
  const archive = useArchiveProject(id ?? '')
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

  /** Тулбар фильтров — отдельная полоса под шапкой, как в макете. */
  const toolbar = (trailing?: React.ReactNode, showSort?: boolean, showLabel = true) => (
    <div className="shrink-0 border-b border-hair bg-bg px-4 py-2.5 lg:px-6">
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

  return (
    <div className="flex flex-col lg:h-full lg:overflow-hidden">
      <ProjectHeader
        project={p}
        sectionCount={sections.data?.length ?? 0}
        tab={tab}
        onTab={setTab}
        onArchive={async () => {
          try {
            await archive.mutateAsync(!isArchived)
            toast.success(isArchived ? 'Проект разархивирован' : 'Проект архивирован')
          } catch {
            // тост показывает глобальный onError мутаций
          }
        }}
        onOpenFields={() => setFieldsOpen(true)}
        onOpenLabels={() => setLabelsOpen(true)}
        onOpenShare={() => setShareOpen(true)}
        onCreateTask={() => {
          setTab('list')
          setTimeout(() => {
            document
              .querySelector<HTMLInputElement>('input[aria-label="Новая задача"]')
              ?.focus()
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
          <div className="min-w-0 flex-1 p-4 lg:overflow-auto lg:p-6">
            <CalendarView projectId={id} onTaskClick={openTask} filters={filters} />
          </div>
        </>
      )}
      {tab === 'timeline' && (
        <div className="min-w-0 flex-1 p-4 lg:overflow-auto lg:p-6">
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

      <FloatingActionButton bottomOffset={4.5} />

      <TaskDetailDrawer
        taskId={selectedTaskId}
        projectId={id}
        onClose={closeTask}
        onOpenTask={openTask}
      />

      <CustomFieldsManager
        projectId={id}
        open={fieldsOpen}
        onOpenChange={setFieldsOpen}
      />

      <LabelsManager projectId={id} open={labelsOpen} onOpenChange={setLabelsOpen} />

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
