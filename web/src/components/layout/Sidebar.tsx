import {
  Archive,
  CheckSquare,
  ChevronDown,
  ChevronRight,
  Folder,
  FolderKanban,
  FolderPlus,
  Home,
  Inbox,
  Layers,
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
import { NavLink, Link, useLocation } from 'react-router-dom'
import { toast } from 'sonner'

import { FolderActionsMenu } from '@/components/project/FolderActionsMenu'
import { nextName } from '@/lib/renameDraft'

import { SidebarSearch } from './SidebarSearch'
import { SpaceSwitcher } from './SpaceSwitcher'
import { CreateFolderDialog } from '@/components/project/CreateFolderDialog'
import { CreateProjectDialog } from '@/components/project/CreateProjectDialog'
import { CreateTaskDialog } from '@/components/task/CreateTaskDialog'
import { Avatar } from '@/components/ui/Avatar'
import { SkeletonRows } from '@/components/ui/Skeleton'
import { Button } from '@/components/ui/Button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/DropdownMenu'
import { useMe } from '@/hooks/useMe'
import { useUnreadCount } from '@/hooks/useNotifications'
import {
  useProjectFolders,
  useProjects,
  useRenameFolder,
  useSetProjectFolder,
} from '@/hooks/useProjects'
import { logoutWithDeviceCleanup } from '@/lib/session'
import { useTheme } from '@/lib/theme'
import { ProjectKeyChip } from '@/components/project/ProjectKeyChip'
import { cn } from '@/lib/cn'
import { HubRoleChip } from '@/components/layout/HubRoleChip'
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
import { templatesNavVisible } from '@/lib/projectTemplates'
import { requestInlineCreate } from '@/lib/quickCreate'
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
  /** Бейдж тоже снапшотим: без него под курсором окажутся буквы вместо
   *  значка — ровно в тех 260px, где значок и нужен. */
  badgeEmoji?: string | null
  badgeUrl?: string | null
  isFavorite: boolean
}

/** Превью под курсором. bg-bg-alt, а не bg-surface/95: токены в
 *  tailwind.config объявлены сырыми var() без <alpha-value>, слэш-опасити
 *  на них не компилируется. */
