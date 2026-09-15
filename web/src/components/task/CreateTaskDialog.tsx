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
import { PeoplePicker } from '@/components/PeoplePicker'
import { SearchableSelect } from '@/components/ui/SearchableSelect'
import { useDelegateTask } from '@/hooks/useDelegated'
import { useMe } from '@/hooks/useMe'
import { useProjects } from '@/hooks/useProjects'
import { useCreateTask } from '@/hooks/useTasks'
import {
  createTaskReady,
  DELEGATE_TARGET,
  PERSONAL_TARGET,
  createTaskTargets,
  initialTarget,
  resolveProjectId,
} from '@/lib/createTaskTargets'
import { taskLocation } from '@/lib/taskLinks'

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
  const [delegateTo, setDelegateTo] = useState<string | null>(null)
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
  const isDelegate = target === DELEGATE_TARGET
  const create = useCreateTask(projectId ?? '')
  const delegate = useDelegateTask()

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = title.trim()
    if (!createTaskReady({ target, title, projectId, delegateTo })) return
    try {
      if (isDelegate && delegateTo) {
        // Поручение: задача уходит в личное пространство человека, и адрес её
        // карточки автору не нужен — он найдёт её в секции «Я поставил».
        await delegate.mutateAsync({
          employee_id: delegateTo,
          title: trimmed,
          description: description.trim() || undefined,
        })
        toast.success('Задача поручена лично')
        setTitle('')
        setDescription('')
        setDelegateTo(null)
        onOpenChange(false)
        return
      }
      if (!projectId) return
      const created = await create.mutateAsync({
        title: trimmed,
        description: description.trim() || undefined,
      })
      toast.success(isPersonal ? 'Личная задача создана' : 'Задача создана')
      setTitle('')
      setDescription('')
      onOpenChange(false)
      if (!openAfterCreate) return
      const to = taskLocation({
        taskId: created.id,
        projectId,
        personalProjectId: personalProjectId,
        pathname: location.pathname,
        search: location.search,
      })
      // Тиком позже: на FAB смена маршрута размонтирует и кнопку, и этот диалог
      // в том же коммите, что и закрытие Radix, — а тогда `pointer-events:none`
      // с body может не сняться (тот же приём в FloatingActionButton).
      //
      // Хинта «только что создана» больше нет (16.09): карточка на `/my`
      // открывается по `?task=` отдельным запросом и списка не ждёт, а раньше
      // она искала задачу в уже загруженном личном списке и без хинта
      // закрывалась сама.
      window.setTimeout(() => navigate(to), 0)
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
                : isDelegate
                  ? 'Задача ляжет в личные задачи сотрудника: увидите её только вы двое, остальные его личные задачи вам не откроются.'
                  : isPersonal
                    ? 'Без проекта — задача попадёт в ваши личные задачи, коллеги её не увидят.'
                    : 'Задача попадёт в выбранный проект и будет видна его участникам.'}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="task-project">Проект</Label>
              {/* «Мои задачи» первым и по умолчанию: задача «на себя» — самый
                  частый случай у того, кто не ведёт проектов. «Личные задачи
                  сотрудника…» последним: поручение — не «ещё один проект», а
                  отдельный адресат, и в общий список проектов его личное
                  пространство не попадает никогда.
                  Оба пункта закреплены (`pinnedTop`/`pinnedBottom`) и НЕ
                  участвуют в фильтрации: иначе набранный запрос прятал бы и
                  адресата по умолчанию, и единственный вход в поручение. */}
              <SearchableSelect
                id="task-project"
                sheetTitle="Куда"
                clearLabel={null}
                disabled={nowhereToWrite}
                value={target}
                onChange={(v) => setTarget(v ?? PERSONAL_TARGET)}
                pinnedTop={[{ value: PERSONAL_TARGET, label: 'Мои задачи' }]}
                pinnedBottom={[
                  { value: DELEGATE_TARGET, label: 'Личные задачи сотрудника…' },
                ]}
                options={targets.map((t) => ({ value: t.value, label: t.label }))}
              />
            </div>

            {isDelegate && (
              <div className="space-y-1.5">
                <Label htmlFor="task-delegate">Кому</Label>
                <PeoplePicker
                  value={delegateTo}
                  onChange={setDelegateTo}
                  placeholder="Выберите сотрудника"
                  sheetTitle="Кому поручить"
                  allowClear={false}
                />
              </div>
            )}

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
              disabled={create.isPending || delegate.isPending}
            >
              Отмена
            </Button>
            <Button
              type="submit"
              disabled={
                create.isPending ||
                delegate.isPending ||
                !createTaskReady({ target, title, projectId, delegateTo })
              }
            >
              {create.isPending || delegate.isPending
                ? 'Создаём…'
                : isDelegate
                  ? 'Поручить'
                  : 'Создать'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
