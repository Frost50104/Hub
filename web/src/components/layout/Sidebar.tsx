import {
  CheckSquare,
  ChevronDown,
  ChevronRight,
  CircleCheck,
  Folder,
  FolderKanban,
  FolderPlus,
  Home,
  Inbox,
  LogOut,
  Plus,
  Settings,
  Sparkles,
  Star,
} from 'lucide-react'
import {
  DndContext,
  DragOverlay,
  PointerSensor,
  TouchSensor,
  pointerWithin,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from '@dnd-kit/core'
import { useState } from 'react'
import { NavLink, Link, useNavigate } from 'react-router-dom'
import { toast } from 'sonner'

import { SidebarSearch } from './SidebarSearch'
import { SpaceSwitcher } from './SpaceSwitcher'
import { CreateFolderDialog } from '@/components/project/CreateFolderDialog'
import { CreateTaskDialog } from '@/components/task/CreateTaskDialog'
import { Avatar } from '@/components/ui/Avatar'
import { SkeletonRows } from '@/components/ui/Skeleton'
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
  DropdownMenuTrigger,
} from '@/components/ui/DropdownMenu'
import { Input, Textarea } from '@/components/ui/Input'
import { Label } from '@/components/ui/Label'
import { useMe } from '@/hooks/useMe'
import { useUnreadCount } from '@/hooks/useNotifications'
import {
  useCreateProject,
  useProjectFolders,
  useProjects,
  useSetProjectFolder,
} from '@/hooks/useProjects'
import { authClient } from '@/lib/auth'
import { useTheme } from '@/lib/theme'
import { ProjectKeyChip } from '@/components/project/ProjectKeyChip'
import { cn } from '@/lib/cn'
import { HUB_ROLE_BADGE } from '@/lib/learn'
import {
  groupProjectsByFolder,
  UNFILED,
  type ProjectGroup,
} from '@/lib/groupProjects'
import {
  folderDropId,
  projectDragId,
  resolveFolderMove,
  type ProjectDragData,
} from '@/lib/projectDnd'
import { type Project } from '@/lib/projects'
import { useFolderCollapse } from '@/stores/projectFolders'

const NAV_ITEMS = [
  { to: '/', label: 'Главная', icon: Home, end: true, badge: false },
  { to: '/my', label: 'Мои задачи', icon: CheckSquare, end: false, badge: false },
  { to: '/assistant', label: 'Ассистент', icon: Sparkles, end: false, badge: false },
  { to: '/inbox', label: 'Входящие', icon: Inbox, end: false, badge: true },
] as const

/** Данные драга сайдбара = общий контракт + снапшот для DragOverlay.
 *  Снапшот, а не поиск по useProjects(): Sidebar на список не подписан. */
interface SidebarDragData extends ProjectDragData {
  name: string
  projectKey: string
}

/** Превью под курсором. bg-bg-alt, а не bg-surface/95: токены в
 *  tailwind.config объявлены сырыми var() без <alpha-value>, слэш-опасити
 *  на них не компилируется. */
function ProjectDragPreview({ drag }: { drag: SidebarDragData }) {
  return (
    <div className="flex h-full w-full items-center gap-2 rounded-md border border-glass-border bg-bg-alt px-2 py-1.5 text-sm text-text shadow-glass">
      <ProjectKeyChip
        project={{ key: drag.projectKey, is_favorite: false }}
        size="sm"
      />
      <span className="truncate">{drag.name}</span>
    </div>
  )
}

