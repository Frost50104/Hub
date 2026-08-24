import { useEffect, useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Label } from '@/components/ui/Label'
import { ResponsiveDialog } from '@/components/ui/ResponsiveDialog'
import { SheetPicker } from '@/components/ui/SheetPicker'
import { useCreateStage, useDeleteStage, useUpdateStage } from '@/hooks/useStages'
import { type TaskStage } from '@/lib/stages'

/**
 * «+ Колонка» / «Переименовать»: только имя. Системного смысла у колонки нет
 * (0044) — выполнение задачи живёт в её галочке, а не в месте на доске.
 */
export function StageFormDialog({
  open,
  onOpenChange,
  projectId,
  stage,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
  projectId: string
  /** Редактирование; без него — создание. */
  stage?: TaskStage | null
}) {
  const create = useCreateStage(projectId)
  const update = useUpdateStage(projectId)
  const [name, setName] = useState('')
  useEffect(() => {
    if (open) {
      setName(stage?.name ?? '')
    }
  }, [open, stage])
  const pending = create.isPending || update.isPending

  const submit = async () => {
    const trimmed = name.trim()
    if (!trimmed) return
    try {
      if (stage) {
        await update.mutateAsync({ stageId: stage.id, name: trimmed })
        toast.success('Этап обновлён')
      } else {
        await create.mutateAsync({ name: trimmed })
        toast.success(`Колонка «${trimmed}» добавлена`)
      }
      onOpenChange(false)
    } catch {
      // тост показывает глобальный onError мутаций
    }
  }

  return (
    <ResponsiveDialog
      open={open}
      onOpenChange={onOpenChange}
      title={stage ? `Колонка «${stage.name}»` : 'Новая колонка'}
      description="Имя колонки — ваше: «Идея», «Согласование», «Печать». Выполненность задачи от колонки не зависит — её отмечают галочкой."
      desktopWidth={480}
      footer={
        <>
          <Button variant="secondary" onClick={() => onOpenChange(false)} disabled={pending}>
            Отмена
          </Button>
          <Button onClick={() => void submit()} disabled={pending || !name.trim()}>
            {pending ? 'Сохраняем…' : stage ? 'Сохранить' : 'Добавить колонку'}
          </Button>
        </>
      }
    >
      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault()
          void submit()
        }}
      >
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="stage-name">Название</Label>
          <Input
            id="stage-name"
            autoFocus
            value={name}
            placeholder="Проверка ТУ"
            maxLength={255}
            onChange={(e) => setName(e.target.value)}
            className="h-11 text-[15px] lg:h-10"
          />
        </div>
      </form>
    </ResponsiveDialog>
  )
}

/**
 * Удаление колонки: если в ней есть задачи — сначала выбрать, куда их
 * перенести (список остальных колонок). Последнюю колонку проекта сервер
 * удалить не даст (409) — текст отказа придёт тостом.
 */
export function DeleteStageDialog({
  open,
  onOpenChange,
  projectId,
  stage,
  stages,
  taskCount,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
  projectId: string
  stage: TaskStage | null
  stages: TaskStage[]
  taskCount: number
}) {
  const remove = useDeleteStage(projectId)
  if (!stage) return null
  const others = stages.filter((s) => s.id !== stage.id)

  const run = async (moveTo: string | null) => {
    try {
      await remove.mutateAsync({ stageId: stage.id, moveTo })
      toast.success(`Колонка «${stage.name}» удалена`)
      onOpenChange(false)
    } catch {
      // тост показывает глобальный onError мутаций (в т.ч. 409 «последняя колонка»)
    }
  }

  if (taskCount > 0) {
    return (
      <SheetPicker
        open={open}
        onOpenChange={onOpenChange}
        title={`Удалить «${stage.name}»`}
        description={`В колонке ${taskCount} задач — выберите, куда их перенести.`}
        items={others.map((s) => ({ id: s.id, label: s.name }))}
        onSelect={(id) => void run(id)}
      />
    )
  }
  return (
    <ResponsiveDialog
      open={open}
      onOpenChange={onOpenChange}
      title={`Удалить колонку «${stage.name}»?`}
      description="Колонка пуста — задачи переносить не нужно."
      desktopWidth={440}
      footer={
        <>
          <Button variant="secondary" onClick={() => onOpenChange(false)} disabled={remove.isPending}>
            Отмена
          </Button>
          <Button variant="destructive" onClick={() => void run(null)} disabled={remove.isPending}>
            Удалить
          </Button>
        </>
      }
    >
      <span className="sr-only">Подтверждение удаления</span>
    </ResponsiveDialog>
  )
}
