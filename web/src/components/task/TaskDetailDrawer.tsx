import * as DialogPrimitive from '@radix-ui/react-dialog'
import {
  Archive,
  ArrowRightLeft,
  Bell,
  Calendar,
  Trash2,
  CornerLeftUp,
  Flag,
  FolderOpen,
  Link as LinkIcon,
  MoreHorizontal,
  Repeat,
  Tag,
  Users,
  X,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { toast } from 'sonner'

import { Markdown } from '@/components/Markdown'
import { PeoplePickerMulti } from '@/components/PeoplePickerMulti'
import { QueryError } from '@/components/QueryError'
import { ShareDialog } from '@/components/share/ShareDialog'
import { DrawerSection } from '@/components/task/DrawerSection'
import { MoveTaskDialog } from '@/components/task/MoveTaskDialog'
import { SubtaskList } from '@/components/task/SubtaskList'
import { TaskDoneControl } from '@/components/task/TaskDoneControl'
import { TaskAttachments } from '@/components/task/TaskAttachments'
import { TaskLabels } from '@/components/task/TaskLabels'
import { TaskCustomFields } from '@/components/task/TaskCustomFields'
import { TaskDependencies } from '@/components/task/TaskDependencies'
import { TaskThread } from '@/components/task/TaskThread'
import { WatchControl } from '@/components/task/WatchControl'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/DropdownMenu'
import { AutoGrowTextarea } from '@/components/ui/AutoGrowTextarea'
import { Button } from '@/components/ui/Button'
import { ResponsiveDialog } from '@/components/ui/ResponsiveDialog'
import { SearchableSelect } from '@/components/ui/SearchableSelect'
import { Textarea } from '@/components/ui/Input'
import { PropertyRow, PropertyRows } from '@/components/ui/PropertyRows'
import { Skeleton, SkeletonRows } from '@/components/ui/Skeleton'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { useMe } from '@/hooks/useMe'
import { useToggleWatcher, useWatchers } from '@/hooks/useThreads'
import { useProject, useProjectMembers } from '@/hooks/useProjects'
import { useStages } from '@/hooks/useStages'
import {
  useArchiveTask,
  useDeleteTask,
  useTask,
  useTasks,
  useToggleAssignee,
  useClearRecurrence,
  useSetRecurrence,
  useToggleDone,
  useUpdateTask,
} from '@/hooks/useTasks'
import { RecurrenceDialog } from '@/components/task/RecurrenceDialog'
import { OptionButton } from '@/components/ui/OptionButton'
import { cn } from '@/lib/cn'
import {
  canSetRecurrence,
  describeRecurrence,
  recurrenceBlockReason,
} from '@/lib/taskRecurrence'
import { taskAssignees } from '@/lib/taskAssignees'
import { locationWithoutTask, projectLocation, taskLocation } from '@/lib/taskLinks'
import { MobileDateCell } from '@/components/ui/MobileDateCell'
import { dayKey, dueDayToIso, isOverdue, overdueDays } from '@/lib/taskDates'
import { describeTaskDeletion } from '@/lib/taskDeletion'
import { PRIORITY_LABEL, taskKey, type TaskPriority } from '@/lib/tasks'
import { plural } from '@/lib/typography'

interface TaskDetailDrawerProps {
  taskId: string | null
  /** Проект СТРАНИЦЫ. Внутри — только фолбэк на время загрузки задачи: всё
   *  остальное считается от `task.project_id` (см. `taskProjectId`). */
  projectId: string
  onClose: () => void
  /** Переключить drawer на другую задачу (родитель/подзадача). */
  onOpenTask?: (id: string) => void
  /** Открыть «Метки проекта» (страница решает, кому можно — `can_manage`). */
  onManageLabels?: () => void
}

const PRIORITIES: TaskPriority[] = ['low', 'medium', 'high', 'urgent']

/** Кнопка-вариант в наборе «Приоритет»: активный — амбер 30% с обводкой. */
/** Подпись свойства в <dl>: иконка + слово, 13/600 на --text2. */
function Dt({ icon: Icon, children }: { icon?: typeof Flag; children: React.ReactNode }) {
  return (
    <dt className="flex items-center gap-[7px] text-[13px] font-semibold text-text2">
      {Icon && <Icon className="h-4 w-4 shrink-0" strokeWidth={1.9} />}
      {children}
    </dt>
  )
}

/** Select этапа в карточке: max-width 320, 36px, r9, --surface (макет). */
/* Прочерк в «Колонке» означает «снять статус» — то есть явный `null`, а не
   «поле не передали». `SearchableSelect` отдаёт ровно `null`, поэтому
   отдельный конвертер значения селекта больше не нужен (был `stageValue`). */

/** Строка «Проект» на десктопе: один силуэт селекта, ДВА контрола (16.09).
 *  Имя — ссылка на страницу проекта; стрелка ⇄ — диалог переноса: у переезда
 *  есть цена (новый номер, отвал меток), и тихим выбором он быть не может,
 *  а цену называет сам диалог. Наблюдатель видит только имя. `overflow-hidden`
 *  на группе и `ring-inset` на сегментах — иначе фокус-ринг и hover сегмента
 *  торчат за скруглённую рамку. */
const PROJECT_GROUP =
  'inline-flex h-9 max-w-[320px] overflow-hidden rounded-[9px] border border-glass-border bg-surface font-body text-[14px] text-text'
const PROJECT_LINK =
  'flex min-w-0 items-center px-3 hover:bg-glass focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-amber/60'
const PROJECT_MOVE =
  'flex w-9 shrink-0 items-center justify-center border-l border-glass-border text-text2 hover:bg-glass hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-amber/60'

const STAGE_SELECT =
  'h-9 max-w-[320px] rounded-[9px] border border-glass-border bg-surface px-3 font-body text-[14px] text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60 disabled:cursor-default'

/** Прозрачный контрол справа в мобильной строке свойств: 16px, по правому краю. */
const MOBILE_CONTROL =
  'min-h-[46px] max-w-full appearance-none bg-transparent pr-2.5 text-right font-body text-[16px] text-text focus-visible:outline-none disabled:opacity-100'

/** Дата — значение поля, а не статус: силуэт чипа 26px, не бейджа. */
const DATE_INPUT =
  'inline-flex h-[26px] items-center rounded-md bg-surface px-2 font-body text-[12px] font-semibold text-text2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60 disabled:cursor-default'

export function TaskDetailDrawer({
  taskId,
  projectId,
  onClose,
  onOpenTask,
  onManageLabels,
}: TaskDetailDrawerProps) {
  const isDesktop = useIsDesktop()
  // Раскладка фиксируется при открытии (инвариант Dialog/ResponsiveDialog):
  // `modal` у Radix нельзя переключать на лету, а поворот планшета не должен
  // превращать панель в лист посреди правки. Пока карточка закрыта — следим
  // за вьюпортом; открылась — замораживаем.
  const [desktop, setDesktop] = useState(isDesktop)
  useEffect(() => {
    if (!taskId) setDesktop(isDesktop)
  }, [taskId, isDesktop])
  const contentRef = useRef<HTMLDivElement>(null)
  const taskQuery = useTask(taskId ?? undefined)
  const { data: task, isLoading } = taskQuery
  // Проект ЗАДАЧИ, а не проект страницы. Пока задача не загрузилась, они
  // совпадают; после переезда — расходятся, и карточка на проп-значении
  // показывала бы колонки и кастом-поля чужого проекта, а ключ в шапке
  // собирала бы из ключа старого проекта и уже нового номера («PLP-12» —
  // номера, которого нет нигде).
  const taskProjectId = task?.project_id ?? projectId
  const myPersonalId = useMe().data?.personal_project_id
  const project = useProject(taskProjectId)
  // Этапы проекта: статус в карточке — раскрывающийся список с их именами
  // (имена пользовательские, этапов сколько угодно — ряд чипов не годится).
  const stages = useStages(taskProjectId)
  // Права считает сервер: viewer → read-only, hub:admin вне членства → правит.
  // `project.data` ещё нет = «не знаем», а не «нельзя»: fail-closed по правам
  // (контролы заблокированы), но БЕЗ объяснения «вы наблюдатель». Иначе на
  // «Моих задачах», где карточка открывается на месте, плашка мелькала бы на
  // каждой рабочей задаче: `taskProjectId` известен только ПОСЛЕ загрузки
  // задачи, и запрос проекта стартует на RTT позже её.
  const readOnly = !project.data?.can_edit
  const rightsKnown = project.data !== undefined
  // Исполнитель закрывает свою задачу и двигает её по доске даже будучи
  // наблюдателем. Правило считает СЕРВЕР (TaskResponse.can_complete); `??` —
  // фолбэк для ручек, которые поле не заполняют (календарь, хронология,
  // оптимистичные объекты в кэше).
  const canStatus = task?.can_complete ?? !readOnly
  // Наблюдателю мало сказать «нельзя» — надо назвать, кого просить.
  // `GET /projects/{id}/members` открыт любой роли в проекте (включая
  // viewer), поэтому имя владельца доступно и ему.
  const members = useProjectMembers(readOnly && rightsKnown ? taskProjectId : undefined)
  const owner = members.data?.find((m) => m.role === 'owner')
  const update = useUpdateTask(taskProjectId)
  const toggleAssignee = useToggleAssignee(taskProjectId)
  // Состав наблюдателей: тот же запрос, что кормит колокольчик в WatchControl —
  // ключ один, лишнего похода нет.
  const watchers = useWatchers(taskId ?? undefined)
  const toggleWatcher = useToggleWatcher(taskId ?? '')
  const toggleDone = useToggleDone(taskProjectId)
  const archive = useArchiveTask(taskProjectId)
  const remove = useDeleteTask(taskProjectId)
  // Подзадачи считаем из того же кэша, что и `SubtaskList` — отдельный запрос
  // ради одной цифры в диалоге не нужен.
  const projectTasks = useTasks(taskProjectId)
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [dueAt, setDueAt] = useState('')
  const [startAt, setStartAt] = useState('')
  const [editingDesc, setEditingDesc] = useState(false)
  const [shareOpen, setShareOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [moveOpen, setMoveOpen] = useState(false)
  const [repeatOpen, setRepeatOpen] = useState(false)
  const setRecurrence = useSetRecurrence(taskProjectId)
  const clearRecurrence = useClearRecurrence(taskProjectId)
  // Гейты кнопки — зеркало сервера: 422 без срока, 409 на подзадаче.
  const repeatBlocked = task ? recurrenceBlockReason(task) : null
  const repeatAllowed = task ? canSetRecurrence(task) : false
  const navigate = useNavigate()
  const location = useLocation()
  // Адрес страницы проекта БЕЗ `?task=`: «открыть проект» — увидеть проект, а
  // не проект с этой же карточкой поверх. На той же странице снимается только
  // `task`, фильтры (`?view=board&f_*`) остаются.
  const projectTo = projectLocation({
    projectId: taskProjectId,
    personalProjectId: myPersonalId,
    pathname: location.pathname,
    search: location.search,
  })
  const openProject = (e: React.MouseEvent<HTMLAnchorElement>) => {
    // Cmd/Ctrl/Shift/средняя кнопка — браузер сам откроет новую вкладку.
    if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return
    e.preventDefault()
    onClose()
    // Карточка открыта на странице своего же проекта: `onClose` уже снял
    // `task`, второй переход на тот же адрес положил бы дубль в историю.
    if (projectTo === locationWithoutTask(location.pathname, location.search)) return
    // Тиком позже: мобильный лист — модальный Radix, и смена маршрута в одном
    // коммите с его закрытием оставляет `pointer-events:none` на body (тот же
    // приём в CreateTaskDialog и FloatingActionButton).
    window.setTimeout(() => navigate(projectTo), 0)
  }

  useEffect(() => {
    if (task) {
      setTitle(task.title)
      setDescription(task.description ?? '')
      // День в display tz, а не UTC-срез ISO: срок 12:00 МСК = 09:00Z, но
      // инстанты у границы суток давали вчерашнюю дату в поле.
      setDueAt(task.due_at ? dayKey(task.due_at) : '')
      setStartAt(task.start_at ? dayKey(task.start_at) : '')
    }
  }, [task])

  const saveTitle = async () => {
    if (!task || title.trim() === task.title) return
    try {
      await update.mutateAsync({ id: task.id, title: title.trim() })
    } catch {
      // тост показывает глобальный onError мутаций
    }
  }

  const saveDescription = async () => {
    if (!task || description === (task.description ?? '')) return
    try {
      await update.mutateAsync({ id: task.id, description })
    } catch {
      // тост показывает глобальный onError мутаций
    }
  }

  const saveDate = async (field: 'due_at' | 'start_at', val: string) => {
    if (!task) return
    // Полдень display tz — единая конвенция с CSV-импортом и ассистентом.
    const iso = val ? dueDayToIso(val) : null
    try {
      await update.mutateAsync({ id: task.id, [field]: iso })
    } catch {
      // тост показывает глобальный onError мутаций
    }
  }

  const key = taskKey(project.data?.key, task?.seq)
  const overdue = task ? isOverdue(task.due_at, task.done) : false

  return (
    // Десктоп — НЕмодальная панель (макет «Задача · десктоп»): список под ней
    // виден, кликабелен и скроллится, клик по другой строке переключает
    // карточку через ?task=. Телефон — модальный полноэкранный лист.
    <DialogPrimitive.Root
      key={desktop ? 'panel' : 'sheet'}
      open={!!taskId}
      onOpenChange={(o) => !o && onClose()}
      modal={!desktop}
    >
      <DialogPrimitive.Portal>
        {!desktop && (
          <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
        )}
        <DialogPrimitive.Content
          ref={contentRef}
          tabIndex={-1}
          // Описания у карточки нет по замыслу: её содержание — сама карточка.
          // Без явного снятия Radix ставит `aria-describedby` на id, которого в
          // документе нет, и пишет предупреждение в консоль — в том числе в
          // прод-сборке (guard'а по NODE_ENV в `DescriptionWarning` нет), а
          // консоль у нас единственный канал диагностики с телефона.
          aria-describedby={undefined}
          // Немодальный Radix закрывает слой и по клику, и по ФОКУСУ снаружи —
          // оба гасим: закрытие — крестик, Escape, пустой ?task=.
          onInteractOutside={desktop ? (e) => e.preventDefault() : undefined}
          // Авто-фокус — на сам контент, а не на первый фокусируемый элемент:
          // «Закрыть» получал фокус-ринг при каждом открытии (QA-0821 #14).
          onOpenAutoFocus={(e) => {
            e.preventDefault()
            contentRef.current?.focus()
          }}
          className={cn(
            'flex flex-col bg-bg-alt focus:outline-none',
            desktop
              ? // Панель 560 у правого края РАБОЧЕЙ ОБЛАСТИ: те же 12px
                // (--shell-gap), что у панели Shell, правые углы 20px, слева
                // волосяная граница и тень; z-40 — ниже меню и пикеров (z-50).
                'fixed inset-y-[var(--shell-gap)] right-[var(--shell-gap)] z-40 w-[560px] max-w-[calc(100vw-2*var(--shell-gap))] overflow-hidden rounded-r-[20px] border-l border-hair shadow-[-18px_0_48px_rgba(0,0,0,.35)] data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:slide-out-to-right-2 data-[state=open]:slide-in-from-right-2'
              : 'fixed inset-0 z-50 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:slide-out-to-bottom data-[state=open]:slide-in-from-bottom',
          )}
        >
          <DialogPrimitive.Title className="sr-only">
            Карточка задачи
          </DialogPrimitive.Title>

          <header
            className="shrink-0 border-b border-hair px-4 pb-3 lg:px-5 lg:pb-4 lg:pt-4"
            style={{ paddingTop: 'calc(env(safe-area-inset-top, 0px) + 12px)' }}
          >
            <div className="flex items-center gap-2">
              <span className="font-mono text-[13px] tracking-[0.02em] text-text2">
                {key ?? 'Задача'}
              </span>
              {task && (
                <button
                  type="button"
                  onClick={() => setShareOpen(true)}
                  aria-label="Скопировать ссылку"
                  title="Поделиться"
                  className="flex h-7 w-7 items-center justify-center rounded-lg text-text2 hover:bg-glass hover:text-text"
                >
                  <LinkIcon className="h-[15px] w-[15px]" strokeWidth={1.9} />
                </button>
              )}
              <span className="ml-auto flex items-center gap-1">
                {task && <WatchControl taskId={task.id} />}
                {task && !readOnly && (
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <button
                        type="button"
                        aria-label="Ещё"
                        className="flex h-11 w-11 items-center justify-center rounded-lg text-text2 hover:bg-glass hover:text-text lg:h-8 lg:w-8"
                      >
                        <MoreHorizontal className="h-4 w-4" strokeWidth={2.2} />
                      </button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      <DropdownMenuItem
                        onSelect={async () => {
                          try {
                            const wasArchived = !!task.archived_at
                            await archive.mutateAsync({
                              id: task.id,
                              archive: !wasArchived,
                            })
                            toast.success(
                              wasArchived ? 'Задача восстановлена' : 'Задача в архиве',
                              {
                                action: {
                                  label: 'Отменить',
                                  onClick: () =>
                                    archive.mutate({ id: task.id, archive: wasArchived }),
                                },
                              },
                            )
                            onClose()
                          } catch {
                            // тост показывает глобальный onError мутаций
                          }
                        }}
                      >
                        <Archive className="mr-2 h-4 w-4" />
                        {task.archived_at ? 'Восстановить' : 'В архив'}
                      </DropdownMenuItem>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem destructive onSelect={() => setDeleteOpen(true)}>
                        <Trash2 className="mr-2 h-4 w-4" />
                        Удалить задачу
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                )}
                <DialogPrimitive.Close
                  className="flex h-11 w-11 items-center justify-center rounded-lg text-text2 hover:bg-glass hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60 lg:h-8 lg:w-8"
                  aria-label="Закрыть"
                >
                  <X className="h-4 w-4" strokeWidth={2.2} />
                </DialogPrimitive.Close>
              </span>
            </div>

            {/* Ссылка на родительскую задачу. Имя проекта отсюда убрано
                (28.08): оно появилось строкой «Проект» в свойствах, и один и тот
                же текст дважды в одной карточке читается как два разных факта.
                Проект по-прежнему опознаётся в шапке — по префиксу ключа
                («RH-5»), который тут и остаётся. */}
            {task?.parent_task_id && onOpenTask && (
              <p className="mt-2 flex flex-wrap items-center gap-1.5 text-[13px] text-text2">
                <button
                  type="button"
                  onClick={() => onOpenTask(task.parent_task_id!)}
                  className="inline-flex items-center gap-1 underline underline-offset-2 hover:text-text"
                >
                  <CornerLeftUp className="h-3.5 w-3.5" />
                  К родительской
                </button>
              </p>
            )}

            {task && (
              // Состояние задачи — кружок слева от названия, тот же контрол,
              // что в строке списка и на карточке доски. Отдельным полем ниже
              // он занимал целую строку ради двух значений, а здесь читается
              // сразу и закрывает задачу одним нажатием.
              <div className="mt-2.5 flex items-start gap-3">
                <TaskDoneControl
                  done={task.done}
                  size={desktop ? 'row' : 'mobile'}
                  onToggle={canStatus ? () => toggleDone(task) : undefined}
                  // Кружок встаёт на оптическую середину ПЕРВОЙ строки
                  // заголовка (22px на десктопе, 20px на телефоне), а не по
                  // верху своего бокса. На телефоне вдобавок снимается левый
                  // отступ: он подобран под строку списка с её `pl-[13px]`,
                  // а в шапке карточки отступ `px-4`.
                  className={desktop ? 'mt-[4px]' : '-ml-2.5 -mt-[6px]'}
                />
                {/* Без прав контрол рендерится `aria-hidden` (иконка, не
                    кнопка), и состояние осталось бы только в цвете кружка. */}
                {!canStatus && (
                  <span className="sr-only">
                    {task.done ? 'Выполнена' : 'Не выполнена'}
                  </span>
                )}
                {/* Обёртка обязательна: className уходит на textarea и её
                    невидимый двойник, а корень AutoGrowTextarea — grid без
                    пропа для класса, и без min-w-0/flex-1 длинное название
                    распирает строку. */}
                <div className="min-w-0 flex-1">
                  {/* Заголовок — редактируемое поле с автовысотой:
                      переименование здесь основное действие, а без прав поле
                      readOnly. */}
                  <AutoGrowTextarea
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    onBlur={saveTitle}
                    readOnly={readOnly}
                    aria-label="Название задачи"
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault()
                        ;(e.target as HTMLTextAreaElement).blur()
                      }
                    }}
                    className={cn(
                      'block w-full rounded-lg border border-transparent bg-transparent px-0 py-0.5 font-display text-[20px] font-bold leading-[1.26] text-text focus-visible:border-amber focus-visible:outline-none lg:text-[22px] lg:leading-[1.24]',
                      // Зачёркнутое название — тот же признак «сделано», что в
                      // списке, на доске и в подзадачах. Каретку возвращаем
                      // явно: она наследует color, и в выполненной задаче
                      // курсор ввода стал бы блёклым.
                      task.done && 'text-text2 line-through caret-text',
                      readOnly ? 'cursor-default' : 'cursor-text',
                    )}
                  />
                </div>
              </div>
            )}

            {readOnly && rightsKnown && task && (
              <p className="mt-2.5 flex flex-wrap items-center gap-x-1.5 gap-y-1 rounded-[10px] border border-glass-border bg-tint px-[11px] py-[9px] text-[14px] leading-[1.45] text-text2">
                <span>
                  {canStatus
                    ? 'Вы наблюдатель проекта: можно только отметить статус своей задачи.'
                    : 'Вы наблюдатель проекта: поля доступны только для чтения.'}
                </span>
                {/* Владельца может не быть вовсе — его могли разжаловать или
                    убрать из проекта. Тогда строку про доступ не показываем:
                    «обратитесь к undefined» хуже молчания. */}
                {owner?.full_name && (
                  <span>
                    Запросить доступ — у владельца,{' '}
                    <span className="text-text">{owner.full_name}</span>.
                  </span>
                )}
              </p>
            )}
          </header>

          <div className="flex min-h-0 flex-1 flex-col gap-[22px] overflow-y-auto px-4 pb-7 pt-[18px] lg:px-5">
            {isLoading && (
              <div className="space-y-4">
                <Skeleton className="h-8 w-2/3" />
                <SkeletonRows rows={4} rowClassName="h-7" />
                <Skeleton className="h-24 w-full" />
              </div>
            )}
            {taskQuery.isError && (
              <QueryError
                error={taskQuery.error}
                onRetry={() => void taskQuery.refetch()}
                title="Не удалось загрузить задачу"
              />
            )}

            {task && !desktop && (
              // Мобильный блок свойств: один компактный контейнер строк
              // «свойство → значение», контрол справа, строка 48px. Ряды чипов
              // на телефоне превращались в стену из шести разнородных блоков.
              <PropertyRows>
                {/* Первой: на «Моих задачах» и в поиске карточка иначе не
                    говорит, из какого задача проекта. Два контрола внутри
                    (имя → страница проекта, ⇄ → перенос), поэтому строка
                    БЕЗ `onClick`: с ним `PropertyRow` рендерит `<button>`, а
                    кнопка в кнопке невалидна. */}
                <PropertyRow label="Проект">
                  {project.data ? (
                    <>
                      <Link
                        to={projectTo}
                        onClick={openProject}
                        className="inline-flex min-h-[46px] min-w-0 items-center pr-2.5 text-right text-[16px] text-text focus-visible:outline-none"
                      >
                        <span className="min-w-0 truncate">{project.data.name}</span>
                      </Link>
                      {!readOnly && (
                        <button
                          type="button"
                          onClick={() => setMoveOpen(true)}
                          aria-label="Перенести в другой проект"
                          className="flex h-[46px] w-11 shrink-0 items-center justify-center text-text2 active:bg-glass"
                        >
                          <ArrowRightLeft className="h-[18px] w-[18px]" strokeWidth={1.9} />
                        </button>
                      )}
                    </>
                  ) : (
                    <span className="truncate">—</span>
                  )}
                </PropertyRow>
                <PropertyRow label="Колонка">
                  {stages.data && stages.data.length > 0 ? (
                    // `bare`: в силуэте поля триггер стоял рамкой посреди
                    // прозрачных строк свойств (ОС владельца 16.09).
                    <SearchableSelect
                      sheetTitle="Колонка"
                      aria-label="Колонка"
                      variant="bare"
                      value={task.stage_id ?? null}
                      disabled={!canStatus}
                      onChange={(v) => update.mutate({ id: task.id, stage_id: v })}
                      className={cn(MOBILE_CONTROL, 'justify-end')}
                      options={stages.data.map((s) => ({ value: s.id, label: s.name }))}
                    />
                  ) : (
                    <span className="text-text2">—</span>
                  )}
                </PropertyRow>
                <PropertyRow label="Приоритет">
                  <select
                    value={task.priority}
                    disabled={readOnly}
                    aria-label="Приоритет"
                    onChange={(e) => update.mutate({ id: task.id, priority: e.target.value as TaskPriority })}
                    className={MOBILE_CONTROL}
                  >
                    {PRIORITIES.map((p) => (
                      <option key={p} value={p}>
                        {PRIORITY_LABEL[p]}
                      </option>
                    ))}
                  </select>
                </PropertyRow>
                <PropertyRow label="Старт">
                  <MobileDateCell
                    value={startAt}
                    ariaLabel="Дата старта"
                    readOnly={readOnly}
                    onChange={(v) => {
                      setStartAt(v)
                      void saveDate('start_at', v)
                    }}
                  />
                </PropertyRow>
                <PropertyRow label="Срок">
                  <MobileDateCell
                    value={dueAt}
                    ariaLabel="Срок"
                    readOnly={readOnly}
                    onChange={(v) => {
                      setDueAt(v)
                      void saveDate('due_at', v)
                    }}
                    className={cn(overdue && 'font-semibold text-red')}
                  >
                    {overdue && task.due_at && (
                      <span className="shrink-0 text-[13px] font-semibold text-red">
                        −{overdueDays(task.due_at)} дн
                      </span>
                    )}
                  </MobileDateCell>
                </PropertyRow>
                {/* Повтор — ОТДЕЛЬНОЙ строкой, а не внутри ячейки срока: там
                    невидимый input[type=date] растянут на всю ячейку и перехватил
                    бы тап (ОС 27.08 про MobileDateCell). */}
                <PropertyRow
                  label="Повтор"
                  onClick={!readOnly && repeatAllowed ? () => setRepeatOpen(true) : undefined}
                >
                  <span className={cn('truncate', !task.recurrence && 'text-text2')}>
                    {task.recurrence ? describeRecurrence(task.recurrence) : '—'}
                  </span>
                </PropertyRow>
                {/* Кастом-поля — теми же строками 48px, что Этап/Приоритет/Срок
                    (макет «Задача · мобильный»), а не стопкой «подпись + инпут»
                    (QA-0821 #14). */}
                <TaskCustomFields variant="mobile" taskId={task.id} projectId={taskProjectId} />
              </PropertyRows>
            )}

            {task && (
              <>
                <dl className="m-0 grid grid-cols-1 items-start gap-x-3.5 gap-y-3 lg:grid-cols-[112px_1fr] lg:items-center lg:gap-y-2.5">
                  {desktop && (
                    <>
                      <Dt icon={FolderOpen}>Проект</Dt>
                      <dd className="m-0 min-w-0">
                        {project.data ? (
                          <span className={PROJECT_GROUP}>
                            <Link
                              to={projectTo}
                              onClick={openProject}
                              title="Открыть проект"
                              className={PROJECT_LINK}
                            >
                              <span className="min-w-0 truncate">{project.data.name}</span>
                            </Link>
                            {!readOnly && (
                              <button
                                type="button"
                                onClick={() => setMoveOpen(true)}
                                aria-label="Перенести в другой проект"
                                title="Перенести в другой проект"
                                className={PROJECT_MOVE}
                              >
                                <ArrowRightLeft className="h-4 w-4" strokeWidth={1.9} />
                              </button>
                            )}
                          </span>
                        ) : (
                          <span className="text-[14px] text-text">—</span>
                        )}
                      </dd>

                      <Dt icon={Flag}>Колонка</Dt>
                      <dd className="m-0">
                        {/* Имена колонок пользовательские и их сколько угодно —
                            раскрывающийся список, а не ряд чипов. Прочерк —
                            «без статуса»: задача уходит с доски, оставаясь
                            в списке и поиске (0046). */}
                        {stages.data && stages.data.length > 0 ? (
                          <SearchableSelect
                            sheetTitle="Колонка"
                            aria-label="Колонка"
                            value={task.stage_id ?? null}
                            disabled={!canStatus}
                            onChange={(v) => update.mutate({ id: task.id, stage_id: v })}
                            className={STAGE_SELECT}
                            options={stages.data.map((s) => ({ value: s.id, label: s.name }))}
                          />
                        ) : (
                          <span className="text-text2">—</span>
                        )}
                      </dd>

                      <Dt icon={Tag}>Приоритет</Dt>
                      <dd className="m-0 flex flex-wrap gap-1">
                        {PRIORITIES.map((p) => (
                          <OptionButton
                            key={p}
                            active={task.priority === p}
                            disabled={readOnly}
                            onClick={() => update.mutate({ id: task.id, priority: p })}
                          >
                            {PRIORITY_LABEL[p]}
                          </OptionButton>
                        ))}
                      </dd>
                    </>
                  )}

                  <Dt icon={Users}>Исполнители</Dt>
                  <dd className="m-0 min-w-0">
                    <PeoplePickerMulti
                      variant="chips"
                      sheetTitle="Исполнители"
                      value={taskAssignees(task)}
                      onToggle={(person, next) =>
                        toggleAssignee.mutate({ taskId: task.id, person, next })
                      }
                      // Одним PATCH'ем, а не циклом по onToggle: replace-семантика
                      // снимает всех в одной транзакции и даёт одно событие в
                      // ленте вместо N.
                      onClearAll={() =>
                        update.mutate({
                          id: task.id,
                          assignee_ids: [],
                          __optimistic: {
                            assignees: [],
                            assignee: null,
                            assignee_id: null,
                          },
                        })
                      }
                      // Намеренно НЕ отключаем на isPending: иначе меню замирает
                      // после каждого тоггла. Состояние ведёт оптимистичный кэш.
                      disabled={readOnly}
                    />
                  </dd>

                  {/* Наблюдатели (02.09): редактор подписывает других; не-участник
                      получает viewer-членство на сервере. Себя viewer подписывает
                      колокольчиком в шапке — он и остаётся его инструментом. */}
                  <Dt icon={Bell}>Наблюдатели</Dt>
                  <dd className="m-0 min-w-0">
                    <PeoplePickerMulti
                      variant="chips"
                      sheetTitle="Наблюдатели"
                      value={(watchers.data ?? []).map((w) => ({
                        employee_id: w.employee_id,
                        email: w.email,
                        full_name: w.full_name,
                      }))}
                      onToggle={(person, next) =>
                        toggleWatcher.mutate({
                          person: {
                            employee_id: person.employee_id,
                            email: person.email,
                            full_name: person.full_name,
                            added_reason: 'manual',
                            added_at: new Date().toISOString(),
                          },
                          next,
                        })
                      }
                      disabled={readOnly}
                      max={50}
                      placeholder="Никто не следит"
                      nounGenitivePlural="наблюдателей"
                      removeAriaPrefix="Снять наблюдателя"
                    />
                  </dd>

                  {desktop && (
                    <>
                      <Dt icon={Calendar}>Старт</Dt>
                      <dd className="m-0">
                        <input
                          type="date"
                          value={startAt}
                          disabled={readOnly}
                          aria-label="Дата старта"
                          onChange={(e) => {
                            setStartAt(e.target.value)
                            void saveDate('start_at', e.target.value)
                          }}
                          className={DATE_INPUT}
                        />
                      </dd>

                      <Dt icon={Calendar}>Срок</Dt>
                      <dd className="m-0 flex flex-wrap items-center gap-2">
                        <input
                          type="date"
                          value={dueAt}
                          disabled={readOnly}
                          aria-label="Срок"
                          onChange={(e) => {
                            setDueAt(e.target.value)
                            void saveDate('due_at', e.target.value)
                          }}
                          className={cn(
                            DATE_INPUT,
                            overdue && 'bg-red font-bold text-bg',
                          )}
                        />
                        {overdue && task.due_at && (
                          <span className="text-[14px] text-red">
                            просрочено на {plural(overdueDays(task.due_at), 'день', 'дня', 'дней')}
                          </span>
                        )}
                        {/* Повтор живёт в строке срока: он и есть свойство
                            срока. Силуэт — тот же чип 26px, что у даты. */}
                        {!readOnly && (
                          <button
                            type="button"
                            onClick={() => setRepeatOpen(true)}
                            disabled={!repeatAllowed}
                            title={repeatBlocked ?? undefined}
                            aria-label="Повтор задачи"
                            className={cn(
                              DATE_INPUT,
                              'gap-1',
                              task.recurrence && 'bg-amber/30 text-text',
                              !repeatAllowed && 'opacity-60',
                            )}
                          >
                            <Repeat className="h-3.5 w-3.5" strokeWidth={1.9} />
                            {task.recurrence ? describeRecurrence(task.recurrence) : 'Повтор'}
                          </button>
                        )}
                      </dd>
                    </>
                  )}

                  <Dt icon={Tag}>Метки</Dt>
                  <dd className="m-0 min-w-0">
                    <TaskLabels
                      bare
                      taskId={task.id}
                      projectId={taskProjectId}
                      canEdit={!readOnly}
                      onManageLabels={project.data?.can_manage ? onManageLabels : undefined}
                    />
                  </dd>

                  {desktop && (
                    <TaskCustomFields
                      variant="rows"
                      taskId={task.id}
                      projectId={taskProjectId}
                    />
                  )}
                </dl>

                <DrawerSection title="Описание">
                  {editingDesc && !readOnly ? (
                    <Textarea
                      autoFocus
                      rows={6}
                      value={description}
                      onChange={(e) => setDescription(e.target.value)}
                      onBlur={() => {
                        void saveDescription()
                        setEditingDesc(false)
                      }}
                      placeholder="Что нужно сделать? Поддерживается markdown."
                    />
                  ) : description ? (
                    <div
                      role={readOnly ? undefined : 'button'}
                      tabIndex={readOnly ? undefined : 0}
                      onClick={readOnly ? undefined : () => setEditingDesc(true)}
                      onKeyDown={
                        readOnly
                          ? undefined
                          : (e) => {
                              if (e.key === 'Enter') setEditingDesc(true)
                            }
                      }
                      className={cn(
                        'rounded-lg border border-transparent px-1 py-0.5 text-[17px] leading-[1.6] text-text',
                        !readOnly &&
                          'cursor-text hover:border-glass-border focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60',
                      )}
                      title={readOnly ? undefined : 'Нажмите, чтобы редактировать'}
                    >
                      <Markdown text={description} />
                    </div>
                  ) : (
                    <button
                      type="button"
                      onClick={() => setEditingDesc(true)}
                      disabled={readOnly}
                      className="w-full rounded-lg border border-dashed border-glass-border px-3 py-2.5 text-left text-[15px] text-text2 hover:border-amber hover:text-text disabled:cursor-default disabled:hover:border-glass-border disabled:hover:text-text2"
                    >
                      Что нужно сделать? Поддерживается markdown.
                    </button>
                  )}
                </DrawerSection>

                {!task.parent_task_id && (
                  <SubtaskList
                    taskId={task.id}
                    projectId={taskProjectId}
                    canEdit={!readOnly}
                    onOpenTask={onOpenTask}
                  />
                )}

                <TaskDependencies
                  taskId={task.id}
                  projectId={taskProjectId}
                  canEdit={!readOnly}
                />

                <TaskAttachments taskId={task.id} canEdit={!readOnly} />

                <TaskThread taskId={task.id} />
              </>
            )}
          </div>

          {/* Мобильный футер — ОДНО действие: закрыть задачу (или вернуть).
              Поле «Комментарий…» отсюда убрано (28.08): оно только скроллило к
              композеру, который и так стоит в теле карточки. Sticky, не fixed:
              fixed под клавиатурой iOS уезжает вместе с visual viewport.
              Показывать нечего — футера нет вовсе: полоса с отступом под
              safe-area и пустотой внутри читается как сломанная вёрстка. */}
          {task && !desktop && canStatus && (
            <footer
              className="sticky bottom-0 z-10 flex shrink-0 items-center gap-2 border-t border-hair bg-bg-alt px-4 pt-2.5"
              style={{ paddingBottom: 'calc(env(safe-area-inset-bottom, 0) + 10px)' }}
            >
              <button
                type="button"
                onClick={() => toggleDone(task)}
                className={cn(
                  'flex h-12 w-full items-center justify-center rounded-xl px-5 text-[15px] font-bold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60',
                  task.done
                    ? 'border border-glass-border text-text'
                    : 'bg-amber text-on-amber',
                )}
              >
                {task.done ? 'Вернуть' : 'Готово'}
              </button>
            </footer>
          )}
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
      {repeatOpen && task && (
        <RecurrenceDialog
          current={task.recurrence ?? null}
          blockedReason={repeatBlocked}
          saving={setRecurrence.isPending || clearRecurrence.isPending}
          onSave={(body) =>
            setRecurrence.mutate(
              { id: task.id, ...body },
              { onSuccess: () => setRepeatOpen(false) },
            )
          }
          onClear={() =>
            clearRecurrence.mutate(task.id, { onSuccess: () => setRepeatOpen(false) })
          }
          onClose={() => setRepeatOpen(false)}
        />
      )}
      {task && (
        <MoveTaskDialog
          open={moveOpen}
          onOpenChange={setMoveOpen}
          taskId={task.id}
          projectId={taskProjectId}
          currentStageName={
            stages.data?.find((s) => s.id === task.stage_id)?.name ?? null
          }
          // Уводим на новое место. Без этого проп `projectId` страницы остаётся
          // старым, а с ним — колонки, кастом-поля и метки чужого проекта.
          // Через `taskLocation`, а не прямым адресом: перенос В ЛИЧНОЕ ведёт
          // на «Мои задачи» — страницы личного проекта больше нет, она
          // редиректит (и ссылка теряла бы `?task=`, не будь редирект аккуратен).
          onMoved={(report) => {
            const to = taskLocation({
              taskId: task.id,
              projectId: report.project_id,
              personalProjectId: myPersonalId,
            })
            navigate(`${to.pathname}${to.search}`)
          }}
        />
      )}
      {task && (
        <ShareDialog
          open={shareOpen}
          onOpenChange={setShareOpen}
          scope="task"
          entityId={task.id}
          entityLabel={task.title}
        />
      )}
      {task && (
        <ResponsiveDialog
          open={deleteOpen}
          // Пока удаляем — диалог держим: исчезнувшая модалка читается как
          // «получилось», даже если сервер ответил отказом.
          onOpenChange={(v) => !remove.isPending && setDeleteOpen(v)}
          title={`Удалить задачу «${task.title}»?`}
          description={describeTaskDeletion(
            (projectTasks.data ?? []).filter(
              (t) => t.parent_task_id === task.id && !t.archived_at,
            ).length,
          )}
          desktopWidth={440}
          footer={
            <>
              <Button
                variant="secondary"
                onClick={() => setDeleteOpen(false)}
                disabled={remove.isPending}
              >
                Отмена
              </Button>
              <Button
                variant="destructive"
                disabled={remove.isPending}
                onClick={async () => {
                  try {
                    await remove.mutateAsync(task.id)
                    toast.success('Задача удалена')
                    setDeleteOpen(false)
                    // Карточку закрываем ПОСЛЕ успеха: `?task=` иначе остался
                    // бы висеть на несуществующей задаче.
                    onClose()
                  } catch {
                    // тост показывает глобальный onError мутаций
                  }
                }}
              >
                {remove.isPending ? 'Удаляем…' : 'Удалить'}
              </Button>
            </>
          }
        >
          <span className="sr-only">Подтверждение удаления задачи</span>
        </ResponsiveDialog>
      )}
    </DialogPrimitive.Root>
  )
}
