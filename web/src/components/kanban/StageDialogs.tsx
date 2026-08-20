import { useEffect, useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Label } from '@/components/ui/Label'
import { ResponsiveDialog } from '@/components/ui/ResponsiveDialog'
import { SheetPicker } from '@/components/ui/SheetPicker'
import { useCreateStage, useDeleteStage, useUpdateStage } from '@/hooks/useStages'
import { type TaskStage } from '@/lib/stages'
import { STATUS_LABEL, type TaskStatus } from '@/lib/tasks'

const SYSTEM: TaskStatus[] = ['todo', 'in_progress', 'in_review', 'done']

const SELECT_CLASS =
  'h-11 w-full rounded-[10px] border border-glass-border bg-surface px-3.5 font-body text-[15px] text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60 lg:h-10'

/**
 * «+ Этап» / «Переименовать»: имя + системный статус. Статус объясняется
 * словами — он решает, что считать «сделано» (уведомления, просрочка,
 * дашборд), а имя колонки — только подпись.
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
  const [status, setStatus] = useState<TaskStatus>('todo')
  useEffect(() => {
    if (open) {
      setName(stage?.name ?? '')
      setStatus(stage?.system_status ?? 'todo')
    }
  }, [open, stage])
  const pending = create.isPending || update.isPending

  const submit = async () => {
    const trimmed = name.trim()
    if (!trimmed) return
    try {
      if (stage) {
        await update.mutateAsync({ stageId: stage.id, name: trimmed, system_status: status })
        toast.success('Этап обновлён')
      } else {
        await create.mutateAsync({ name: trimmed, system_status: status })
        toast.success(`Этап «${trimmed}» добавлен`)
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
      title={stage ? `Этап «${stage.name}»` : 'Новый этап'}
      description="Имя этапа — ваше; системный статус решает, что считать «сделано»: уведомления, просрочка и дашборд смотрят на него."
      desktopWidth={480}
      footer={
        <>
          <Button variant="secondary" onClick={() => onOpenChange(false)} disabled={pending}>
            Отмена
          </Button>
          <Button onClick={() => void submit()} disabled={pending || !name.trim()}>
            {pending ? 'Сохраняем…' : stage ? 'Сохранить' : 'Добавить этап'}
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
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="stage-status">Системный статус</Label>
          <select
            id="stage-status"
            value={status}
            onChange={(e) => setStatus(e.target.value as TaskStatus)}
            className={SELECT_CLASS}
          >
            {SYSTEM.map((s) => (
              <option key={s} value={s}>
                {STATUS_LABEL[s]}
              </option>
            ))}
          </select>
        </div>
      </form>
    </ResponsiveDialog>
  )
}

/**
 * Удаление этапа: если в нём есть задачи — сначала выбрать, куда их
 * перенести (список остальных этапов). Последний этап системного статуса
 * сервер удалить не даст (409) — текст отказа придёт тостом.
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
      toast.success(`Этап «${stage.name}» удалён`)
      onOpenChange(false)
    } catch {
      // тост показывает глобальный onError мутаций (в т.ч. 409 «последний этап статуса»)
    }
  }

  if (taskCount > 0) {
    return (
      <SheetPicker
        open={open}
        onOpenChange={onOpenChange}
        title={`Удалить «${stage.name}»`}
        description={`В этапе ${taskCount} задач — выберите, куда их перенести.`}
        items={others.map((s) => ({ id: s.id, label: s.name, meta: STATUS_LABEL[s.system_status] }))}
        onSelect={(id) => void run(id)}
      />
    )
  }
  return (
    <ResponsiveDialog
      open={open}
      onOpenChange={onOpenChange}
      title={`Удалить этап «${stage.name}»?`}
      description="Этап пуст — задачи переносить не нужно."
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
