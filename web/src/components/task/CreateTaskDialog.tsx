import { useEffect, useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/Button'
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
import { useProjects, useProjectSections } from '@/hooks/useProjects'
import { useCreateTask } from '@/hooks/useTasks'

interface CreateTaskDialogProps {
  open: boolean
  onOpenChange: (v: boolean) => void
  /** Pre-select project (e.g. when invoked from ProjectPage). */
  initialProjectId?: string
}

export function CreateTaskDialog({
  open,
  onOpenChange,
  initialProjectId,
}: CreateTaskDialogProps) {
  const projects = useProjects()
  const [projectId, setProjectId] = useState<string | ''>(initialProjectId ?? '')
  const sections = useProjectSections(projectId || undefined)
  const [sectionId, setSectionId] = useState<string | ''>('')
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')

  // Default to the first project when dialog opens without one preselected.
  useEffect(() => {
    if (open && !projectId && projects.data && projects.data.length > 0) {
      setProjectId(projects.data[0]!.id)
    }
  }, [open, projectId, projects.data])

  const create = useCreateTask(projectId || '')

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = title.trim()
    if (!trimmed || !projectId) return
    try {
      await create.mutateAsync({
        title: trimmed,
        description: description.trim() || undefined,
        section_id: sectionId || undefined,
      })
      toast.success('Задача создана')
      setTitle('')
      setDescription('')
      setSectionId('')
      onOpenChange(false)
    } catch (err) {
      const message =
        (err as { response?: { data?: { detail?: string } } }).response?.data?.detail ??
        (err as Error).message
      toast.error('Не удалось создать задачу', { description: message })
    }
  }

  const hasProjects = (projects.data?.length ?? 0) > 0

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form onSubmit={submit}>
          <DialogHeader>
            <DialogTitle>Новая задача</DialogTitle>
            <DialogDescription>
              {hasProjects
                ? 'Выберите проект и секцию (опционально), введите название.'
                : 'Сначала создайте проект — задачи живут внутри проектов.'}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="task-project">Проект</Label>
              <select
                id="task-project"
                value={projectId}
                onChange={(e) => {
                  setProjectId(e.target.value)
                  setSectionId('')
                }}
                disabled={!hasProjects}
                className="flex h-9 w-full rounded-lg border border-glass-border bg-glass px-2 text-sm text-text focus:border-amber focus:outline-none"
              >
                {!hasProjects && <option>—</option>}
                {projects.data?.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="task-section">Секция</Label>
              <select
                id="task-section"
                value={sectionId}
                onChange={(e) => setSectionId(e.target.value)}
                disabled={!projectId}
                className="flex h-9 w-full rounded-lg border border-glass-border bg-glass px-2 text-sm text-text focus:border-amber focus:outline-none"
              >
                <option value="">Без секции</option>
                {sections.data?.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="task-title">Название</Label>
              <Input
                id="task-title"
                placeholder="Что нужно сделать?"
                autoFocus
                value={title}
                onChange={(e) => setTitle(e.target.value)}
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="task-desc">Описание (опционально)</Label>
              <Textarea
                id="task-desc"
                rows={3}
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
            <Button
              type="submit"
              disabled={create.isPending || !title.trim() || !projectId}
            >
              {create.isPending ? 'Создаём…' : 'Создать'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
