import { CircleCheck, FolderPlus, Plus } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'

import { CreateTaskDialog } from '@/components/task/CreateTaskDialog'
import {
  BottomSheet,
  BottomSheetItem,
} from '@/components/ui/BottomSheet'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/Dialog'
import { Input, Textarea } from '@/components/ui/Input'
import { Label } from '@/components/ui/Label'
import { Button } from '@/components/ui/Button'
import { useCreateProject } from '@/hooks/useProjects'
import { cn } from '@/lib/cn'

interface FloatingActionButtonProps {
  /** Position above the bottom tab bar — extra offset in rem. */
  bottomOffset?: number
  className?: string
}

/**
 * Asana-style FAB — fixed bottom-right rounded-square button with `+`.
 * Tap opens a bottom sheet to pick what to create (Task / Project).
 *
 * Lives outside the Shell so any page can mount it. Hidden on `lg` —
 * desktop uses the sidebar "Создать" dropdown instead.
 */
export function FloatingActionButton({
  bottomOffset = 5.5,
  className,
}: FloatingActionButtonProps) {
  const [sheetOpen, setSheetOpen] = useState(false)
  const [taskOpen, setTaskOpen] = useState(false)
  const [projectOpen, setProjectOpen] = useState(false)

  return (
    <>
      <button
        type="button"
        onClick={() => setSheetOpen(true)}
        aria-label="Создать"
        className={cn(
          'fixed right-4 z-30 inline-flex h-14 w-14 items-center justify-center rounded-2xl bg-red text-white shadow-lg transition-transform hover:scale-105 active:scale-95 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60 lg:hidden',
          className,
        )}
        style={{
          bottom: `calc(env(safe-area-inset-bottom, 0) + ${bottomOffset}rem)`,
        }}
      >
        <Plus className="h-7 w-7" strokeWidth={2.5} />
      </button>

      <BottomSheet
        open={sheetOpen}
        onOpenChange={setSheetOpen}
        title="Создать"
      >
        <BottomSheetItem
          icon={<CircleCheck className="h-5 w-5" />}
          onClick={() => {
            setSheetOpen(false)
            setTaskOpen(true)
          }}
        >
          Задача
        </BottomSheetItem>
        <BottomSheetItem
          icon={<FolderPlus className="h-5 w-5" />}
          onClick={() => {
            setSheetOpen(false)
            setProjectOpen(true)
          }}
        >
          Проект
        </BottomSheetItem>
      </BottomSheet>

      <CreateTaskDialog open={taskOpen} onOpenChange={setTaskOpen} />
      <MobileCreateProjectDialog open={projectOpen} onOpenChange={setProjectOpen} />
    </>
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
              Короткий ключ для задач (HUB-123) подберётся автоматически.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="fab-project-name">Название</Label>
              <Input
                id="fab-project-name"
                placeholder="Маркетинг"
                autoFocus
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="fab-project-desc">Описание (опционально)</Label>
              <Textarea
                id="fab-project-desc"
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
