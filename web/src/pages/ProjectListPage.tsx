import { zodResolver } from '@hookform/resolvers/zod'
import { Plus } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { z } from 'zod'

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
import { Input, Textarea } from '@/components/ui/Input'
import { Label } from '@/components/ui/Label'
import { useCreateProject, useProjects } from '@/hooks/useProjects'
import { type Project } from '@/lib/projects'

const createSchema = z.object({
  name: z.string().min(1).max(255),
  description: z.string().max(4000).optional(),
})

type CreateFormValues = z.infer<typeof createSchema>

function ProjectCard({ project }: { project: Project }) {
  return (
    <Link
      to={`/projects/${project.id}`}
      className="glass group flex flex-col gap-2 p-5 transition-colors hover:bg-surface focus:outline-none focus-visible:ring-2 focus-visible:ring-amber"
    >
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-amber/20 font-display text-base font-black uppercase text-amber">
          {project.key.slice(0, 2)}
        </div>
        <div className="min-w-0 flex-1">
          <h3 className="truncate font-display text-base font-semibold text-text">
            {project.name}
          </h3>
          <p className="text-xs text-text3">{project.key}</p>
        </div>
        {project.archived_at && <Badge variant="secondary">архив</Badge>}
        {project.my_role && project.my_role !== 'viewer' && (
          <Badge variant="default">{project.my_role}</Badge>
        )}
      </div>
      {project.description && (
        <p className="line-clamp-2 text-sm text-text2">{project.description}</p>
      )}
    </Link>
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
    } catch (err) {
      const message =
        (err as { response?: { data?: { detail?: string } } }).response?.data?.detail ??
        (err as Error).message
      toast.error('Не удалось создать проект', { description: message })
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
  const { data, isLoading, error } = useProjects()

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="font-display text-2xl">Проекты</h1>
          <p className="text-sm text-text2">
            Командные пространства с задачами, секциями и участниками.
          </p>
        </div>
        <Button onClick={() => setCreateOpen(true)}>
          <Plus className="h-4 w-4" />
          Новый проект
        </Button>
      </div>

      {isLoading && <p className="text-text2">Загружаем проекты…</p>}
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
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {data.map((p) => (
            <ProjectCard key={p.id} project={p} />
          ))}
        </div>
      )}

      <CreateProjectDialog open={createOpen} onOpenChange={setCreateOpen} />
    </div>
  )
}
