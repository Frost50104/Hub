import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
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
import { useCreateProject } from '@/hooks/useProjects'

/** Потолки — как у `ProjectCreate` на сервере. */
const NAME_MAX = 255
const DESCRIPTION_MAX = 4000

/**
 * Единственный диалог «Новый проект» — для сайдбара, шторки FAB и `/projects`.
 * До 21.09 это были три копии, и разошлись они уже в поведении: из сайдбара и
 * FAB человек попадал в созданный проект, со страницы «Проекты» — нет.
 */
export function CreateProjectDialog({
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
              <Label htmlFor="create-project-name">Название</Label>
              <Input
                id="create-project-name"
                placeholder="Маркетинг"
                autoFocus
                maxLength={NAME_MAX}
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="create-project-desc">Описание (опционально)</Label>
              <Textarea
                id="create-project-desc"
                rows={2}
                maxLength={DESCRIPTION_MAX}
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
