import { ChevronDown, Link as LinkIcon, Loader2, MoreHorizontal, Plus, Settings2, Star, Tags, Trash2 } from 'lucide-react'
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
import { Skeleton, SkeletonRows } from '@/components/ui/Skeleton'
import { QueryError } from '@/components/QueryError'
import { ShareDialog } from '@/components/share/ShareDialog'
import { TaskDetailDrawer } from '@/components/task/TaskDetailDrawer'
import { TaskListHeader } from '@/components/task/TaskListHeader'
import { TaskInlineCreate } from '@/components/task/TaskInlineCreate'
import { TaskRow } from '@/components/task/TaskRow'
import { TimelineView } from '@/components/timeline/TimelineView'
import {
  BottomSheet,
  BottomSheetItem,
} from '@/components/ui/BottomSheet'
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
import { useTasks, useUpdateTask } from '@/hooks/useTasks'
import { cn } from '@/lib/cn'
import { type Label } from '@/lib/labels'
import { type CustomFieldDefinition, type CustomFieldValue } from '@/lib/customFields'
import {
  PROJECT_ROLE_LABEL,
  type Project,
  type ProjectRole,
  type Section,
} from '@/lib/projects'
import {
  applyFiltersToSearchParams,
  filtersFromSearchParams,
  toListFilters,
  type TaskViewFilters,
} from '@/lib/taskFilters'
import { type Task } from '@/lib/tasks'
import { useViewConfig } from '@/stores/viewConfig'

type TabKey =
  | 'list'
  | 'board'
  | 'calendar'
  | 'timeline'
  | 'dashboard'
  | 'members'

const TABS: { key: TabKey; label: string; disabled?: boolean }[] = [
  { key: 'list', label: 'Список' },
  { key: 'board', label: 'Доска' },
  { key: 'calendar', label: 'Календарь' },
  { key: 'timeline', label: 'Хронология' },
  { key: 'dashboard', label: 'Дашборд' },
  { key: 'members', label: 'Участники' },
]

function canEdit(role: ProjectRole | null | undefined): boolean {
  return role === 'owner' || role === 'editor'
}
function canManage(role: ProjectRole | null | undefined): boolean {
  return role === 'owner'
}

