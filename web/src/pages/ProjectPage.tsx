import { Filter, MoreHorizontal, Plus, Star, Trash2 } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'

import { CalendarView } from '@/components/calendar/CalendarView'
import { BoardView } from '@/components/kanban/BoardView'
import { TaskDetailDrawer } from '@/components/task/TaskDetailDrawer'
import { TaskInlineCreate } from '@/components/task/TaskInlineCreate'
import { TaskRow } from '@/components/task/TaskRow'
import { Avatar } from '@/components/ui/Avatar'
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
  useArchiveProject,
  useCreateSection,
  useDeleteSection,
  useProject,
  useProjectMembers,
  useProjectSections,
} from '@/hooks/useProjects'
import { useTasks, useUpdateTask } from '@/hooks/useTasks'
import { cn } from '@/lib/cn'
import { type Project, type ProjectRole, type Section } from '@/lib/projects'
import { type Task } from '@/lib/tasks'

type TabKey = 'list' | 'board' | 'calendar' | 'members'

const TABS: { key: TabKey; label: string; disabled?: boolean }[] = [
  { key: 'list', label: 'Список' },
  { key: 'board', label: 'Доска' },
  { key: 'calendar', label: 'Календарь' },
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
}: {
  project: Project
  onArchive: () => void
}) {
  const isArchived = !!project.archived_at
  const myRole = project.my_role
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
            <button
              type="button"
              className="text-text3 hover:text-amber"
              aria-label="В избранное (скоро)"
              title="В избранное (скоро)"
            >
              <Star className="h-4 w-4" />
            </button>
            <Badge variant="outline">{project.key}</Badge>
            {isArchived && <Badge variant="secondary">архив</Badge>}
            {myRole && <Badge variant="default">{myRole}</Badge>}
          </div>
          {project.description && (
            <p className="mt-0.5 max-w-2xl truncate text-sm text-text2">
              {project.description}
            </p>
          )}
        </div>
      </div>
      {canManage(myRole) && (
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
  return (
    <div className="flex gap-1 border-b border-glass-border px-1">
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

function SectionBlock({
  section,
  projectId,
  tasks,
  canEditFlag,
  canManageFlag,
  onTaskClick,
}: {
  section: Section | null
  projectId: string
  tasks: Task[]
  canEditFlag: boolean
  canManageFlag: boolean
  onTaskClick: (id: string) => void
}) {
  const [collapsed, setCollapsed] = useState(false)
  const del = useDeleteSection(projectId)
  const update = useUpdateTask(projectId)
  const title = section ? section.name : 'Без секции'

  return (
    <section>
      <header className="flex items-center justify-between border-b border-glass-border px-1 py-2">
        <button
          type="button"
          onClick={() => setCollapsed((v) => !v)}
          className="flex items-baseline gap-2 text-left text-text hover:text-amber"
        >
          <span className="font-display text-base font-semibold">{title}</span>
          <span className="text-xs text-text3">{tasks.length}</span>
        </button>
        {section && (canEditFlag || canManageFlag) && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" aria-label="Действия">
                <MoreHorizontal className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem disabled>Переименовать (скоро)</DropdownMenuItem>
              {canManageFlag && (
                <>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    destructive
                    onSelect={async () => {
                      try {
                        await del.mutateAsync(section.id)
                        toast.success(`Секция «${section.name}» удалена`)
                      } catch (err) {
                        toast.error('Не удалось удалить', {
                          description: (err as Error).message,
                        })
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
                onClick={() => onTaskClick(t.id)}
                onToggleDone={() =>
                  update.mutate({
                    id: t.id,
                    status: t.status === 'done' ? 'todo' : 'done',
                  })
                }
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
}: {
  projectId: string
  myRole: ProjectRole | null | undefined
  onTaskClick: (id: string) => void
}) {
  const sections = useProjectSections(projectId)
  const tasks = useTasks(projectId)
  const create = useCreateSection(projectId)
  const [newSectionName, setNewSectionName] = useState('')
  const [addingSection, setAddingSection] = useState(false)

  const tasksBySection = useMemo(() => {
    const map = new Map<string | null, Task[]>()
    for (const t of tasks.data ?? []) {
      const list = map.get(t.section_id) ?? []
      list.push(t)
      map.set(t.section_id, list)
    }
    return map
  }, [tasks.data])

  const onAddSection = async (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = newSectionName.trim()
    if (!trimmed) return
    try {
      await create.mutateAsync({ name: trimmed })
      setNewSectionName('')
      setAddingSection(false)
      toast.success(`Секция «${trimmed}» создана`)
    } catch (err) {
      toast.error('Не удалось создать секцию', {
        description: (err as Error).message,
      })
    }
  }

  const orphanTasks = tasksBySection.get(null) ?? []
  const canEditFlag = canEdit(myRole)
  const canManageFlag = canManage(myRole)

  return (
    <div className="space-y-6">
      {sections.isLoading && <p className="text-text2">Загружаем секции…</p>}
      {sections.error && (
        <p className="text-red">Ошибка: {(sections.error as Error).message}</p>
      )}

      {(orphanTasks.length > 0 || canEditFlag) && (
        <SectionBlock
          section={null}
          projectId={projectId}
          tasks={orphanTasks}
          canEditFlag={canEditFlag}
          canManageFlag={canManageFlag}
          onTaskClick={onTaskClick}
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

function MembersTab({ projectId }: { projectId: string }) {
  const members = useProjectMembers(projectId)
  return (
    <div className="space-y-2">
      {members.isLoading && <p className="text-text2">Загружаем участников…</p>}
      {members.error && (
        <p className="text-red">Ошибка: {(members.error as Error).message}</p>
      )}
      {members.data && members.data.length === 0 && (
        <p className="text-text2">Пока нет участников.</p>
      )}
      {members.data?.map((m) => (
        <div key={m.id} className="glass flex items-center justify-between p-3">
          <div className="flex items-center gap-3">
            <Avatar name={m.full_name} email={m.email} />
            <div>
              <p className="text-sm font-medium text-text">
                {m.full_name || m.email || m.employee_id}
              </p>
              {m.email && <p className="text-xs text-text3">{m.email}</p>}
            </div>
          </div>
          <Badge variant={m.role === 'owner' ? 'default' : 'secondary'}>{m.role}</Badge>
        </div>
      ))}
      <p className="pt-2 text-xs text-text3">
        Управление участниками (добавить / убрать / поменять роль) — в следующей итерации MVP.
      </p>
    </div>
  )
}

export function ProjectPage() {
  const { id } = useParams<{ id: string }>()
  const [searchParams, setSearchParams] = useSearchParams()
  const project = useProject(id)
  const archive = useArchiveProject(id ?? '')
  const [tab, setTab] = useState<TabKey>('list')

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

  if (!id) return null
  if (project.isLoading) return <div className="p-6 text-text2">Загружаем проект…</div>
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
          } catch (err) {
            toast.error('Не получилось', { description: (err as Error).message })
          }
        }}
      />

      <TabsRow active={tab} onChange={setTab} />

      {tab === 'list' && (
        <div className="space-y-3">
          <div className="flex items-center justify-between px-1">
            <Button variant="secondary" size="sm" disabled title="Фильтры (скоро)">
              <Filter className="h-3.5 w-3.5" /> Фильтр
            </Button>
          </div>
          <ListTab projectId={id} myRole={p.my_role} onTaskClick={openTask} />
        </div>
      )}
      {tab === 'board' && (
        <BoardView projectId={id} myRole={p.my_role} onTaskClick={openTask} />
      )}
      {tab === 'calendar' && (
        <CalendarView projectId={id} onTaskClick={openTask} />
      )}
      {tab === 'members' && <MembersTab projectId={id} />}

      <TaskDetailDrawer
        taskId={selectedTaskId}
        projectId={id}
        onClose={closeTask}
      />
    </div>
  )
}
