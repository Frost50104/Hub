import { zodResolver } from '@hookform/resolvers/zod'
import {
  DndContext,
  PointerSensor,
  TouchSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core'
import { CSS } from '@dnd-kit/utilities'
import {
  ChevronDown,
  ChevronRight,
  Folder,
  FolderPlus,
  MoreHorizontal,
  Plus,
} from 'lucide-react'
import { useMemo, useState, type CSSProperties } from 'react'
import { useForm } from 'react-hook-form'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { z } from 'zod'

import { CreateFolderDialog } from '@/components/project/CreateFolderDialog'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/Dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/DropdownMenu'
import { Input, Textarea } from '@/components/ui/Input'
import { Label } from '@/components/ui/Label'
import { SkeletonRows } from '@/components/ui/Skeleton'
import {
  useCreateProject,
  useDeleteFolder,
  useProjectFolders,
  useProjects,
  useRenameFolder,
  useReorderFolders,
  useSetProjectFolder,
} from '@/hooks/useProjects'
import { ProjectKeyChip, projectMeta } from '@/components/project/ProjectKeyChip'
import { cn } from '@/lib/cn'
import { groupProjectsByFolder, UNFILED, type ProjectGroup } from '@/lib/groupProjects'
import {
  folderDropId,
  resolveFolderMove,
  type ProjectDragData,
} from '@/lib/projectDnd'
import { type ProjectFolder } from '@/lib/projectFolders'
import { PROJECT_ROLE_LABEL, type Project } from '@/lib/projects'
import { useFolderCollapse } from '@/stores/projectFolders'

const createSchema = z.object({
  name: z.string().min(1).max(255),
  description: z.string().max(4000).optional(),
})

type CreateFormValues = z.infer<typeof createSchema>

function ProjectCard({
  project,
  folders,
  onMove,
}: {
  project: Project
  folders: ProjectFolder[]
  onMove: (folderId: string | null) => void
}) {
  const [moveOpen, setMoveOpen] = useState(false)
  // Перетаскивать может только тот, кто может и переложить через меню.
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: project.id,
    disabled: !project.can_manage,
    data: { projectId: project.id, folderId: project.folder_id },
  })
  // transform ОБЯЗАТЕЛЕН (паттерн CalendarTaskBar): без него карточка не
  // едет за курсором, а её rect не смещается — collision detection не видит
  // папку под указателем и дроп молча не срабатывает.
  const style: CSSProperties = {
    transform: CSS.Translate.toString(transform),
    zIndex: isDragging ? 20 : undefined,
  }

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={cn('group relative', isDragging && 'opacity-60')}
    >
      <Link
        to={`/projects/${project.id}`}
        // У <a href> есть нативный HTML5-drag, конфликтующий с dnd-kit.
        draggable={false}
        {...attributes}
        {...listeners}
        className="glass flex flex-col gap-2 p-5 transition-colors hover:bg-surface focus:outline-none focus-visible:ring-2 focus-visible:ring-amber"
      >
        <div className="flex items-center gap-3">
          <ProjectKeyChip project={project} size="lg" />
          <div className="min-w-0 flex-1">
            <h3 className="truncate font-display text-base font-semibold text-text">
              {project.name}
            </h3>
            <p className="truncate text-[13px] text-text2">
              {projectMeta(project) ?? project.key}
            </p>
          </div>
          {project.archived_at && <Badge variant="secondary">архив</Badge>}
          {project.my_role && project.my_role !== 'viewer' && (
            <Badge variant="secondary">{PROJECT_ROLE_LABEL[project.my_role]}</Badge>
          )}
        </div>
        {project.description && (
          <p className="line-clamp-2 text-sm text-text2">{project.description}</p>
        )}
      </Link>

      {project.can_manage && (
        <div className="absolute right-2 top-2">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                // Иначе клик всплывёт в <Link> и уведёт со страницы.
                onClick={(e) => {
                  e.preventDefault()
                  e.stopPropagation()
                }}
                onPointerDown={(e) => e.stopPropagation()}
                className="rounded p-1 text-text2 transition-opacity hover:bg-glass hover:text-text focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60 md:opacity-0 md:group-hover:opacity-100"
                aria-label="Действия с проектом"
              >
                <MoreHorizontal className="h-4 w-4" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onSelect={() => setMoveOpen(true)}>
                <Folder className="mr-2 h-4 w-4" />
                Переместить в папку…
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      )}

      <MoveToFolderDialog
        open={moveOpen}
        onOpenChange={setMoveOpen}
        folders={folders}
        current={project.folder_id}
        onPick={(folderId) => {
          onMove(folderId)
          setMoveOpen(false)
        }}
      />
    </div>
  )
}

