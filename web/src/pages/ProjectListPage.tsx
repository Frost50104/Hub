import { zodResolver } from '@hookform/resolvers/zod'
import {
  DndContext,
  PointerSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from '@dnd-kit/core'
import { CSS } from '@dnd-kit/utilities'
import { Folder, FolderPlus, MoreHorizontal, Plus, Star } from 'lucide-react'
import { useMemo, useState, type CSSProperties, type ReactNode } from 'react'
import { useForm } from 'react-hook-form'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { z } from 'zod'

import { MobilePageHeader } from '@/components/layout/MobilePageHeader'
import { CreateFolderDialog } from '@/components/project/CreateFolderDialog'
import { ProjectKeyChip } from '@/components/project/ProjectKeyChip'
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
import { dropZoneClass } from '@/components/ui/DropZone'
import { EmptyState } from '@/components/ui/EmptyState'
import { ErrorBanner } from '@/components/ui/ErrorBanner'
import { GroupHeader } from '@/components/ui/GroupHeader'
import { Input, Textarea } from '@/components/ui/Input'
import { Label } from '@/components/ui/Label'
import { ListRow } from '@/components/ui/ListRow'
import { SheetPicker } from '@/components/ui/SheetPicker'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { useMe } from '@/hooks/useMe'
import {
  useCreateProject,
  useDeleteFolder,
  useProjectFolders,
  useProjects,
  useRenameFolder,
  useReorderFolders,
  useSetFavorite,
  useSetProjectFolder,
} from '@/hooks/useProjects'
import { cn } from '@/lib/cn'
import { dataAgeLabel } from '@/lib/dates'
import { groupProjectsByFolder, UNFILED, type ProjectGroup } from '@/lib/groupProjects'
import { folderDropId, resolveFolderMove, type ProjectDragData } from '@/lib/projectDnd'
import { type ProjectFolder } from '@/lib/projectFolders'
import { PROJECT_ROLE_LABEL, type Project } from '@/lib/projects'
import { NBSP, plural } from '@/lib/typography'
import { useFolderCollapse } from '@/stores/projectFolders'

const createSchema = z.object({
  name: z.string().min(1).max(255),
  description: z.string().max(4000).optional(),
})

type CreateFormValues = z.infer<typeof createSchema>

/** «312 задач · 48 закрыто · описание» — вторая строка проекта. */
function projectContext(project: Project): string {
  const parts: string[] = []
  if (project.task_count != null) {
    if (project.task_count === 0) parts.push('Пока нет задач')
    else {
      parts.push(plural(project.task_count, 'задача', 'задачи', 'задач'))
      if ((project.done_count ?? 0) > 0) parts.push(`${project.done_count}${NBSP}закрыто`)
    }
  }
  if (project.description) parts.push(project.description)
  return parts.join(' · ')
}

// ─── Строка проекта ──────────────────────────────────────────────────────────

function ProjectRow({
  project,
  folders,
  dndEnabled,
  isDesktop,
  onMove,
}: {
  project: Project
  folders: ProjectFolder[]
  dndEnabled: boolean
  isDesktop: boolean
  onMove: (folderId: string | null) => void
}) {
  const navigate = useNavigate()
  const setFavorite = useSetFavorite(project.id)
  const [moveOpen, setMoveOpen] = useState(false)
  // Перетаскивать может только тот, кто может и переложить через меню.
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: project.id,
    disabled: !dndEnabled || !project.can_manage,
    data: { projectId: project.id, folderId: project.folder_id } satisfies ProjectDragData,
  })
  // transform ОБЯЗАТЕЛЕН (паттерн CalendarTaskBar): без него строка не едет
  // за курсором, а её rect не смещается — collision detection не видит папку
  // под указателем и дроп молча не срабатывает.
  const style: CSSProperties = {
    transform: CSS.Translate.toString(transform),
    zIndex: isDragging ? 20 : undefined,
    position: isDragging ? 'relative' : undefined,
  }

  return (
    <div
      ref={setNodeRef}
      style={style}
      {...(dndEnabled ? attributes : {})}
      {...(dndEnabled ? listeners : {})}
      className={cn(isDragging && 'opacity-60')}
    >
      <ListRow
        onClick={() => navigate(`/projects/${project.id}`)}
        ariaLabel={project.name}
        lead={<ProjectKeyChip project={project} size="md" />}
        className={cn('last:border-b-0', isDesktop ? 'pl-4 pr-3.5' : 'pl-4 pr-1.5')}
        title={
          <>
            <span className="min-w-0 truncate">{project.name}</span>
            {/* Звезда прямо в строке: избранное переключается там, где список,
                а не только в шапке проекта. Иконка-кнопка гасит клик строки. */}
            <button
              type="button"
              aria-label={project.is_favorite ? 'Убрать из избранного' : 'В избранное'}
              aria-pressed={project.is_favorite}
              onClick={(e) => {
                e.stopPropagation()
                setFavorite.mutate(!project.is_favorite)
              }}
              onPointerDown={(e) => e.stopPropagation()}
              onKeyDown={(e) => e.stopPropagation()}
              className={cn(
                '-m-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-md transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60',
                // На телефоне hover нет — контурная звезда у каждой строки
                // превращалась в шум (QA-0821 #2): видна только у избранных,
                // добавить в избранное можно из шапки проекта.
                project.is_favorite ? 'text-amber' : 'text-text2 opacity-0 hover:text-text group-hover:opacity-100 focus-visible:opacity-100',
              )}
            >
              <Star className={cn('h-[15px] w-[15px]', project.is_favorite && 'fill-current')} />
            </button>
            {project.archived_at && <Badge variant="secondary">архив</Badge>}
            {project.my_role && project.my_role !== 'viewer' && (
              <Badge variant="secondary" className="hidden sm:inline-flex">
                {PROJECT_ROLE_LABEL[project.my_role]}
              </Badge>
            )}
          </>
        }
        context={<span className="min-w-0 truncate">{projectContext(project)}</span>}
        trailing={
          project.can_manage ? (
            <button
              type="button"
              aria-label={`Действия с проектом «${project.name}»`}
              onClick={(e) => {
                e.stopPropagation()
                setMoveOpen(true)
              }}
              onPointerDown={(e) => e.stopPropagation()}
              onKeyDown={(e) => e.stopPropagation()}
              className={cn(
                'flex shrink-0 items-center justify-center rounded-lg text-text2 transition-colors hover:bg-glass hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60',
                isDesktop ? 'h-8 w-8' : 'h-11 w-11',
              )}
            >
              <MoreHorizontal className="h-4 w-4" />
            </button>
          ) : null
        }
      />

      {/* Меню-путь перемещения — ОСНОВНОЙ, drag-n-drop поверх него дополнение:
          на мобильном TouchSensor конкурирует со скроллом, а с клавиатуры DnD
          в проекте недоступен вовсе. */}
      <SheetPicker
        open={moveOpen}
        onOpenChange={setMoveOpen}
        title={`Переместить «${project.name}»`}
        description="Папки общие на тенант, один уровень. Проекты можно и перетаскивать мышью."
        items={[{ id: UNFILED, name: 'Без папки' }, ...folders].map((f) => ({
          id: f.id,
          label: f.name,
          icon: <Folder className="h-[18px] w-[18px]" />,
          selected: (f.id === UNFILED ? null : f.id) === project.folder_id,
        }))}
        onSelect={(id) => onMove(id === UNFILED ? null : id)}
      />
    </div>
  )
}

