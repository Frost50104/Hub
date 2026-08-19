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
import { useEffect, useState } from 'react'
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
import { Skeleton, SkeletonRows } from '@/components/ui/Skeleton'
import { useProject, useProjectSections } from '@/hooks/useProjects'
import {
  useArchiveTask,
  useTask,
  useToggleAssignee,
  useUpdateTask,
} from '@/hooks/useTasks'
import { cn } from '@/lib/cn'
import { taskAssignees } from '@/lib/taskAssignees'
import { isOverdue, overdueDays } from '@/lib/taskDates'
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

/** Дата — значение поля, а не статус: силуэт чипа 26px, не бейджа. */
const DATE_INPUT =
  'inline-flex h-[26px] items-center rounded-md bg-surface px-2 font-body text-[12px] font-semibold text-text2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60 disabled:cursor-default'

export function TaskDetailDrawer({
  taskId,
  projectId,
  onClose,
  onOpenTask,
}: TaskDetailDrawerProps) {
  const taskQuery = useTask(taskId ?? undefined)
  const { data: task, isLoading } = taskQuery
  const project = useProject(projectId)
  const sections = useProjectSections(projectId)
  // Права считает сервер: viewer → read-only, hub:admin вне членства → правит.
  const readOnly = !project.data?.can_edit
  const update = useUpdateTask(projectId)
  const toggleAssignee = useToggleAssignee(projectId)
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
      setDueAt(task.due_at ? task.due_at.slice(0, 10) : '')
      setStartAt(task.start_at ? task.start_at.slice(0, 10) : '')
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
    const iso = val ? new Date(val + 'T12:00:00').toISOString() : null
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
    <DialogPrimitive.Root open={!!taskId} onOpenChange={(o) => !o && onClose()}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
        <DialogPrimitive.Content
          className={cn(
            'fixed z-50 flex flex-col bg-bg-alt focus:outline-none',
            // Мобильный — полноэкранный лист снизу.
            'inset-0',
            'data-[state=open]:animate-in data-[state=closed]:animate-out',
            'data-[state=closed]:slide-out-to-bottom data-[state=open]:slide-in-from-bottom',
            // Десктоп — панель 560px у правого края, с волосяной границей и
            // тенью; ширина из спеки (была 480 — свойства не помещались в две
            // колонки и переносились).
            'lg:inset-y-0 lg:left-auto lg:right-0 lg:w-[560px] lg:border-l lg:border-hair lg:shadow-[-18px_0_48px_rgba(0,0,0,.35)]',
            'lg:data-[state=closed]:slide-out-to-right-2 lg:data-[state=open]:slide-in-from-right-2',
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
              <p className="mt-2.5 flex items-center gap-2 rounded-[10px] border border-glass-border bg-tint px-[11px] py-[9px] text-[14px] leading-[1.45] text-text2">
                Вы наблюдатель проекта: поля доступны только для чтения.
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

            {task && (
              <>
                <dl className="m-0 grid grid-cols-1 items-start gap-x-3.5 gap-y-3 lg:grid-cols-[112px_1fr] lg:items-center lg:gap-y-2.5">
                  <Dt icon={Flag}>Статус</Dt>
                  <dd className="m-0 flex flex-wrap gap-1">
                    {STATUSES.map((s) => (
                      <OptionButton
                        key={s}
                        active={task.status === s}
                        disabled={readOnly}
                        tone="solid"
                        onClick={() => update.mutate({ id: task.id, status: s })}
                      >
                        {STATUS_LABEL[s]}
                      </OptionButton>
                    ))}
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

                  <Dt icon={Tag}>Метки</Dt>
                  <dd className="m-0 min-w-0">
                    <TaskLabels
                      bare
                      taskId={task.id}
                      projectId={projectId}
                      canEdit={!readOnly}
                    />
                  </dd>

                  <TaskCustomFields
                    variant="rows"
                    taskId={task.id}
                    projectId={projectId}
                  />
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