/**
 * Меню-путь перемещения — ОСНОВНОЙ, drag-n-drop поверх него дополнение:
 * на мобильном TouchSensor конкурирует со скроллом, а KeyboardSensor в
 * проекте не используется нигде, то есть DnD недоступен с клавиатуры.
 */
function MoveToFolderDialog({
  open,
  onOpenChange,
  folders,
  current,
  onPick,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
  folders: ProjectFolder[]
  current: string | null
  onPick: (folderId: string | null) => void
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Переместить в папку</DialogTitle>
          <DialogDescription>
            Папки общие для компании — раскладку увидят все участники.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-1">
          {[{ id: null, name: 'Без папки' }, ...folders].map((f) => (
            <button
              key={f.id ?? UNFILED}
              type="button"
              onClick={() => onPick(f.id)}
              className={cn(
                'flex w-full items-center gap-2 rounded-md px-2 py-2 text-left text-sm transition-colors hover:bg-glass',
                (f.id ?? null) === current ? 'text-amber' : 'text-text2',
              )}
            >
              <Folder className="h-4 w-4 shrink-0" />
              <span className="flex-1 truncate">{f.name}</span>
              {(f.id ?? null) === current && <span className="text-xs">текущая</span>}
            </button>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  )
}

function FolderSection({
  group,
  folders,
  canManage,
  onMoveProject,
}: {
  group: ProjectGroup
  folders: ProjectFolder[]
  canManage: boolean
  onMoveProject: (projectId: string, folderId: string | null) => void
}) {
  const folder = group.folder
  const { setNodeRef, isOver } = useDroppable({ id: folderDropId(folder?.id ?? null) })
  const collapsed = useFolderCollapse((s) =>
    folder ? (s.collapsed[folder.id] ?? false) : false,
  )
  const toggle = useFolderCollapse((s) => s.toggle)

  const rename = useRenameFolder()
  const reorder = useReorderFolders()
  const remove = useDeleteFolder()
  const [renaming, setRenaming] = useState(false)
  const [draft, setDraft] = useState(folder?.name ?? '')
  const [confirmDelete, setConfirmDelete] = useState(false)

  // Тенант без папок видит ровно сегодняшний плоский список — без заголовков.
  const headless = folder === null && folders.length === 0
  if (headless && group.projects.length === 0) return null

  const move = (dir: -1 | 1) => {
    if (!folder) return
    const idx = folders.findIndex((f) => f.id === folder.id)
    const next = idx + dir
    if (idx < 0 || next < 0 || next >= folders.length) return
    const ids = folders.map((f) => f.id)
    const [moved] = ids.splice(idx, 1)
    ids.splice(next, 0, moved!)
    reorder.mutate(ids)
  }

  const submitRename = () => {
    const trimmed = draft.trim()
    setRenaming(false)
    if (folder && trimmed && trimmed !== folder.name) {
      rename.mutate({ id: folder.id, name: trimmed })
    }
  }

  return (
    <section ref={setNodeRef} className="space-y-3">
      {!headless && (
        <div
          className={cn(
            'flex items-center gap-2 rounded-md px-1 py-1 transition-colors',
            isOver && 'bg-amber/5 ring-1 ring-amber/40',
          )}
        >
          {renaming && folder ? (
            <input
              autoFocus
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onBlur={submitRename}
              onKeyDown={(e) => {
                if (e.key === 'Enter') submitRename()
                if (e.key === 'Escape') setRenaming(false)
              }}
              className="rounded border border-glass-border bg-glass px-2 py-1 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
            />
          ) : (
            <button
              type="button"
              onClick={() => folder && toggle(folder.id)}
              disabled={!folder}
              className="flex flex-1 items-center gap-1.5 text-left text-sm font-semibold text-text2 disabled:cursor-default"
            >
              {folder &&
                (collapsed ? (
                  <ChevronRight className="h-4 w-4 shrink-0 text-text2" />
                ) : (
                  <ChevronDown className="h-4 w-4 shrink-0 text-text2" />
                ))}
              <Folder className="h-4 w-4 shrink-0 text-text2" />
              <span className="truncate">{folder?.name ?? 'Без папки'}</span>
              <span className="text-xs font-normal text-text2">
                {group.projects.length}
              </span>
            </button>
          )}

          {folder && canManage && !renaming && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button
                  type="button"
                  className="rounded p-1 text-text2 hover:bg-glass hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
                  aria-label={`Действия с папкой ${folder.name}`}
                >
                  <MoreHorizontal className="h-4 w-4" />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem
                  onSelect={() => {
                    setDraft(folder.name)
                    // Radix возвращает фокус на триггер после закрытия —
                    // без отложенного монтирования autoFocus не сработает.
                    setTimeout(() => setRenaming(true), 0)
                  }}
                >
                  Переименовать
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => move(-1)}>Выше</DropdownMenuItem>
                <DropdownMenuItem onSelect={() => move(1)}>Ниже</DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem destructive onSelect={() => setConfirmDelete(true)}>
                  Удалить папку
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </div>
      )}

      {!collapsed &&
        (group.projects.length > 0 ? (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
            {group.projects.map((p) => (
              <ProjectCard
                key={p.id}
                project={p}
                folders={folders}
                onMove={(folderId) => onMoveProject(p.id, folderId)}
              />
            ))}
          </div>
        ) : (
          !headless && (
            <p className="rounded-lg border border-dashed border-glass-border px-4 py-6 text-center text-sm text-text2">
              Пусто — перетащите сюда проект
            </p>
          )
        ))}

      {folder && (
        <Dialog open={confirmDelete} onOpenChange={setConfirmDelete}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Удалить папку «{folder.name}»?</DialogTitle>
              <DialogDescription>
                Проекты ({group.projects.length}) останутся — они переедут в «Без
                папки».
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button variant="secondary" onClick={() => setConfirmDelete(false)}>
                Отмена
              </Button>
              <Button
                onClick={() => {
                  remove.mutate(folder.id)
                  setConfirmDelete(false)
                }}
              >
                Удалить
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </section>
  )
}

function CreateProjectDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
}) {
  const create = useCreateProject()
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<CreateFormValues>({ resolver: zodResolver(createSchema) })

  const onSubmit = handleSubmit(async (values) => {
    try {
      const project = await create.mutateAsync({
        name: values.name,
        description: values.description || undefined,
      })
      toast.success(`Проект ${project.key} создан`)
      reset()
      onOpenChange(false)
    } catch {
      // тост показывает глобальный onError мутаций
    }
  })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form onSubmit={onSubmit}>
          <DialogHeader>
            <DialogTitle>Новый проект</DialogTitle>
            <DialogDescription>
              Короткий ключ (HUB-123 в идентификаторах задач) подберётся автоматически из названия.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="name">Название</Label>
              <Input
                id="name"
                placeholder="Signaris Hub"
                autoFocus
                {...register('name')}
              />
              {errors.name && <p className="text-xs text-red">{errors.name.message}</p>}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="description">Описание (опционально)</Label>
              <Textarea
                id="description"
                rows={3}
                placeholder="Что делает этот проект?"
                {...register('description')}
              />
              {errors.description && (
                <p className="text-xs text-red">{errors.description.message}</p>
              )}
            </div>
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="secondary"
              onClick={() => onOpenChange(false)}
              disabled={isSubmitting}
            >
              Отмена
            </Button>
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? 'Создаём…' : 'Создать'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

export function ProjectListPage() {
  const [createOpen, setCreateOpen] = useState(false)
  const [createFolderOpen, setCreateFolderOpen] = useState(false)
  const { data, isLoading, error } = useProjects()
  const foldersQuery = useProjectFolders()
  const setFolder = useSetProjectFolder()

  const folders = useMemo(() => foldersQuery.data?.folders ?? [], [foldersQuery.data])
  const groups = useMemo(
    () => groupProjectsByFolder(data ?? [], folders),
    [data, folders],
  )

  // distance:5 — благодаря ему обычный клик по карточке по-прежнему
  // открывает проект, а не начинает перетаскивание.
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 200, tolerance: 5 } }),
  )

  const onDragEnd = (e: DragEndEvent) => {
    const move = resolveFolderMove(
      e.active.data.current as ProjectDragData | undefined,
      e.over?.id,
    )
    if (move) setFolder.mutate(move)
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <div className="flex items-center justify-between gap-4">
        {/* min-w-0 + truncate: сжиматься должен заголовок, а не кнопки —
            иначе на узком экране текст внутри кнопок переносится при
            фиксированной высоте h-9 и вылезает за их границы. */}
        <div className="min-w-0">
          <h1 className="font-display text-2xl">Проекты</h1>
          <p className="truncate text-sm text-text2">
            Командные пространства с задачами, секциями и участниками.
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {foldersQuery.data?.can_manage && (
            <>
              {/* До sm — иконка: две текстовые кнопки в 390px не помещаются. */}
              <Button
                variant="secondary"
                size="icon"
                className="sm:hidden"
                onClick={() => setCreateFolderOpen(true)}
                aria-label="Новая папка"
              >
                <FolderPlus className="h-4 w-4" />
              </Button>
              <Button
                variant="secondary"
                className="hidden whitespace-nowrap sm:inline-flex"
                onClick={() => setCreateFolderOpen(true)}
              >
                <FolderPlus className="h-4 w-4" />
                Новая папка
              </Button>
            </>
          )}
          <Button
            className="whitespace-nowrap"
            onClick={() => setCreateOpen(true)}
          >
            <Plus className="h-4 w-4" />
            <span className="hidden sm:inline">Новый проект</span>
            <span className="sm:hidden">Проект</span>
          </Button>
        </div>
      </div>

      {foldersQuery.isError && (
        <p className="text-sm text-red">
          Не удалось загрузить папки — раскладка по папкам временно недоступна.{' '}
          <button
            type="button"
            onClick={() => void foldersQuery.refetch()}
            className="underline hover:text-red/80"
          >
            Повторить
          </button>
        </p>
      )}

      {isLoading && <SkeletonRows rows={5} rowClassName="h-14" />}
      {error && (
        <p className="text-red">
          Не удалось загрузить проекты — {(error as Error).message}
        </p>
      )}
      {data && data.length === 0 && (
        <div className="glass flex flex-col items-center gap-3 p-12 text-center">
          <p className="text-text2">У вас пока нет проектов в Hub.</p>
          <Button onClick={() => setCreateOpen(true)}>
            <Plus className="h-4 w-4" />
            Создать первый проект
          </Button>
        </div>
      )}
      {data && data.length > 0 && (
        <DndContext sensors={sensors} onDragEnd={onDragEnd}>
          <div
            className={cn(
              'space-y-6',
              setFolder.isPending && 'pointer-events-none opacity-60',
            )}
          >
            {groups.map((group) => (
              <FolderSection
                key={group.folder?.id ?? UNFILED}
                group={group}
                folders={folders}
                canManage={foldersQuery.data?.can_manage ?? false}
                onMoveProject={(projectId, folderId) =>
                  setFolder.mutate({ projectId, folderId })
                }
              />
            ))}
          </div>
        </DndContext>
      )}

      <CreateProjectDialog open={createOpen} onOpenChange={setCreateOpen} />
      <CreateFolderDialog open={createFolderOpen} onOpenChange={setCreateFolderOpen} />
    </div>
  )
}