function FolderNavGroup({
  group,
  drag,
  dndEnabled,
  onItemClick,
}: {
  group: ProjectGroup
  /** null — перетаскивания сейчас нет. */
  drag: SidebarDragData | null
  dndEnabled: boolean
  onItemClick?: () => void
}) {
  const folder = group.folder
  const dragging = drag !== null
  // Хуки — строго до любых return (rules-of-hooks).
  const { setNodeRef, isOver } = useDroppable({
    id: folderDropId(folder?.id ?? null),
    data: { folderName: folder?.name ?? 'Без папки' },
  })
  const collapsed = useFolderCollapse((s) =>
    folder ? (s.collapsed[folder.id] ?? false) : false,
  )
  const toggle = useFolderCollapse((s) => s.toggle)

  // Пустые ИМЕНОВАННЫЕ папки показываем всегда: папку можно создать прямо
  // отсюда, и она обязана быть видна там, где создана, — иначе это читается
  // как «создал, а её нет». Прячем только пустую группу «Без папки»: её
  // заголовок с нулём — чистый шум (во время драга он нужен как зона
  // «вынуть из папки»).
  if (!folder && group.projects.length === 0 && !dragging) return null

  // Проекты без папки — плоскими пунктами: фальшивый заголовок «Без папки»
  // в узкой колонке читается хуже простого списка. Во время драга заголовок
  // нужен как зона «вынуть из папки».
  const headless = !folder && !dragging
  // Подсветку гасим над собственной папкой проекта — переноса там не будет.
  const isTarget = isOver && drag?.folderId !== (folder?.id ?? null)

  const items = (
    <ul className={cn('space-y-0.5', folder && 'pl-3')}>
      {group.projects.map((p) => (
        <ProjectLinkItem
          key={p.id}
          project={p}
          scope="group"
          dndEnabled={dndEnabled && p.can_manage}
          isSource={drag?.projectId === p.id}
          onItemClick={onItemClick}
        />
      ))}
    </ul>
  )

  if (headless) return <div ref={setNodeRef}>{items}</div>

  return (
    <div
      ref={setNodeRef}
      // py-1 вместо зазора у контейнера: pointerWithin требует, чтобы зоны
      // стыковались, иначе между ними появляются мёртвые полосы.
      className={cn(
        'rounded-md py-1 transition-colors',
        isTarget && 'bg-amber/5 ring-1 ring-amber/40',
      )}
    >
      {folder ? (
        <button
          type="button"
          onClick={() => toggle(folder.id)}
          className="flex w-full items-center gap-1 px-2 py-0.5 text-left text-[12px] font-semibold uppercase tracking-wider text-text2 hover:text-text2"
        >
          {collapsed ? (
            <ChevronRight className="h-3 w-3 shrink-0" />
          ) : (
            <ChevronDown className="h-3 w-3 shrink-0" />
          )}
          <span className="truncate">{folder.name}</span>
          <span className="ml-auto font-normal normal-case">
            {group.projects.length}
          </span>
        </button>
      ) : (
        <div className="flex w-full items-center gap-1 px-2 py-0.5 text-[12px] font-semibold uppercase tracking-wider text-text2">
          {/* спейсер вместо шеврона — текст на одной вертикали с папками */}
          <span className="w-3 shrink-0" />
          <span className="truncate">Без папки</span>
          <span className="ml-auto font-normal normal-case">
            {group.projects.length}
          </span>
        </div>
      )}
      {!collapsed && items}
      {dragging && !collapsed && group.projects.length === 0 && (
        <p className="mx-2 mt-0.5 rounded-md border border-dashed border-glass-border px-2 py-1.5 text-[12px] text-text2">
          Перенести сюда
        </p>
      )}
    </div>
  )
}

