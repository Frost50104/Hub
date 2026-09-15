import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/Button'
import { SELECT_CLASS } from '@/components/ui/Input'
import { Label } from '@/components/ui/Label'
import { SearchableSelect } from '@/components/ui/SearchableSelect'
import { ResponsiveDialog } from '@/components/ui/ResponsiveDialog'
import { useMe } from '@/hooks/useMe'
import { useProject, useProjects } from '@/hooks/useProjects'
import { useStages } from '@/hooks/useStages'
import { useMoveTask } from '@/hooks/useTasks'
import { describeTaskMove, moveTargets } from '@/lib/taskMove'
import { tasksApi, type TaskMoveReport } from '@/lib/tasks'

/**
 * «Перенести задачу» — выбор проекта плюс сводка последствий.
 *
 * Не инлайн-селект в карточке: переезд перенумеровывает задачу
 * (`uq_tasks_project_seq`), снимает метки и значения полей, для которых в цели
 * нет пары, отписывает наблюдателей и гасит публичную ссылку. Тихо это делать
 * нельзя, поэтому цену считает сервер (`GET /tasks/{id}/move-preview`) и
 * показывает ДО нажатия. Открывается стрелкой ⇄ в строке «Проект» карточки
 * (16.09): имя рядом — ссылка на страницу проекта, перенос — отдельная кнопка.
 *
 * Пересечения меток и полей здесь НЕ считаются: вторая реализация матчинга
 * разошлась бы с серверной на первой же правке.
 */
export function MoveTaskDialog({
  open,
  onOpenChange,
  taskId,
  projectId,
  currentStageName,
  onMoved,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
  taskId: string
  /** Текущий проект задачи — из неё самой, не из пропа страницы. */
  projectId: string
  /** Имя нынешней колонки: в цели по нему подставляется одноимённая. */
  currentStageName: string | null
  onMoved: (report: TaskMoveReport) => void
}) {
  const me = useMe()
  const projects = useProjects()
  // Личного пространства в `GET /projects` нет и не будет — сервер прячет его
  // из всех списков проектов. Берём точечно, по id из /api/me.
  const personal = useProject(me.data?.personal_project_id ?? undefined)
  const targets = moveTargets(projects.data, personal.data, projectId)

  const [targetId, setTargetId] = useState('')
  const [stageId, setStageId] = useState<string | null>(null)
  const stages = useStages(targetId || undefined)
  // Колонку подставляем ОДИН раз на каждую цель: иначе рефетч списка колонок
  // затирал бы выбор человека.
  const defaulted = useRef<string | null>(null)

  useEffect(() => {
    if (!open) {
      setTargetId('')
      setStageId(null)
      defaulted.current = null
      return
    }
    if (!targetId && targets[0]) setTargetId(targets[0].id)
  }, [open, targetId, targets])

  useEffect(() => {
    if (!targetId || !stages.data || defaulted.current === targetId) return
    defaulted.current = targetId
    // Дружелюбный дефолт живёт здесь, а не на сервере: у ручки одно правило
    // («корень берёт переданное»), и предпросмотр с переносом не расходятся.
    setStageId(stages.data.find((s) => s.name === currentStageName)?.id ?? null)
  }, [targetId, stages.data, currentStageName])

  const preview = useQuery({
    queryKey: ['task', taskId, 'move-preview', targetId, stageId],
    queryFn: () => tasksApi.movePreview(taskId, targetId, stageId),
    enabled: open && !!targetId,
  })
  const summary = preview.data ? describeTaskMove(preview.data) : null

  const move = useMoveTask()
  const submit = async () => {
    try {
      const report = await move.mutateAsync({
        id: taskId,
        project_id: targetId,
        stage_id: stageId,
      })
      toast.success(
        report.new_key
          ? `Задача перенесена — теперь ${report.new_key}`
          : 'Задача перенесена',
      )
      onOpenChange(false)
      onMoved(report)
    } catch {
      // тост показывает глобальный onError мутаций
    }
  }

  const empty = targets.length === 0 && !projects.isPending

  return (
    <ResponsiveDialog
      open={open}
      onOpenChange={(v) => !move.isPending && onOpenChange(v)}
      title="Перенести задачу"
      // Не украшение: без `Description` Radix пишет в консоль предупреждение
      // о доступности. Текст выбран так, чтобы не повторять сводку ниже, а
      // снять главный страх — «а комментарии не потеряются?».
      description="Комментарии, вложения и подзадачи переезжают вместе с задачей."
      desktopWidth={480}
      footer={
        <>
          <Button
            variant="secondary"
            onClick={() => onOpenChange(false)}
            disabled={move.isPending}
          >
            {empty ? 'Закрыть' : 'Отмена'}
          </Button>
          {!empty && (
            <Button onClick={() => void submit()} disabled={!targetId || move.isPending}>
              {move.isPending ? 'Переносим…' : 'Перенести'}
            </Button>
          )}
        </>
      }
    >
      {empty ? (
        <p className="text-[15px] text-text2">
          Переносить некуда: нужен ещё один проект, в котором у вас права
          редактора.
        </p>
      ) : (
        <div className="flex flex-col gap-4">
          {/* Обёртка `<label>` заменена на `Label htmlFor` 16.09: у списка с
              поиском триггер — кнопка, а интерактивный элемент внутри label
              даёт двойной клик по себе же. Суффикс «(личное)» снят 16.09:
              проект теперь так и называется — «Мои задачи». */}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="move-project" className="text-[13px] font-semibold text-text2">
              Проект
            </Label>
            <SearchableSelect
              id="move-project"
              sheetTitle="Проект"
              clearLabel={null}
              className={SELECT_CLASS}
              value={targetId || null}
              onChange={(v) => {
                setTargetId(v ?? '')
                defaulted.current = null
              }}
              options={targets.map((t) => ({ value: t.id, label: t.name, meta: t.key }))}
            />
          </div>

          {/* Прочерк — «без статуса» (0046): задача уходит с доски, оставаясь
              в списке и поиске. У проекта без колонок это единственный вариант.
              Поиск здесь не про длину «обычного» проекта: замер 16.09 — в
              крупнейшем 64 колонки, свыше десяти их в пяти проектах. */}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="move-stage" className="text-[13px] font-semibold text-text2">
              Колонка
            </Label>
            <SearchableSelect
              id="move-stage"
              sheetTitle="Колонка"
              className={SELECT_CLASS}
              value={stageId}
              onChange={setStageId}
              disabled={!stages.data || stages.data.length === 0}
              options={(stages.data ?? []).map((s) => ({ value: s.id, label: s.name }))}
            />
          </div>

          <div className="flex flex-col gap-1.5 text-[14px] leading-[1.45] text-text2">
            {preview.isPending && <span>Считаем последствия…</span>}
            {summary?.lines.map((line) => <span key={line}>{line}</span>)}
            {summary?.warning && (
              <span className="font-semibold text-red">{summary.warning}</span>
            )}
          </div>
        </div>
      )}
    </ResponsiveDialog>
  )
}
