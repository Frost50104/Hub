import {
  CheckSquare,
  ChevronDown,
  CircleCheck,
  Folder,
  FolderPlus,
  Home,
  Inbox,
  LogOut,
  Plus,
  Settings,
} from 'lucide-react'
import { useState } from 'react'
import { NavLink, Link, useNavigate } from 'react-router-dom'
import { toast } from 'sonner'

import { SidebarSearch } from './SidebarSearch'
import { CreateTaskDialog } from '@/components/task/CreateTaskDialog'
import { Avatar } from '@/components/ui/Avatar'
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
import { useCreateProject, useProjects } from '@/hooks/useProjects'
import { authClient } from '@/lib/auth'
import { cn } from '@/lib/cn'
import { type Project } from '@/lib/projects'

const NAV_ITEMS = [
  { to: '/', label: 'Главная', icon: Home, end: true, badge: false },
  { to: '/my', label: 'Мои задачи', icon: CheckSquare, end: false, badge: false },
  { to: '/inbox', label: 'Входящие', icon: Inbox, end: false, badge: true },
] as const

function projectColorFor(p: Project): string {
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

function ProjectsList({ onItemClick }: { onItemClick?: () => void }) {
  const { data, isLoading } = useProjects()
  if (isLoading) return <p className="px-3 py-1 text-xs text-text3">Загружаем…</p>
  if (!data || data.length === 0) {
    return <p className="px-3 py-1 text-xs text-text3">Нет проектов</p>
  }
  return (
    <ul className="space-y-0.5">
      {data.map((p) => (
        <li key={p.id}>
          <NavLink
            to={`/projects/${p.id}`}
            onClick={onItemClick}
            className={({ isActive }) =>
              cn(
                'group flex items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors',
                isActive
                  ? 'bg-surface text-text'
                  : 'text-text2 hover:bg-glass hover:text-text',
              )
            }
          >
            <span
              className={cn(
                'flex h-5 w-5 shrink-0 items-center justify-center rounded text-[10px] font-semibold uppercase',
                projectColorFor(p),
              )}
            >
              {p.key.slice(0, 2)}
            </span>
            <span className="truncate">{p.name}</span>
          </NavLink>
        </li>
      ))}
    </ul>
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
    } catch (err) {
      const message =
        (err as { response?: { data?: { detail?: string } } }).response?.data?.detail ??
        (err as Error).message
      toast.error('Не удалось создать проект', { description: message })
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
  const me = useMe()
  const unread = useUnreadCount()
  const unreadCount = unread.data?.count ?? 0
  const [createProjectOpen, setCreateProjectOpen] = useState(false)
  const [createTaskOpen, setCreateTaskOpen] = useState(false)
  return (
    <aside className="glass flex h-screen w-[280px] shrink-0 flex-col gap-4 p-4 md:h-[calc(100vh-1.5rem)] md:w-[260px]">
      <Link to="/" onClick={onItemClick} className="flex items-center gap-2 px-1">
        <img src="/brand/signaris-horizontal-on-dark.svg" alt="Signaris" className="h-6" />
        <span className="font-display text-lg font-black leading-none tracking-tight">
          Hub
        </span>
      </Link>

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
            <FolderPlus className="mr-2 h-4 w-4" />
            Проект
          </DropdownMenuItem>
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
              <span className="rounded-full bg-amber px-1.5 py-0.5 text-[10px] font-semibold text-bg">
                {unreadCount > 99 ? '99+' : unreadCount}
              </span>
            )}
          </NavLink>
        ))}
      </nav>

      <div className="flex flex-1 min-h-0 flex-col gap-1 overflow-y-auto">
        <div className="flex items-center justify-between px-1 pb-1 pt-2">
          <span className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-text3">
            <Folder className="h-3.5 w-3.5" /> Проекты
          </span>
          <button
            onClick={() => setCreateProjectOpen(true)}
            className="rounded p-1 text-text3 hover:bg-glass hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
            aria-label="Новый проект"
          >
            <Plus className="h-3.5 w-3.5" />
          </button>
        </div>
        <ProjectsList onItemClick={onItemClick} />
      </div>

      <div className="flex items-center justify-between gap-2 border-t border-glass-border pt-3">
        <div className="flex items-center gap-2 overflow-hidden">
          <Avatar
            name={me.data?.full_name}
            email={me.data?.email}
            className="h-7 w-7 text-[10px]"
          />
          <div className="min-w-0">
            <p className="truncate text-xs font-medium text-text">
              {me.data?.full_name || me.data?.email || '—'}
            </p>
            <p className="truncate text-[10px] text-text3">{me.data?.tenant_slug ?? ''}</p>
          </div>
        </div>
        <div className="flex items-center gap-1">
          <Link
            to="/settings/notifications"
            onClick={onItemClick}
            className="rounded p-1.5 text-text3 hover:bg-glass hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
            aria-label="Настройки"
            title="Настройки"
          >
            <Settings className="h-4 w-4" />
          </Link>
          <button
            onClick={() => {
              void authClient.logout()
            }}
            className="rounded p-1.5 text-text3 hover:bg-glass hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
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
    </aside>
  )
}