function ProjectsList({
  drag,
  onItemClick,
}: {
  drag: SidebarDragData | null
  onItemClick?: () => void
}) {
  const { data, isLoading, isError, refetch } = useProjects()
  const foldersQuery = useProjectFolders()
  const folders = foldersQuery.data?.folders ?? []
  const groups = groupProjectsByFolder(data ?? [], folders)
  // Папок нет — тащить некуда, аффорданс не даём.
  const dndEnabled = folders.length > 0

  if (isLoading) return <SkeletonRows rows={4} rowClassName="h-7" className="px-2" />
  if (isError) {
    return (
      <button
        type="button"
        onClick={() => void refetch()}
        className="px-3 py-1 text-left text-xs text-red hover:underline"
      >
        Не удалось загрузить — повторить
      </button>
    )
  }
  if (!data || data.length === 0) {
    return <p className="px-3 py-1 text-xs text-text2">Нет проектов</p>
  }
  const favorites = data.filter((p) => p.is_favorite)
  return (
    <>
      {favorites.length > 0 && (
        <>
          {/* Избранное — персональный сквозной срез, папки его не касаются. */}
          <p className="flex items-center gap-1 px-2 pb-0.5 text-[12px] font-semibold uppercase tracking-wider text-text2">
            <Star className="h-3 w-3 fill-amber text-amber" /> Избранное
          </p>
          <ul className="space-y-0.5 pb-2">
            {favorites.map((p) => (
              <ProjectLinkItem
                key={p.id}
                project={p}
                scope="fav"
                dndEnabled={dndEnabled && p.can_manage}
                isSource={drag?.projectId === p.id}
                onItemClick={onItemClick}
              />
            ))}
          </ul>
        </>
      )}
      {/* Без space-y: зазор перенесён внутрь зон (py-1), иначе pointerWithin
          даёт мёртвые полосы между дропзонами. */}
      <div>
        {groups.map((group) => (
          <FolderNavGroup
            key={group.folder?.id ?? UNFILED}
            group={group}
            drag={drag}
            dndEnabled={dndEnabled}
            onItemClick={onItemClick}
          />
        ))}
      </div>
      {/* Сбой папок раньше был молчаливым: список просто оставался плоским,
          и это неотличимо от «фичи нет» — ровно та жалоба, с которой пришёл
          тестировщик. */}
      {foldersQuery.isError && (
        <button
          type="button"
          onClick={() => void foldersQuery.refetch()}
          className="px-3 py-1 text-left text-xs text-red hover:underline"
        >
          Папки не загрузились — повторить
        </button>
      )}
    </>
  )
}

function ProjectLinkItem({
  project,
  scope,
  dndEnabled,
  isSource,
  onItemClick,
}: {
  project: Project
  /** Часть dnd-id: один проект рендерится и в «Избранном», и в своей папке. */
  scope: 'fav' | 'group'
  dndEnabled: boolean
  /** Перетаскивают именно этот проект — гасим ОБА его вхождения. */
  isSource: boolean
  onItemClick?: () => void
}) {
  const { attributes, listeners, setNodeRef } = useDraggable({
    id: projectDragId(scope, project.id),
    disabled: !dndEnabled,
    data: {
      projectId: project.id,
      folderId: project.folder_id,
      name: project.name,
      projectKey: project.key,
    } satisfies SidebarDragData,
    // Дефолт useDraggable — role="button": на <a> это ломает семантику ссылки.
    attributes: {
      role: 'link',
      roleDescription: 'проект, можно перетащить в папку',
    },
  })

  return (
    // transform НЕ ставим: перетаскиваемое рисует DragOverlay, а transform
    // внутри overflow-y-auto контейнера обрезался бы по границе колонки.
    <li ref={setNodeRef} className={cn(isSource && 'opacity-40')}>
      <NavLink
        to={`/projects/${project.id}`}
        onClick={onItemClick}
        // У <a href> есть нативный HTML5-drag, конфликтующий с dnd-kit.
        draggable={false}
        {...(dndEnabled ? attributes : {})}
        {...listeners}
        className={({ isActive }) =>
          cn(
            'group flex h-[34px] select-none items-center gap-[9px] rounded-[9px] px-2 text-[14px] transition-colors',
            isActive
              ? 'bg-surface font-semibold text-text'
              : 'font-medium text-text2 hover:bg-glass hover:text-text',
          )
        }
      >
        <ProjectKeyChip project={project} size="sm" />
        <span className="truncate">{project.name}</span>
      </NavLink>
    </li>
  )
}

