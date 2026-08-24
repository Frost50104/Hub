import * as DialogPrimitive from '@radix-ui/react-dialog'
import {
  Archive,
  Calendar,
  CornerLeftUp,
  Flag,
  Link as LinkIcon,
  MoreHorizontal,
  Tag,
  Users,
  X,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'

import { Markdown } from '@/components/Markdown'
import { PeoplePickerMulti } from '@/components/PeoplePickerMulti'
import { QueryError } from '@/components/QueryError'
import { ShareDialog } from '@/components/share/ShareDialog'
import { DrawerSection } from '@/components/task/DrawerSection'
import { SubtaskList } from '@/components/task/SubtaskList'
import { TaskAttachments } from '@/components/task/TaskAttachments'
import { TaskLabels } from '@/components/task/TaskLabels'
import { TaskCustomFields } from '@/components/task/TaskCustomFields'
import { TaskDependencies } from '@/components/task/TaskDependencies'
import { TaskThread } from '@/components/task/TaskThread'
import { TaskWatchers } from '@/components/task/TaskWatchers'
import { WatchControl } from '@/components/task/WatchControl'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/DropdownMenu'
import { AutoGrowTextarea } from '@/components/ui/AutoGrowTextarea'
import { Textarea } from '@/components/ui/Input'
import { PropertyRow, PropertyRows } from '@/components/ui/PropertyRows'
import { Skeleton, SkeletonRows } from '@/components/ui/Skeleton'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { useProject, useProjectMembers, useProjectSections } from '@/hooks/useProjects'
import { useStages } from '@/hooks/useStages'
import {
  useArchiveTask,
  useTask,
  useToggleAssignee,
  useToggleDone,
  useUpdateTask,
} from '@/hooks/useTasks'
import { cn } from '@/lib/cn'
import { taskAssignees } from '@/lib/taskAssignees'
import { dayKey, dueDayToIso, isOverdue, overdueDays } from '@/lib/taskDates'
import {
  PRIORITY_LABEL,
  STATUS_LABEL,
  taskKey,
  type TaskPriority,
  type TaskStatus,
} from '@/lib/tasks'
import { plural } from '@/lib/typography'

interface TaskDetailDrawerProps {
  taskId: string | null
  projectId: string
  onClose: () => void
  /** Переключить drawer на другую задачу (родитель/подзадача). */
  onOpenTask?: (id: string) => void
  /** Открыть «Метки проекта» (страница решает, кому можно — `can_manage`). */
  onManageLabels?: () => void
}

const STATUSES: TaskStatus[] = ['todo', 'in_progress', 'in_review', 'done']
const PRIORITIES: TaskPriority[] = ['low', 'medium', 'high', 'urgent']

/** Кнопка-вариант в наборе «Статус»/«Приоритет». */
function OptionButton({
  active,
  disabled,
  tone,
  onClick,
  children,
}: {
  active: boolean
  disabled: boolean
  /** Активный статус — плотный амбер, активный приоритет — амбер 30% с обводкой. */
  tone: 'solid' | 'tint'
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        'inline-flex min-h-[30px] items-center rounded-lg px-2.5 text-[13px] font-semibold transition-colors',
        disabled ? 'cursor-default' : 'cursor-pointer',
        active
          ? tone === 'solid'
            ? 'bg-amber text-on-amber'
            : 'bg-amber/30 text-text shadow-[inset_0_0_0_1px_color-mix(in_srgb,rgb(var(--amber))_55%,transparent)]'
          : disabled
            ? 'bg-tint text-text2'
            : 'bg-surface text-text2 hover:text-text',
      )}
    >
      {children}
    </button>
  )
}

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
  const project = useProject(projectId)
  const sections = useProjectSections(projectId)
  // Этапы проекта: статус в карточке — раскрывающийся список с их именами
  // (имена пользовательские, этапов сколько угодно — ряд чипов не годится).
  const stages = useStages(projectId)
  // Права считает сервер: viewer → read-only, hub:admin вне членства → правит.
  const readOnly = !project.data?.can_edit
  // Исполнитель меняет статус и этап своей задачи даже будучи наблюдателем.
  // Правило считает СЕРВЕР (TaskResponse.can_set_status); `??` — фолбэк для
  // ручек, которые поле не заполняют (календарь, хронология, оптимистичные
  // объекты в кэше).
  const canStatus = task?.can_set_status ?? !readOnly
  // Наблюдателю мало сказать «нельзя» — надо назвать, кого просить.
  // `GET /projects/{id}/members` открыт любой роли в проекте (включая
  // viewer), поэтому имя владельца доступно и ему.
  const members = useProjectMembers(readOnly ? projectId : undefined)
  const owner = members.data?.find((m) => m.role === 'owner')
  const update = useUpdateTask(projectId)
  const toggleAssignee = useToggleAssignee(projectId)
  const toggleDone = useToggleDone(projectId)
  const archive = useArchiveTask(projectId)
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [dueAt, setDueAt] = useState('')
  const [startAt, setStartAt] = useState('')
  const [editingDesc, setEditingDesc] = useState(false)
  const [shareOpen, setShareOpen] = useState(false)

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
  const sectionName = task?.section_id
    ? (sections.data?.find((s) => s.id === task.section_id)?.name ?? null)
    : null
  const overdue = task ? isOverdue(task.due_at, task.status) : false

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

            {/* Хлебные крошки: проект / секция / родительская задача. */}
            <p className="mt-2 flex flex-wrap items-center gap-1.5 text-[13px] text-text2">
              {project.data && <span className="truncate">{project.data.name}</span>}
              {sectionName && (
                <>
                  <span aria-hidden>/</span>
                  <span className="truncate">{sectionName}</span>
                </>
              )}
              {task?.parent_task_id && onOpenTask && (
                <>
                  <span aria-hidden>/</span>
                  <button
                    type="button"
                    onClick={() => onOpenTask(task.parent_task_id!)}
                    className="inline-flex items-center gap-1 underline underline-offset-2 hover:text-text"
                  >
                    <CornerLeftUp className="h-3.5 w-3.5" />
                    К родительской
                  </button>
                </>
              )}
            </p>

            {task && (
              // Заголовок — редактируемое поле с автовысотой: переименование
              // здесь основное действие, а без прав поле readOnly.
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
                  'mt-2.5 block w-full rounded-lg border border-transparent bg-transparent px-0 py-0.5 font-display text-[20px] font-bold leading-[1.26] text-text focus-visible:border-amber focus-visible:outline-none lg:text-[22px] lg:leading-[1.24]',
                  readOnly ? 'cursor-default' : 'cursor-text',
                )}
              />
            )}

            {readOnly && task && (
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
                <PropertyRow label="Этап">
                  {stages.data && stages.data.length > 0 ? (
                    <select
                      value={task.stage_id ?? ''}
                      disabled={!canStatus}
                      aria-label="Этап"
                      onChange={(e) => update.mutate({ id: task.id, stage_id: e.target.value })}
                      className={MOBILE_CONTROL}
                    >
                      {!task.stage_id && <option value="">—</option>}
                      {stages.data.map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.name}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <select
                      value={task.status}
                      disabled={!canStatus}
                      aria-label="Статус"
                      onChange={(e) => update.mutate({ id: task.id, status: e.target.value as TaskStatus })}
                      className={MOBILE_CONTROL}
                    >
                      {STATUSES.map((s) => (
                        <option key={s} value={s}>
                          {STATUS_LABEL[s]}
                        </option>
                      ))}
                    </select>
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
                  <input
                    type="date"
                    value={startAt}
                    disabled={readOnly}
                    aria-label="Дата старта"
                    onChange={(e) => {
                      setStartAt(e.target.value)
                      void saveDate('start_at', e.target.value)
                    }}
                    className={MOBILE_CONTROL}
                  />
                </PropertyRow>
                <PropertyRow label="Срок">
                  <span className="flex items-center gap-2">
                    {overdue && task.due_at && (
                      <span className="text-[13px] font-semibold text-red">
                        −{overdueDays(task.due_at)} дн
                      </span>
                    )}
                    <input
                      type="date"
                      value={dueAt}
                      disabled={readOnly}
                      aria-label="Срок"
                      onChange={(e) => {
                        setDueAt(e.target.value)
                        void saveDate('due_at', e.target.value)
                      }}
                      className={cn(MOBILE_CONTROL, overdue && 'font-semibold text-red')}
                    />
                  </span>
                </PropertyRow>
                {/* Кастом-поля — теми же строками 48px, что Этап/Приоритет/Срок
                    (макет «Задача · мобильный»), а не стопкой «подпись + инпут»
                    (QA-0821 #14). */}
                <TaskCustomFields variant="mobile" taskId={task.id} projectId={projectId} />
              </PropertyRows>
            )}

            {task && (
              <>
                <dl className="m-0 grid grid-cols-1 items-start gap-x-3.5 gap-y-3 lg:grid-cols-[112px_1fr] lg:items-center lg:gap-y-2.5">
                  {desktop && (
                    <>
                      <Dt icon={Flag}>Этап</Dt>
                      <dd className="m-0">
                        {/* Статус = колонка доски: имена этапов пользовательские
                            и их сколько угодно — раскрывающийся список, а не ряд
                            чипов. Проект без этапов (окно деплоя) — 4 системных. */}
                        {stages.data && stages.data.length > 0 ? (
                          <select
                            value={task.stage_id ?? ''}
                            disabled={!canStatus}
                            aria-label="Этап"
                            onChange={(e) => update.mutate({ id: task.id, stage_id: e.target.value })}
                            className={STAGE_SELECT}
                          >
                            {!task.stage_id && <option value="">—</option>}
                            {stages.data.map((s) => (
                              <option key={s.id} value={s.id}>
                                {s.name}
                              </option>
                            ))}
                          </select>
                        ) : (
                          <span className="flex flex-wrap gap-1">
                            {STATUSES.map((s) => (
                              <OptionButton
                                key={s}
                                active={task.status === s}
                                disabled={!canStatus}
                                tone="solid"
                                onClick={() => update.mutate({ id: task.id, status: s })}
                              >
                                {STATUS_LABEL[s]}
                              </OptionButton>
                            ))}
                          </span>
                        )}
                      </dd>

                      <Dt icon={Tag}>Приоритет</Dt>
                      <dd className="m-0 flex flex-wrap gap-1">
                        {PRIORITIES.map((p) => (
                          <OptionButton
                            key={p}
                            active={task.priority === p}
                            disabled={readOnly}
                            tone="tint"
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
                      </dd>
                    </>
                  )}

                  <Dt icon={Tag}>Метки</Dt>
                  <dd className="m-0 min-w-0">
                    <TaskLabels
                      bare
                      taskId={task.id}
                      projectId={projectId}
                      canEdit={!readOnly}
                      onManageLabels={project.data?.can_manage ? onManageLabels : undefined}
                    />
                  </dd>

                  {desktop && (
                    <TaskCustomFields
                      variant="rows"
                      taskId={task.id}
                      projectId={projectId}
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
                    projectId={projectId}
                    canEdit={!readOnly}
                    onOpenTask={onOpenTask}
                  />
                )}

                <TaskDependencies
                  taskId={task.id}
                  projectId={projectId}
                  canEdit={!readOnly}
                />

                <TaskAttachments taskId={task.id} canEdit={!readOnly} />

                <TaskThread taskId={task.id} />

                <TaskWatchers taskId={task.id} />
              </>
            )}
          </div>

          {/* Мобильный футер: «Комментарий…» ставит курсор в композер треда,
              «Готово» закрывает задачу (или возвращает). Sticky, не fixed:
              fixed под клавиатурой iOS уезжает вместе с visual viewport. */}
          {task && !desktop && (
            <footer
              className="sticky bottom-0 z-10 flex shrink-0 items-center gap-2 border-t border-hair bg-bg-alt px-4 pt-2.5"
              style={{ paddingBottom: 'calc(env(safe-area-inset-bottom, 0) + 10px)' }}
            >
              {readOnly ? (
                <>
                  <span className="min-w-0 flex-1 text-[14px] text-text2">
                    Комментировать может участник проекта.
                  </span>
                  <WatchControl taskId={task.id} />
                  {/* Единственный способ закрыть задачу с телефона: без этой
                      ветки исполнитель-наблюдатель видел бы карточку своей
                      задачи вообще без действия. */}
                  {canStatus && (
                    <button
                      type="button"
                      onClick={() => toggleDone(task)}
                      className={cn(
                        'flex h-12 shrink-0 items-center justify-center rounded-xl px-5 text-[15px] font-bold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60',
                        task.status === 'done'
                          ? 'border border-glass-border text-text'
                          : 'bg-amber text-on-amber',
                      )}
                    >
                      {task.status === 'done' ? 'Вернуть' : 'Готово'}
                    </button>
                  )}
                </>
              ) : (
                <>
                  <button
                    type="button"
                    onClick={() => {
                      const el = document.querySelector<HTMLTextAreaElement>(
                        '#task-thread-composer textarea',
                      )
                      el?.scrollIntoView({ block: 'center', behavior: 'smooth' })
                      el?.focus()
                    }}
                    className="flex h-12 min-w-0 flex-1 items-center rounded-xl border border-glass-border bg-tint px-4 text-left text-[15px] text-text2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
                  >
                    Комментарий…
                  </button>
                  <button
                    type="button"
                    onClick={() => toggleDone(task)}
                    className={cn(
                      'flex h-12 shrink-0 items-center justify-center rounded-xl px-5 text-[15px] font-bold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60',
                      task.status === 'done'
                        ? 'border border-glass-border text-text'
                        : 'bg-amber text-on-amber',
                    )}
                  >
                    {task.status === 'done' ? 'Вернуть' : 'Готово'}
                  </button>
                </>
              )}
            </footer>
          )}
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
      {task && (
        <ShareDialog
          open={shareOpen}
          onOpenChange={setShareOpen}
          scope="task"
          entityId={task.id}
          entityLabel={task.title}
        />
      )}
    </DialogPrimitive.Root>
  )
}