function ProjectDragPreview({ drag }: { drag: SidebarDragData }) {
  return (
    <div className="flex h-full w-full items-center gap-2 rounded-md border border-glass-border bg-bg-alt px-2 py-1.5 text-sm text-text shadow-glass">
      <ProjectKeyChip
        project={{
          key: drag.projectKey,
          is_favorite: drag.isFavorite,
          badge_emoji: drag.badgeEmoji,
          badge_url: drag.badgeUrl,
        }}
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
  canManageFolders,
  onItemClick,
}: {
  group: ProjectGroup
  /** null — перетаскивания сейчас нет. */
  drag: SidebarDragData | null
  dndEnabled: boolean
  /** Может ли этот человек управлять папками — от этого зависит, показывать
   *  ли ему пустые. */
  canManageFolders: boolean
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
  const [renaming, setRenaming] = useState(false)
  const [draft, setDraft] = useState(folder?.name ?? '')
  const rename = useRenameFolder()

  const submitRename = () => {
    setRenaming(false)
    if (!folder) return
    // Пустое и неизменённое имя запроса не порождают — правило общее с
    // `/projects`, поэтому живёт в lib и покрыто тестом.
    const name = nextName(draft, folder.name)
    if (name) rename.mutate({ id: folder.id, name })
  }

  // Пустую группу «Без папки» прячем всегда: заголовок с нулём — чистый шум
  // (во время драга он нужен как зона «вынуть из папки»).
  if (!folder && group.projects.length === 0 && !dragging) return null

  // Пустую ИМЕНОВАННУЮ папку показываем только тому, кто папками управляет:
  // он мог её только что создать, и она обязана быть видна там, где создана,
  // а во время драга она — единственная зона, куда можно перенести проект.
  // Остальным восемь строк со счётчиком 0, которые лишь сворачиваются, —
  // такой же шум, как «Без папки»: у линейного сотрудника доступных проектов
  // внутри нет и не появится.
  if (folder && group.projects.length === 0 && !dragging && !canManageFolders) {
    return null
  }

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
        renaming ? (
          <div className="px-2 py-0.5">
            <input
              autoFocus
              // Выделяем при фокусе: переименование почти всегда — замена
              // имени целиком, а без выделения набранное дописывается к
              // старому и человек получает «ОТДЕЛ ПЕРСОНАЛАНОВОЕ».
              onFocus={(e) => e.target.select()}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onBlur={submitRename}
              onKeyDown={(e) => {
                if (e.key === 'Enter') submitRename()
                if (e.key === 'Escape') setRenaming(false)
              }}
              aria-label={`Новое имя папки «${folder.name}»`}
              className="h-6 w-full rounded-md border border-glass-border bg-glass px-1.5 text-[12px] font-semibold uppercase tracking-wider text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
            />
          </div>
        ) : (
          // Группа ИМЕНОВАННАЯ и висит на СТРОКЕ ЗАГОЛОВКА, а не на обёртке-
          // дропзоне: `:hover` истинен и на потомках, поэтому группа на обёртке
          // зажигала бы «…» при наведении на любой проект внутри папки. Имя
          // обязательно — у NavLink проекта ниже уже объявлен безымянный
          // `group`, и безымянный `group-hover:` здесь привязался бы к
          // несуществующему предку: не сработал бы и ошибки не выдал.
          <div className="group/folder flex items-center gap-1 px-2 py-0.5">
            <button
              type="button"
              onClick={() => toggle(folder.id)}
              className="flex min-w-0 flex-1 items-center gap-1 text-left text-[12px] font-semibold uppercase tracking-wider text-text2 hover:text-text2"
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
            {canManageFolders && !dragging && (
              <FolderActionsMenu
                folder={folder}
                projectCount={group.projects.length}
                onRenameStart={() => {
                  setDraft(folder.name)
                  setRenaming(true)
                }}
                size="xs"
                // Каждый класс лечит свой отказ: наведение, клавиатуру,
                // открытое меню (Radix ставит data-state на триггер, а строка
                // теряет :hover, пока курсор на портале) и тач ≥1024px, где
                // hover не наступает никогда, а opacity-0 оставляет кнопку
                // кликабельной, но невидимой.
                triggerClassName="opacity-0 transition-opacity group-hover/folder:opacity-100 focus-visible:opacity-100 data-[state=open]:opacity-100 [@media(hover:none)]:opacity-100"
              />
            )}
          </div>
        )
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
  const canManageFolders = foldersQuery.data?.can_manage ?? false
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
            canManageFolders={canManageFolders}
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
      badgeEmoji: project.badge_emoji,
      badgeUrl: project.badge_url,
      isFavorite: project.is_favorite,
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


export interface SidebarProps {
  /** Called when a navigation entry is clicked (used to close the mobile drawer). */
  onItemClick?: () => void
}

export function Sidebar({ onItemClick }: SidebarProps = {}) {
  const theme = useTheme((s) => s.theme)
  const location = useLocation()
  const me = useMe()
  const unread = useUnreadCount()
  const unreadCount = unread.data?.count ?? 0
  const [createProjectOpen, setCreateProjectOpen] = useState(false)
  const [createTaskOpen, setCreateTaskOpen] = useState(false)
  /** Проект, открытый в момент нажатия: подставляется в запасной диалог. */
  const [createTaskProjectId, setCreateTaskProjectId] = useState<string | undefined>()
  const [createFolderOpen, setCreateFolderOpen] = useState(false)
  // Тот же queryKey, что читает ProjectsList — TanStack дедуплицирует,
  // лишнего запроса нет. Права считает сервер, копии правила тут не заводим.
  const foldersCanManage = useProjectFolders().data?.can_manage ?? false
  const canCreateProjects = me.data?.can_create_projects ?? false
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
      {/* Бренд по макету: марка-маяк 26px + «Hub» на месте «Signaris»
          (горизонтальный локап остаётся публичной странице и сертификату).
          Роль живёт чипом у профиля в футере, не под логотипом. */}
      <Link to="/" onClick={onItemClick} className="flex items-center gap-2.5 px-1">
        <img
          src={
            theme === 'light'
              ? '/brand/signaris-mark-on-light.svg'
              : '/brand/signaris-mark-on-dark.svg'
          }
          alt="Signaris"
          className="h-[26px] w-[26px] shrink-0"
        />
        <span className="font-display text-[17px] font-black leading-none tracking-[-0.025em] text-text">
          Hub
        </span>
      </Link>

      <SpaceSwitcher />

      {/* Единственная плотная амбер-кнопка сайдбара. На странице проекта она
          ставит курсор в инлайн-поле «+ Новая задача» — одна точка входа, а не
          второй способ создать задачу; вне проекта открывает диалог. Проект и
          папка создаются через «+» у блока «Проекты». Скрыта в read-only
          (кнопка без прав «отсутствует, а не заблокирована»). */}
      <Button
        className="h-[38px] w-full justify-center rounded-[10px] text-[14px] font-bold"
        onClick={() => {
          const m = /^\/projects\/([^/]+)/.exec(location.pathname)
          if (m?.[1] && requestInlineCreate(m[1])) return
          // Диалог — ЗАПАСНОЙ путь: инлайн-поля нет, например, на вкладках
          // «Участники» и «Дашборд». Проект подставляем текущий, иначе
          // «Новая задача» внутри проекта молча заводит ЛИЧНУЮ задачу — а с
          // открытием карточки это ещё и уводит человека на /my.
          setCreateTaskProjectId(m?.[1])
          setCreateTaskOpen(true)
        }}
      >
        <Plus className="h-4 w-4" strokeWidth={2.4} />
        Новая задача
      </Button>

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
                'flex h-[34px] items-center gap-[9px] rounded-[9px] px-2 text-[14px] transition-colors',
                isActive
                  ? 'bg-surface font-semibold text-text'
                  : 'font-medium text-text2 hover:bg-glass hover:text-text',
              )
            }
          >
            <Icon className="h-4 w-4" />
            <span className="flex-1">{label}</span>
            {/* Точка 6px, а не счётчик: число непрочитанных уже есть во
                «Входящих», в навигации достаточно факта «есть новое». */}
            {badge && unreadCount > 0 && (
              <span
                aria-label={`${unreadCount} непрочитанных`}
                className="h-1.5 w-1.5 shrink-0 rounded-full bg-red"
              />
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
              было бы лишним кликом на ровном месте. Без права создавать
              проекты (линейный сотрудник) «+» не рисуется вовсе —
              «кнопка без прав отсутствует, а не заблокирована». */}
          {!canCreateProjects ? null : foldersCanManage ? (
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

      {/* ВНЕ скролла проектов и над футером: внутри контейнера «Архив» уезжал
          бы вниз вместе с длинным деревом папок. Рисуем всегда — чтобы узнать,
          пуст ли архив, сайдбару пришлось бы тянуть второй полный список
          проектов на каждой загрузке ради строки в 34px. */}
      <nav className="flex flex-col gap-0.5">
        <NavLink
          to="/projects/archived"
          onClick={onItemClick}
          className={({ isActive }) =>
            cn(
              'flex h-[34px] items-center gap-[9px] rounded-[9px] px-2 text-[14px] transition-colors',
              isActive
                ? 'bg-surface font-semibold text-text'
                : 'font-medium text-text2 hover:bg-glass hover:text-text',
            )
          }
        >
          <Archive className="h-4 w-4" />
          <span className="flex-1">Архив</span>
        </NavLink>
        {templatesNavVisible(me.data) && (
          <NavLink
            to="/projects/templates"
            onClick={onItemClick}
            className={({ isActive }) =>
              cn(
                'flex h-[34px] items-center gap-[9px] rounded-[9px] px-2 text-[14px] transition-colors',
                isActive
                  ? 'bg-surface font-semibold text-text'
                  : 'font-medium text-text2 hover:bg-glass hover:text-text',
              )
            }
          >
            <Layers className="h-4 w-4" />
            <span className="flex-1">Шаблоны</span>
          </NavLink>
        )}
      </nav>

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
            {/* Чип роли — во второй строке перед e-mail: на 260px рядом с
                именем он резал «Пётр Попов» до «Пётр П…», а e-mail терпит
                многоточие лучше имени. */}
            <p className="mt-0.5 flex min-w-0 items-center gap-1.5">
              {me.data?.hub_role && <HubRoleChip role={me.data.hub_role} />}
              <span className="min-w-0 truncate text-[12px] leading-[1.35] text-text2">
                {me.data?.email ?? ''}
              </span>
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
              void logoutWithDeviceCleanup()
            }}
            className="rounded p-1.5 text-text2 hover:bg-glass hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
            aria-label="Выйти"
            title="Выйти"
          >
            <LogOut className="h-4 w-4" />
          </button>
        </div>
      </div>

      <CreateProjectDialog
        open={createProjectOpen}
        onOpenChange={setCreateProjectOpen}
      />
      <CreateTaskDialog
        open={createTaskOpen}
        onOpenChange={setCreateTaskOpen}
        initialProjectId={createTaskProjectId}
        openAfterCreate
      />
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
