import { useEffect, useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Label } from '@/components/ui/Label'
import { ResponsiveDialog } from '@/components/ui/ResponsiveDialog'
import { SheetPicker } from '@/components/ui/SheetPicker'
import { useCreateStage, useDeleteStage } from '@/hooks/useStages'
import { stageDeletePrompt } from '@/lib/boardHints'
import { type TaskStage } from '@/lib/stages'

/**
 * «+ Колонка»: только имя. Системного смысла у колонки нет (0044) —
 * выполнение задачи живёт в её галочке, а не в месте на доске.
 *
 * Режима правки у диалога НЕТ: имя меняется кликом прямо по заголовку колонки
 * (26.08). Модалка ради одного поля, которое видно на доске, была лишним шагом.
 */
export function StageFormDialog({
  open,
  onOpenChange,
  projectId,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
  projectId: string
}) {
  const create = useCreateStage(projectId)
  const [name, setName] = useState('')
  useEffect(() => {
    if (open) setName('')
  }, [open])

  const submit = async () => {
    const trimmed = name.trim()
    if (!trimmed) return
    try {
      await create.mutateAsync({ name: trimmed })
      toast.success(`Колонка «${trimmed}» добавлена`)
      onOpenChange(false)
    } catch {
      // тост показывает глобальный onError мутаций
    }
  }

  return (
    <ResponsiveDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Новая колонка"
      description="Имя колонки — ваше: «Идея», «Согласование», «Печать». Выполненность задачи от колонки не зависит — её отмечают галочкой."
      desktopWidth={480}
      footer={
        <>
          <Button variant="secondary" onClick={() => onOpenChange(false)} disabled={create.isPending}>
            Отмена
          </Button>
          <Button onClick={() => void submit()} disabled={create.isPending || !name.trim()}>
            {create.isPending ? 'Сохраняем…' : 'Добавить колонку'}
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

/** Сентинел «оставить без колонки» в списке приёмников. */
const DETACH = '__detach__'

/**
 * Удаление колонки.
 *
 * С задачами внутри выбор обязателен: перенести их в другую колонку или
 * оставить без колонки (`stage_id = null` — легальное состояние с 0046).
 * Сервер тот же выбор требует и от API: без `move_to` и без `detach` он
 * отвечает 409, чтобы раскладка не пропала молча.
 *
 * Последнюю колонку удалить МОЖНО (26.08): проект без колонок — норма, и
 * создавший колонку по ошибке обязан иметь выход. Тогда переносить некуда, и
 * вместо пикера показываем честное подтверждение.
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

  const run = async (target: string | null) => {
    try {
      await remove.mutateAsync(
        target === null || target === DETACH
          ? { stageId: stage.id, detach: taskCount > 0 }
          : { stageId: stage.id, moveTo: target },
      )
      toast.success(`Колонка «${stage.name}» удалена`)
      onOpenChange(false)
    } catch {
      // тост показывает глобальный onError мутаций
    }
  }

  if (taskCount > 0 && others.length > 0) {
    return (
      <SheetPicker
        open={open}
        onOpenChange={onOpenChange}
        title={`Удалить «${stage.name}»`}
        description={stageDeletePrompt(taskCount, true)}
        items={[
          ...others.map((s) => ({ id: s.id, label: s.name })),
          { id: DETACH, label: 'Оставить без колонки', meta: 'Задачи останутся в списке' },
        ]}
        onSelect={(id) => void run(id)}
      />
    )
  }

  return (
    <ResponsiveDialog
      open={open}
      onOpenChange={onOpenChange}
      title={`Удалить колонку «${stage.name}»?`}
      // Последняя колонка: переносить некуда, поэтому диалог называет цену.
      description={stageDeletePrompt(taskCount, false)}
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