function projectIconClasses(p: Project): string {
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

function ProjectHeader({
  project,
  onArchive,
  onOpenFields,
  onOpenLabels,
  onOpenShare,
}: {
  project: Project
  onArchive: () => void
  onOpenFields: () => void
  onOpenLabels: () => void
  onOpenShare: () => void
}) {
  const isArchived = !!project.archived_at
  const myRole = project.my_role
  const setFavorite = useSetFavorite(project.id)
  return (
    <div className="flex items-start justify-between gap-4 px-1">
      <div className="flex min-w-0 items-center gap-3">
        <div
          className={cn(
            'flex h-10 w-10 shrink-0 items-center justify-center rounded-lg font-display text-base font-black uppercase',
            projectIconClasses(project),
          )}
        >
          {project.key.slice(0, 2)}
        </div>
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h1 className="truncate font-display text-2xl font-semibold">{project.name}</h1>
            {myRole && (
              <button
                type="button"
                onClick={() => setFavorite.mutate(!project.is_favorite)}
                disabled={setFavorite.isPending}
                className={cn(
                  'hover:text-amber',
                  project.is_favorite ? 'text-amber' : 'text-text3',
                )}
                aria-label={
                  project.is_favorite ? 'Убрать из избранного' : 'В избранное'
                }
                title={project.is_favorite ? 'Убрать из избранного' : 'В избранное'}
              >
                <Star
                  className={cn('h-4 w-4', project.is_favorite && 'fill-amber')}
                />
              </button>
            )}
            <Badge variant="outline">{project.key}</Badge>
            {isArchived && <Badge variant="secondary">архив</Badge>}
            {myRole && <Badge variant="default">{PROJECT_ROLE_LABEL[myRole]}</Badge>}
          </div>
          {project.description && (
            <p className="mt-0.5 max-w-2xl truncate text-sm text-text2">
              {project.description}
            </p>
          )}
        </div>
      </div>
      {(canManage(myRole) || canEdit(myRole)) && (
        <div className="flex items-center gap-2">
          {canEdit(myRole) && (
            <Button
              variant="secondary"
              size="sm"
              onClick={onOpenShare}
              aria-label="Поделиться проектом"
            >
              <LinkIcon className="h-3.5 w-3.5" />
              Поделиться
            </Button>
          )}
          {canManage(myRole) && (
            <>
              <Button
                variant="secondary"
                size="sm"
                onClick={onOpenFields}
                aria-label="Поля проекта"
              >
                <Settings2 className="h-3.5 w-3.5" />
                Поля
              </Button>
              <Button
                variant="secondary"
                size="sm"
                onClick={onOpenLabels}
                aria-label="Метки проекта"
              >
                <Tags className="h-3.5 w-3.5" />
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
        </div>
      )}
    </div>
  )
}

function TabsRow({
  active,
  onChange,
}: {
  active: TabKey
  onChange: (t: TabKey) => void
}) {
  // Hidden on mobile — replaced by MobileViewControlBar at the bottom.
  return (
    <div className="hidden gap-1 border-b border-glass-border px-1 lg:flex">
      {TABS.map(({ key, label, disabled }) => (
        <button
          key={key}
          disabled={disabled}
          onClick={() => onChange(key)}
          className={cn(
            '-mb-px border-b-2 px-3 py-2 text-sm font-medium transition-colors',
            active === key
              ? 'border-amber text-text'
              : 'border-transparent text-text2 hover:text-text',
            disabled && 'cursor-not-allowed opacity-50',
          )}
          title={disabled ? 'Скоро (Hub-MVP.3b)' : undefined}
        >
          {label}
        </button>
      ))}
    </div>
  )
}

function MobileViewControlBar({
  active,
  onChange,
}: {
  active: TabKey
  onChange: (t: TabKey) => void
}) {
  const [pickerOpen, setPickerOpen] = useState(false)
  const current = TABS.find((t) => t.key === active)!
  return (
    <>
      <div
        className="fixed inset-x-0 z-20 flex items-center justify-center gap-2 px-4 lg:hidden"
        style={{
          bottom: 'calc(env(safe-area-inset-bottom, 0) + 4.5rem)',
        }}
      >
        <div className="flex items-center gap-1 rounded-full border border-glass-border bg-bg-alt/95 px-1 py-1 shadow-lg backdrop-blur">
          <button
            type="button"
            onClick={() => setPickerOpen(true)}
            className="inline-flex items-center gap-1.5 rounded-full px-4 py-2 text-sm font-medium text-text active:bg-surface"
          >
            {current.label}
            <ChevronDown className="h-3.5 w-3.5 text-text3" />
          </button>
        </div>
      </div>

      <BottomSheet
        open={pickerOpen}
        onOpenChange={setPickerOpen}
        title="Выберите вид"
      >
        {TABS.map(({ key, label, disabled }) => (
          <BottomSheetItem
            key={key}
            disabled={disabled}
            onClick={() => {
              onChange(key)
              setPickerOpen(false)
            }}
            trailing={active === key ? '✓' : null}
          >
            {label}
          </BottomSheetItem>
        ))}
      </BottomSheet>
    </>
  )
}

function SectionBlock({
  section,
  projectId,
  tasks,
  canEditFlag,
  canManageFlag,
  onTaskClick,
  visibleFields,
  valuesByTask,
  childrenByParent,
  labelsByTask,
}: {
  section: Section | null
  projectId: string
  tasks: Task[]
  canEditFlag: boolean
  canManageFlag: boolean
  onTaskClick: (id: string) => void
  visibleFields: CustomFieldDefinition[]
  valuesByTask: Map<string, Map<string, CustomFieldValue>>
  childrenByParent?: Map<string, { total: number; done: number }>
  labelsByTask?: Map<string, Label[]>
}) {
  const [collapsed, setCollapsed] = useState(false)
  const [renaming, setRenaming] = useState(false)
  const [draftName, setDraftName] = useState('')
  const del = useDeleteSection(projectId)
  const updateSection = useUpdateSection(projectId)
  const update = useUpdateTask(projectId)
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
      <header className="flex items-center justify-between border-b border-glass-border px-1 py-2">
        {renaming && section ? (
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
        ) : (
          <button
            type="button"
            onClick={() => setCollapsed((v) => !v)}
            className="flex items-baseline gap-2 text-left text-text hover:text-amber"
          >
            <span className="font-display text-base font-semibold">{title}</span>
            <span className="text-xs text-text3">{tasks.length}</span>
          </button>
        )}
        {section && (canEditFlag || canManageFlag) && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" aria-label="Действия">
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
        )}
      </header>

      {!collapsed && (
        <>
          <div>
            {tasks.map((t) => (
              <TaskRow
                key={t.id}
                task={t}
                subtasks={childrenByParent?.get(t.id)}
                labels={labelsByTask?.get(t.id)}
                onClick={() => onTaskClick(t.id)}
                onToggleDone={() =>
                  update.mutate({
                    id: t.id,
                    status: t.status === 'done' ? 'todo' : 'done',
                  })
                }
                visibleFields={visibleFields}
                customValues={valuesByTask.get(t.id)}
              />
            ))}
          </div>
          {canEditFlag && (
            <div className="px-2 pt-1">
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

function ListTab({
  projectId,
  myRole,
  onTaskClick,
  filters,
}: {
  projectId: string
  myRole: ProjectRole | null | undefined
  onTaskClick: (id: string) => void
  filters: TaskViewFilters
}) {
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

  // Definitions filtered + ordered by user's visibility config.
  const visibleFields = useMemo(() => {
    if (!defs.data) return []
    const byId = new Map(defs.data.map((d) => [d.id, d]))
    return visibleIds
      .map((id) => byId.get(id))
      .filter((d): d is CustomFieldDefinition => d !== undefined)
  }, [defs.data, visibleIds])

  // Map<task_id, Map<field_id, value>> — flat → nested lookup.
  const valuesByTask = useMemo(() => {
    const m = new Map<string, Map<string, CustomFieldValue>>()
    for (const v of values.data ?? []) {
      const bucket = m.get(v.task_id) ?? new Map()
      bucket.set(v.field_id, v)
      m.set(v.task_id, bucket)
    }
    return m
  }, [values.data])

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

  const orphanTasks = tasksBySection.get(null) ?? []
  const canEditFlag = canEdit(myRole)
  const canManageFlag = canManage(myRole)

  return (
    <div className="space-y-6">
      {sections.isLoading && <SkeletonRows rows={5} />}
      {sections.isError && (
        <QueryError
          error={sections.error}
          onRetry={() => void sections.refetch()}
          title="Не удалось загрузить секции"
        />
      )}
      {tasks.isError && (
        <QueryError
          error={tasks.error}
          onRetry={() => void tasks.refetch()}
          title="Не удалось загрузить задачи"
        />
      )}
      {(defs.isError || values.isError) && (
        <QueryError
          error={defs.error ?? values.error}
          onRetry={() => {
            if (defs.isError) void defs.refetch()
            if (values.isError) void values.refetch()
          }}
          title="Не удалось загрузить кастом-поля"
        />
      )}

      <TaskListHeader visibleFields={visibleFields} />

      {(orphanTasks.length > 0 || canEditFlag) && (
        <SectionBlock
          section={null}
          projectId={projectId}
          tasks={orphanTasks}
          canEditFlag={canEditFlag}
          canManageFlag={canManageFlag}
          onTaskClick={onTaskClick}
          visibleFields={visibleFields}
          valuesByTask={valuesByTask}
          childrenByParent={childrenByParent}
          labelsByTask={labelsByTask}
        />
      )}

      {sections.data?.map((s) => (
        <SectionBlock
          key={s.id}
          section={s}
          projectId={projectId}
          tasks={tasksBySection.get(s.id) ?? []}
          canEditFlag={canEditFlag}
          canManageFlag={canManageFlag}
          onTaskClick={onTaskClick}
          visibleFields={visibleFields}
          valuesByTask={valuesByTask}
          childrenByParent={childrenByParent}
          labelsByTask={labelsByTask}
        />
      ))}

      {canEditFlag && !addingSection && (
        <button
          onClick={() => setAddingSection(true)}
          className="flex items-center gap-1 px-1 text-sm text-text2 hover:text-amber"
        >
          <Plus className="h-4 w-4" /> Добавить секцию
        </button>
      )}
      {canEditFlag && addingSection && (
        <form onSubmit={onAddSection} className="flex gap-2 px-1">
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
  )
}

export function ProjectPage() {
  const { id } = useParams<{ id: string }>()
  const [searchParams, setSearchParams] = useSearchParams()
  const project = useProject(id)
  const archive = useArchiveProject(id ?? '')
  const [tab, setTab] = useState<TabKey>('list')
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
        <SkeletonRows rows={6} />
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

  return (
    <div className="space-y-4 p-6">
      <ProjectHeader
        project={p}
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
      />

      <TabsRow active={tab} onChange={setTab} />

      {tab === 'list' && (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2 px-1">
            <TaskFilterBar
              projectId={id}
              value={filters}
              onChange={setFilters}
              showSort
            />
            <ColumnsMenu projectId={id} />
          </div>
          <ListTab
            projectId={id}
            myRole={p.my_role}
            onTaskClick={openTask}
            filters={filters}
          />
        </div>
      )}
      {tab === 'board' && (
        <div className="space-y-3">
          <TaskFilterBar projectId={id} value={filters} onChange={setFilters} />
          <BoardView
            projectId={id}
            myRole={p.my_role}
            onTaskClick={openTask}
            filters={filters}
          />
        </div>
      )}
      {tab === 'calendar' && (
        <div className="space-y-3">
          <TaskFilterBar
            projectId={id}
            value={filters}
            onChange={setFilters}
            showLabel={false}
          />
          <CalendarView projectId={id} onTaskClick={openTask} filters={filters} />
        </div>
      )}
      {tab === 'timeline' && (
        <TimelineView projectId={id} onTaskClick={openTask} />
      )}
      {tab === 'dashboard' && (
        <Suspense
          fallback={
            <div className="flex items-center gap-2 p-2 text-sm text-text2">
              <Loader2 className="h-4 w-4 animate-spin" /> Загружаем дашборд…
            </div>
          }
        >
          <ProjectDashboard projectId={id} />
        </Suspense>
      )}
      {tab === 'members' && (
        <MembersTab projectId={id} canManage={canManage(p.my_role)} />
      )}

      {/* Mobile: floating view picker + FAB above the bottom tab bar. */}
      <MobileViewControlBar active={tab} onChange={setTab} />
      <FloatingActionButton bottomOffset={7.5} />

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