function CreateProjectFromSidebar({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
}) {
  const create = useCreateProject()
  const nav = useNavigate()
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = name.trim()
    if (!trimmed) return
    try {
      const project = await create.mutateAsync({
        name: trimmed,
        description: description.trim() || undefined,
      })
      toast.success(`Проект ${project.key} создан`)
      setName('')
      setDescription('')
      onOpenChange(false)
      nav(`/projects/${project.id}`)
    } catch {
      // тост показывает глобальный onError мутаций
    }
  }
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form onSubmit={submit}>
          <DialogHeader>
            <DialogTitle>Новый проект</DialogTitle>
            <DialogDescription>
              Короткий ключ для задач (HUB-123) подберётся автоматически из названия.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="sidebar-project-name">Название</Label>
              <Input
                id="sidebar-project-name"
                placeholder="Маркетинг"
                autoFocus
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="sidebar-project-desc">Описание (опционально)</Label>
              <Textarea
                id="sidebar-project-desc"
                rows={2}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="secondary"
              onClick={() => onOpenChange(false)}
              disabled={create.isPending}
            >
              Отмена
            </Button>
            <Button type="submit" disabled={create.isPending || !name.trim()}>
              {create.isPending ? 'Создаём…' : 'Создать'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

export interface SidebarProps {
  /** Called when a navigation entry is clicked (used to close the mobile drawer). */
  onItemClick?: () => void
}

export function Sidebar({ onItemClick }: SidebarProps = {}) {
  const theme = useTheme((s) => s.theme)
  const me = useMe()
  const unread = useUnreadCount()
  const unreadCount = unread.data?.count ?? 0
  const [createProjectOpen, setCreateProjectOpen] = useState(false)
  const [createTaskOpen, setCreateTaskOpen] = useState(false)
  const [createFolderOpen, setCreateFolderOpen] = useState(false)
  // Тот же queryKey, что читает ProjectsList — TanStack дедуплицирует,
  // лишнего запроса нет. Права считает сервер, копии правила тут не заводим.
  const foldersCanManage = useProjectFolders().data?.can_manage ?? false
  const [drag, setDrag] = useState<SidebarDragData | null>(null)
  const setFolder = useSetProjectFolder()

  // distance:5 — обычный клик по NavLink (жест короче) по-прежнему открывает
  // проект; после успешного драга dnd-kit сам подавляет click.
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 200, tolerance: 5 } }),
  )

  const onDragStart = (e: DragStartEvent) =>
    setDrag((e.active.data.current as SidebarDragData | undefined) ?? null)

  const onDragEnd = (e: DragEndEvent) => {
    setDrag(null)
    const move = resolveFolderMove(
      e.active.data.current as ProjectDragData | undefined,
      e.over?.id,
    )
    if (!move) return
    const folderName = (e.over?.data.current as { folderName?: string } | undefined)
      ?.folderName
    setFolder.mutate(move, {
      onSuccess: () =>
        toast.success(`Проект перенесён в «${folderName ?? 'Без папки'}»`),
    })
  }

  return (
    <DndContext
      sensors={sensors}
      // pointerWithin, а не дефолтный rectIntersection: зоны — вертикальный
      // стек переменной высоты, и на границе двух групп выбор «по площади
      // перекрытия» превращается в лотерею. Плюс вне зон он не возвращает
      // ничего — случайный дроп мимо ничего не двигает.
      collisionDetection={pointerWithin}
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      // Escape посреди жеста: без этого drag завис бы, а пустые папки
      // остались бы висеть навсегда.
      onDragCancel={() => setDrag(null)}
    >
    <aside className="glass flex h-screen w-[280px] shrink-0 flex-col gap-4 p-4 md:h-[calc(100vh-1.5rem)] md:w-[260px]">
      <Link to="/" onClick={onItemClick} className="flex items-center gap-2 px-1">
        <img
          src={
            theme === 'light'
              ? '/brand/signaris-horizontal-on-light.svg'
              : '/brand/signaris-horizontal-on-dark.svg'
          }
          alt="Signaris"
          className="h-6"
        />
        <span className="font-display text-lg font-black leading-none tracking-tight">
          Hub
        </span>
        {me.data?.hub_role && (
          <span className="ml-1 text-[12px] font-semibold uppercase tracking-widest text-text2">
            {HUB_ROLE_BADGE[me.data.hub_role]}
          </span>
        )}
      </Link>

      <SpaceSwitcher />

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button className="w-full justify-center">
            <Plus className="h-4 w-4" />
            Создать
            <ChevronDown className="h-3.5 w-3.5 opacity-70" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-[228px]">
          <DropdownMenuItem onSelect={() => setCreateTaskOpen(true)}>
            <CircleCheck className="mr-2 h-4 w-4" />
            Задача
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={() => setCreateProjectOpen(true)}>
            <FolderKanban className="mr-2 h-4 w-4" />
            Проект
          </DropdownMenuItem>
          {foldersCanManage && (
            <DropdownMenuItem onSelect={() => setCreateFolderOpen(true)}>
              <FolderPlus className="mr-2 h-4 w-4" />
              Папка
            </DropdownMenuItem>
          )}
        </DropdownMenuContent>
      </DropdownMenu>

      <SidebarSearch />

      <nav className="flex flex-col gap-0.5">
        {NAV_ITEMS.map(({ to, label, icon: Icon, end, badge }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            onClick={onItemClick}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-2 rounded-md px-2 py-1.5 text-sm font-medium transition-colors',
                isActive
                  ? 'bg-surface text-text'
                  : 'text-text2 hover:bg-glass hover:text-text',
              )
            }
          >
            <Icon className="h-4 w-4" />
            <span className="flex-1">{label}</span>
            {badge && unreadCount > 0 && (
              <span className="rounded-full bg-amber px-1.5 py-0.5 text-[12px] font-semibold text-on-amber">
                {unreadCount > 99 ? '99+' : unreadCount}
              </span>
            )}
          </NavLink>
        ))}
      </nav>

      <div className="flex flex-1 min-h-0 flex-col gap-1 overflow-y-auto">
        <div className="flex items-center justify-between px-1 pb-1 pt-2">
          <span className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-text2">
            <Folder className="h-3.5 w-3.5" /> Проекты
          </span>
          {/* Меню только когда есть права на папки: из одного пункта оно
              было бы лишним кликом на ровном месте. */}
          {foldersCanManage ? (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button
                  type="button"
                  className="rounded p-1 text-text2 hover:bg-glass hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
                  aria-label="Создать проект или папку"
                >
                  <Plus className="h-3.5 w-3.5" />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-[200px]">
                <DropdownMenuItem onSelect={() => setCreateProjectOpen(true)}>
                  <FolderKanban className="mr-2 h-4 w-4" />
                  Проект
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => setCreateFolderOpen(true)}>
                  <FolderPlus className="mr-2 h-4 w-4" />
                  Папка
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          ) : (
            <button
              type="button"
              onClick={() => setCreateProjectOpen(true)}
              className="rounded p-1 text-text2 hover:bg-glass hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
              aria-label="Новый проект"
            >
              <Plus className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
        <ProjectsList drag={drag} onItemClick={onItemClick} />
      </div>

      <div className="flex items-center justify-between gap-2 border-t border-glass-border pt-3">
        <div className="flex items-center gap-2 overflow-hidden">
          <Avatar
            name={me.data?.full_name}
            email={me.data?.email}
            src={me.data?.avatar_url}
            className="h-7 w-7 text-[13px]"
          />
          <div className="min-w-0">
            <p className="truncate text-[13px] font-medium leading-[1.35] text-text">
              {me.data?.full_name || me.data?.email || '—'}
            </p>
            <p className="truncate text-[12px] leading-[1.35] text-text2">
              {me.data?.email ?? ''}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-1">
          <Link
            to="/settings/notifications"
            onClick={onItemClick}
            className="rounded p-1.5 text-text2 hover:bg-glass hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
            aria-label="Настройки"
            title="Настройки"
          >
            <Settings className="h-4 w-4" />
          </Link>
          <button
            onClick={() => {
              void authClient.logout()
            }}
            className="rounded p-1.5 text-text2 hover:bg-glass hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
            aria-label="Выйти"
            title="Выйти"
          >
            <LogOut className="h-4 w-4" />
          </button>
        </div>
      </div>

      <CreateProjectFromSidebar
        open={createProjectOpen}
        onOpenChange={setCreateProjectOpen}
      />
      <CreateTaskDialog open={createTaskOpen} onOpenChange={setCreateTaskOpen} />
      <CreateFolderDialog
        open={createFolderOpen}
        onOpenChange={setCreateFolderOpen}
      />
    </aside>

    {/* Оверлей — СОСЕД <aside>, не потомок: .glass несёт backdrop-filter, а он
        создаёт containing block для position:fixed — внутри сайдбара оверлей
        сместился бы и обрезался его границами. */}
    <DragOverlay dropAnimation={null}>
      {drag && <ProjectDragPreview drag={drag} />}
    </DragOverlay>
    </DndContext>
  )
}
