import { ChevronDown, CircleCheck, FolderPlus, Menu, Plus } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { toast } from 'sonner'

import { CreateTaskDialog } from '@/components/task/CreateTaskDialog'
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
import { useCreateProject } from '@/hooks/useProjects'

interface MobileTopbarProps {
  onOpenSidebar: () => void
}

/**
 * Mobile-only top bar. Shows on `<md` viewports — burger trigger opens
 * `<SidebarDrawer />`, plus a compact "Создать" dropdown for tasks/projects
 * so users on phones can create work without opening the drawer.
 */
export function MobileTopbar({ onOpenSidebar }: MobileTopbarProps) {
  const [taskOpen, setTaskOpen] = useState(false)
  const [projectOpen, setProjectOpen] = useState(false)

  return (
    <header className="glass sticky top-0 z-30 flex h-14 items-center gap-2 px-3">
      <button
        type="button"
        onClick={onOpenSidebar}
        className="-ml-1 inline-flex h-11 w-11 items-center justify-center rounded-md text-text2 hover:bg-glass hover:text-text"
        aria-label="Открыть меню"
      >
        <Menu className="h-5 w-5" />
      </button>

      <Link to="/" className="flex flex-1 items-center gap-2 overflow-hidden">
        <img
          src="/brand/signaris-horizontal-on-dark.svg"
          alt="Signaris"
          className="h-5 shrink-0"
        />
        <span className="font-display text-base font-black leading-none tracking-tight">
          Hub
        </span>
      </Link>

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button size="sm" className="h-9 px-3">
            <Plus className="h-4 w-4" />
            <ChevronDown className="h-3.5 w-3.5 opacity-70" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-[180px]">
          <DropdownMenuItem onSelect={() => setTaskOpen(true)}>
            <CircleCheck className="mr-2 h-4 w-4" />
            Задача
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={() => setProjectOpen(true)}>
            <FolderPlus className="mr-2 h-4 w-4" />
            Проект
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <CreateTaskDialog open={taskOpen} onOpenChange={setTaskOpen} />
      <MobileCreateProjectDialog open={projectOpen} onOpenChange={setProjectOpen} />
    </header>
  )
}

function MobileCreateProjectDialog({
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
              Короткий ключ для задач (HUB-123) подберётся автоматически.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="mobile-project-name">Название</Label>
              <Input
                id="mobile-project-name"
                placeholder="Маркетинг"
                autoFocus
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="mobile-project-desc">Описание (опционально)</Label>
              <Textarea
                id="mobile-project-desc"
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