// ─── Группа-папка ────────────────────────────────────────────────────────────

function FolderSection({
  group,
  folders,
  canManage,
  drag,
  dndEnabled,
  isDesktop,
  onMoveProject,
}: {
  group: ProjectGroup
  folders: ProjectFolder[]
  canManage: boolean
  /** null — перетаскивания сейчас нет. */
  drag: ProjectDragData | null
  dndEnabled: boolean
  isDesktop: boolean
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

  // Тенант без папок видит плоский список — без заголовков.
  const headless = folder === null && folders.length === 0
  if (headless && group.projects.length === 0) return null
  // Подсветку гасим над собственной папкой проекта — переноса там не будет.
  const isTarget = isOver && drag !== null && drag.folderId !== (folder?.id ?? null)

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

  const rows =
    group.projects.length > 0 ? (
      <div
        className={cn(
          'flex flex-col',
          isDesktop && 'overflow-hidden rounded-xl border border-glass-border bg-tint',
        )}
      >
        {group.projects.map((p) => (
          <ProjectRow
            key={p.id}
            project={p}
            folders={folders}
            dndEnabled={dndEnabled}
            isDesktop={isDesktop}
            onMove={(folderId) => onMoveProject(p.id, folderId)}
          />
        ))}
      </div>
    ) : (
      !headless && (
        <p
          className={cn(
            'px-4 py-5 text-center text-[14px] text-text2',
            isDesktop && 'rounded-xl border border-glass-border bg-tint',
          )}
        >
          {isDesktop
            ? 'Пусто — перетащите сюда проект или переложите через меню строки.'
            : 'Пусто — переложите проект через меню строки.'}
        </p>
      )
    )

  const folderMenu: ReactNode =
    // «Без папки» — не папка: её нельзя переименовать, передвинуть или удалить,
    // поэтому меню только у настоящих папок и только при can_manage.
    folder && canManage && !renaming ? (
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            className={cn(
              'flex items-center justify-center rounded-lg text-text2 hover:bg-glass hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60',
              isDesktop ? 'h-8 w-8' : 'h-11 w-11',
            )}
            aria-label={`Действия с папкой «${folder.name}»`}
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
    ) : null

  return (
    // Зона приёма — вся группа; пунктир amber/50 + фон 5%, как у колонки
    // канбана: одна модель дроп-зоны на весь трекер.
    <section
      ref={setNodeRef}
      className={cn(
        'flex flex-col',
        isDesktop ? cn('gap-1.5 rounded-xl p-0.5', dropZoneClass(isTarget)) : dropZoneClass(isTarget, 'rounded-none border-x-0'),
      )}
    >
      {!headless &&
        (renaming && folder ? (
          <div className="px-1.5 py-1">
            <input
              autoFocus
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onBlur={submitRename}
              onKeyDown={(e) => {
                if (e.key === 'Enter') submitRename()
                if (e.key === 'Escape') setRenaming(false)
              }}
              className="h-8 rounded-md border border-glass-border bg-glass px-2 text-[14px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
            />
          </div>
        ) : (
          <GroupHeader
            variant={isDesktop ? 'desktop' : 'mobile'}
            title={folder?.name ?? 'Без папки'}
            count={group.projects.length}
            collapsed={collapsed}
            onToggle={folder ? () => toggle(folder.id) : undefined}
            dropActive={isTarget}
            actions={folderMenu}
          />
        ))}

      {!collapsed && rows}

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

// ─── Создание проекта ────────────────────────────────────────────────────────

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

/** Скелетон: 5 строк 64px, ширины чередуются, без пульсации. */
const SKELETON_WIDTHS = [88, 64, 76, 52, 84]

function ProjectsSkeleton({ isDesktop }: { isDesktop: boolean }) {
  return (
    <div
      aria-hidden
      className={cn(isDesktop && 'overflow-hidden rounded-xl border border-glass-border bg-tint')}
    >
      {SKELETON_WIDTHS.map((w, i) => (
        <div key={i} className="flex h-16 items-center gap-3 border-b border-hair px-4 last:border-b-0">
          <span className="h-9 w-9 shrink-0 rounded-[9px] bg-surface" />
          <span className="flex min-w-0 flex-1 flex-col gap-[7px]">
            <span className="h-3.5 rounded-[5px] bg-surface" style={{ width: `${w}%` }} />
            <span className="h-[11px] w-[140px] rounded bg-surface" />
          </span>
        </div>
      ))}
    </div>
  )
}

// ─── Страница ────────────────────────────────────────────────────────────────

/**
 * `/projects` — строки 64px по папкам (не плитки): то же решение, что в
 * списке задач — вертикальное сканирование по одной колонке вместо чтения
 * плитки за плиткой. Перетаскивание — только на десктопе (на телефоне
 * TouchSensor конкурирует со скроллом, путь — меню строки).
 */
export function ProjectListPage() {
  const isDesktop = useIsDesktop()
  const [createOpen, setCreateOpen] = useState(false)
  const [createFolderOpen, setCreateFolderOpen] = useState(false)
  const projects = useProjects()
  const foldersQuery = useProjectFolders()
  const setFolder = useSetProjectFolder()
  const [drag, setDrag] = useState<ProjectDragData | null>(null)

  const data = projects.data
  const folders = useMemo(() => foldersQuery.data?.folders ?? [], [foldersQuery.data])
  const groups = useMemo(
    () => groupProjectsByFolder(data ?? [], folders),
    [data, folders],
  )
  const canManageFolders = foldersQuery.data?.can_manage ?? false
  // Право создавать проекты считает сервер (admin или офис/ТУ/франчайзи);
  // линейному сотруднику кнопок нет — он попадает в проекты по приглашению.
  const canCreateProjects = useMe().data?.can_create_projects ?? false
  const dndEnabled = isDesktop && folders.length > 0

  // distance:5 — обычный клик по строке по-прежнему открывает проект.
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }))

  const onDragStart = (e: DragStartEvent) =>
    setDrag((e.active.data.current as ProjectDragData | undefined) ?? null)
  const onDragEnd = (e: DragEndEvent) => {
    setDrag(null)
    const move = resolveFolderMove(
      e.active.data.current as ProjectDragData | undefined,
      e.over?.id,
    )
    if (move) setFolder.mutate(move)
  }

  const countLine =
    data && data.length > 0
      ? [
          plural(data.length, 'проект', 'проекта', 'проектов'),
          folders.length > 0 ? plural(folders.length, 'папка', 'папки', 'папок') : null,
        ]
          .filter(Boolean)
          .join(' · ')
      : null

  const createButtons = !canCreateProjects ? null : isDesktop ? (
    <div className="flex shrink-0 items-center gap-2">
      {canManageFolders && (
        <Button variant="secondary" size="sm" onClick={() => setCreateFolderOpen(true)}>
          <FolderPlus className="h-[15px] w-[15px]" />
          Новая папка
        </Button>
      )}
      <Button size="sm" onClick={() => setCreateOpen(true)}>
        <Plus className="h-[15px] w-[15px]" strokeWidth={2.4} />
        Новый проект
      </Button>
    </div>
  ) : (
    // На 390px две текстовые кнопки не помещаются — иконки 44px.
    <div className="flex shrink-0 items-center gap-1">
      {canManageFolders && (
        <button
          type="button"
          onClick={() => setCreateFolderOpen(true)}
          aria-label="Новая папка"
          className="-m-1 flex h-11 w-11 items-center justify-center rounded-lg text-text2 hover:bg-glass hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
        >
          <FolderPlus className="h-[21px] w-[21px]" strokeWidth={1.8} />
        </button>
      )}
      <button
        type="button"
        onClick={() => setCreateOpen(true)}
        aria-label="Новый проект"
        className="-m-1 flex h-11 w-11 items-center justify-center rounded-lg text-text hover:bg-glass focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
      >
        <Plus className="h-[22px] w-[22px]" strokeWidth={2.2} />
      </button>
    </div>
  )

  const body = (
    <>
      {/* Ошибка папок и ошибка проектов независимы: если папки не загрузились,
          список остаётся плоским, а не пустым. */}
      {foldersQuery.isError && (
        <ErrorBanner
          title="Не удалось загрузить папки"
          text="Раскладка по папкам временно недоступна — проекты ниже показаны одним списком."
          actionLabel="Повторить"
          onAction={() => void foldersQuery.refetch()}
        />
      )}

      {projects.isLoading && <ProjectsSkeleton isDesktop={isDesktop} />}

      {projects.isError && (
        <EmptyState
          tone="error"
          layout="card"
          title="Не удалось загрузить проекты"
          text={(projects.error as Error).message || 'Сервер ответил ошибкой.'}
          meta={dataAgeLabel(projects.dataUpdatedAt)}
          cta="Повторить"
          onCta={() => void projects.refetch()}
        />
      )}

      {data && data.length === 0 && (
        <EmptyState
          layout="card"
          icon={<Folder className="h-[26px] w-[26px]" strokeWidth={1.6} />}
          title="У вас пока нет проектов в Hub"
          text={
            canCreateProjects
              ? 'Проект — это задачи, секции и участники. Папки появятся, когда проектов станет много.'
              : 'Проект — это задачи, секции и участники. Вас добавит в проект руководитель или администратор.'
          }
          cta={canCreateProjects ? 'Создать первый проект' : undefined}
          onCta={canCreateProjects ? () => setCreateOpen(true) : undefined}
        />
      )}

      {data && data.length > 0 && (
        <DndContext
          sensors={sensors}
          onDragStart={onDragStart}
          onDragEnd={onDragEnd}
          onDragCancel={() => setDrag(null)}
        >
          <div
            className={cn(
              'flex flex-col',
              isDesktop ? 'gap-[18px]' : 'gap-0',
              setFolder.isPending && 'pointer-events-none opacity-60',
            )}
          >
            {groups.map((group) => (
              <FolderSection
                key={group.folder?.id ?? UNFILED}
                group={group}
                folders={folders}
                canManage={canManageFolders}
                drag={drag}
                dndEnabled={dndEnabled}
                isDesktop={isDesktop}
                onMoveProject={(projectId, folderId) =>
                  setFolder.mutate({ projectId, folderId })
                }
              />
            ))}
          </div>
        </DndContext>
      )}
    </>
  )

  return (
    <>
      {isDesktop ? (
        <div className="mx-auto flex max-w-[960px] flex-col gap-[18px] px-6 pb-10 pt-7">
          <header className="flex flex-wrap items-end justify-between gap-3">
            <div className="min-w-0">
              <h1 className="font-display text-[24px] font-bold leading-[1.2] text-text">
                Проекты
              </h1>
              <p className="mt-[5px] text-[15px] text-text2">
                Командные пространства с задачами, секциями и участниками.
              </p>
            </div>
            {createButtons}
          </header>
          {countLine && <p className="-mt-2 text-[13px] text-text2">{countLine}</p>}
          {body}
        </div>
      ) : (
        <div className="flex flex-col pb-6">
          <MobilePageHeader title="Проекты" trailing={createButtons} className="pb-2" />
          {countLine && <p className="px-4 pb-2 text-[14px] text-text2">{countLine}</p>}
          {/* px-4 у карточек-состояний; строки папок тянутся во всю ширину сами. */}
          <div className={cn('flex flex-col gap-4', (projects.isError || (data && data.length === 0) || foldersQuery.isError || projects.isLoading) && 'px-4')}>
            {body}
          </div>
        </div>
      )}

      <CreateProjectDialog open={createOpen} onOpenChange={setCreateOpen} />
      <CreateFolderDialog open={createFolderOpen} onOpenChange={setCreateFolderOpen} />
    </>
  )
}
