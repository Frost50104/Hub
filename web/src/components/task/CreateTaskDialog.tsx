import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
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
import { useMe } from '@/hooks/useMe'
import { useProjects } from '@/hooks/useProjects'
import { useCreateTask } from '@/hooks/useTasks'
import {
  createdTaskLocation,
  PERSONAL_TARGET,
  createTaskTargets,
  initialTarget,
  resolveProjectId,
} from '@/lib/createTaskTargets'

interface CreateTaskDialogProps {
  open: boolean
  onOpenChange: (v: boolean) => void
  /** Pre-select project (e.g. when invoked from ProjectPage). */
  initialProjectId?: string
  /**
   * Открыть карточку созданной задачи, чтобы дозаполнить остальные поля.
   *
   * По умолчанию ВЫКЛЮЧЕНО, и это не осторожность: у ассистента задачу заводят
   * из строки отчёта iiko, и уводить человека с экрана посреди разбора нельзя.
   * Дефолт `false` означает, что оба ассистентских монтирования не правятся
   * вовсе — забыть про них невозможно.
   */
  openAfterCreate?: boolean
}

/**
 * «Новая задача».
 *
 * Прочерк в поле «Проект» — не «ничего не выбрано», а конкретное место: личные
 * задачи. Он же выбран по умолчанию, поэтому подпись диалога обязана это
 * проговорить: иначе человек ищет, что же выбрать, а набрав название и нажав
 * «Создать», не поймёт, куда задача делась.
 *
 * В списке — только проекты с `can_edit`. Раньше туда попадали и те, где
 * человек наблюдатель, а `POST /tasks` требует owner/editor: у сотрудника с
 * одним viewer-проектом кнопка вела в 403.
 */
export function CreateTaskDialog({
  open,
  onOpenChange,
  initialProjectId,
  openAfterCreate = false,
}: CreateTaskDialogProps) {
  const navigate = useNavigate()
  const location = useLocation()
  const projects = useProjects()
  // Личный проект скрыт из `useProjects()` серверным инвариантом — id берём
  // из `/api/me`.
  const personalProjectId = useMe().data?.personal_project_id ?? null
  const targets = createTaskTargets(projects.data)
  const [target, setTarget] = useState<string>(PERSONAL_TARGET)
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')

  // Пересчитываем при открытии, а не в useState: `initialProjectId` и список
  // проектов приезжают асинхронно, а диалог переиспользуется между открытиями.
  useEffect(() => {
    if (open) setTarget(initialTarget(targets, initialProjectId))
    // targets пересобирается каждый рендер — в зависимостях только его длина,
    // иначе эффект перетирал бы выбор человека на каждом ререндере.
  }, [open, initialProjectId, targets.length]) // eslint-disable-line react-hooks/exhaustive-deps

  const projectId = resolveProjectId(target, personalProjectId)
  const isPersonal = target === PERSONAL_TARGET
  const create = useCreateTask(projectId ?? '')

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = title.trim()
    if (!trimmed || !projectId) return
    try {
      const created = await create.mutateAsync({
        title: trimmed,
        description: description.trim() || undefined,
      })
      toast.success(isPersonal ? 'Личная задача создана' : 'Задача создана')
      setTitle('')
      setDescription('')
      onOpenChange(false)
      if (!openAfterCreate) return
      const to = createdTaskLocation({
        taskId: created.id,
        projectId,
        isPersonal,
        pathname: location.pathname,
        search: location.search,
      })
      // Тиком позже: на FAB смена маршрута размонтирует и кнопку, и этот диалог
      // в том же коммите, что и закрытие Radix, — а тогда `pointer-events:none`
      // с body может не сняться (тот же приём в FloatingActionButton).
      window.setTimeout(() => {
        navigate(to, {
          // Личный список ещё не перезапрошен — без хинта /my молча закрыл бы
          // карточку (см. resolvePersonalTaskParam).
          state: isPersonal ? { justCreatedTaskId: created.id, at: Date.now() } : undefined,
        })
      }, 0)
    } catch {
      // ввод сохраняем в форме; тост показывает глобальный onError мутаций
    }
  }

  // Писать некуда только если нет ни личного проекта, ни прав ни в одном
  // рабочем. Личный есть у каждого сотрудника с hub-ролью, так что это
  // редкий случай — но он обязан выглядеть объяснением, а не пустой формой.
  const nowhereToWrite = !personalProjectId && targets.length === 0

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form onSubmit={submit}>
          <DialogHeader>
            <DialogTitle>Новая задача</DialogTitle>
            <DialogDescription>
              {nowhereToWrite
                ? 'Вам пока некуда добавить задачу: в рабочих проектах вы наблюдатель, а личное пространство не заведено. Обратитесь к администратору.'
                : isPersonal
                  ? 'Без проекта — задача попадёт в ваши личные задачи, коллеги её не увидят.'
                  : 'Задача попадёт в выбранный проект и будет видна его участникам.'}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="task-project">Проект</Label>
              <select
                id="task-project"
                value={target}
                onChange={(e) => setTarget(e.target.value)}
                disabled={nowhereToWrite}
                className="flex h-9 w-full rounded-lg border border-glass-border bg-glass px-2 text-sm text-text focus:border-amber focus:outline-none"
              >
                {/* Прочерк первым и по умолчанию: задача «на себя» — самый
                    частый случай у того, кто не ведёт проектов. */}
                <option value={PERSONAL_TARGET}>—</option>
                {targets.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
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
