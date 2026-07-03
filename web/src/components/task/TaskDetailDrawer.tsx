import * as DialogPrimitive from '@radix-ui/react-dialog'
import { Archive, Calendar, CornerLeftUp, Flag, Link as LinkIcon, Tag, User, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { toast } from 'sonner'

import { Markdown } from '@/components/Markdown'
import { PeoplePicker } from '@/components/PeoplePicker'
import { QueryError } from '@/components/QueryError'
import { ShareDialog } from '@/components/share/ShareDialog'
import { SubtaskList } from '@/components/task/SubtaskList'
import { TaskAttachments } from '@/components/task/TaskAttachments'
import { TaskLabels } from '@/components/task/TaskLabels'
import { TaskCustomFields } from '@/components/task/TaskCustomFields'
import { TaskDependencies } from '@/components/task/TaskDependencies'
import { TaskThread } from '@/components/task/TaskThread'
import { WatchControl } from '@/components/task/WatchControl'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Input, Textarea } from '@/components/ui/Input'
import { Skeleton, SkeletonRows } from '@/components/ui/Skeleton'
import { useProject } from '@/hooks/useProjects'
import { useArchiveTask, useTask, useUpdateTask } from '@/hooks/useTasks'
import { cn } from '@/lib/cn'
import {
  PRIORITY_LABEL,
  STATUS_LABEL,
  type TaskPriority,
  type TaskStatus,
} from '@/lib/tasks'

interface TaskDetailDrawerProps {
  taskId: string | null
  projectId: string
  onClose: () => void
  /** Переключить drawer на другую задачу (родитель/подзадача). */
  onOpenTask?: (id: string) => void
}

const STATUSES: TaskStatus[] = ['todo', 'in_progress', 'in_review', 'done']
const PRIORITIES: TaskPriority[] = ['low', 'medium', 'high', 'urgent']

function ParentLink({
  parentId,
  onOpen,
}: {
  parentId: string
  onOpen: (id: string) => void
}) {
  const parent = useTask(parentId)
  return (
    <button
      type="button"
      onClick={() => onOpen(parentId)}
      className="flex max-w-full items-center gap-1 text-xs text-text2 hover:text-amber"
    >
      <CornerLeftUp className="h-3.5 w-3.5 shrink-0" />
      <span className="truncate">
        {parent.data ? `К родительской: ${parent.data.title}` : 'К родительской задаче'}
      </span>
    </button>
  )
}

export function TaskDetailDrawer({
  taskId,
  projectId,
  onClose,
  onOpenTask,
}: TaskDetailDrawerProps) {
  const taskQuery = useTask(taskId ?? undefined)
  const { data: task, isLoading } = taskQuery
  const project = useProject(projectId)
  // viewer — read-only; null (hub:admin вне членства) оставляем редактируемым,
  // права всё равно enforced на backend.
  const readOnly = project.data?.my_role === 'viewer'
  const update = useUpdateTask(projectId)
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

  const saveDueAt = async (val: string) => {
    if (!task) return
    const iso = val ? new Date(val + 'T12:00:00').toISOString() : null
    try {
      await update.mutateAsync({ id: task.id, due_at: iso })
    } catch {
      // тост показывает глобальный onError мутаций
    }
  }

  const saveStartAt = async (val: string) => {
    if (!task) return
    const iso = val ? new Date(val + 'T12:00:00').toISOString() : null
    try {
      await update.mutateAsync({ id: task.id, start_at: iso })
    } catch {
      // тост показывает глобальный onError мутаций
    }
  }

  return (
    <DialogPrimitive.Root open={!!taskId} onOpenChange={(o) => !o && onClose()}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
        <DialogPrimitive.Content
          className={cn(
            'glass fixed z-50 overflow-y-auto bg-bg-alt p-4 shadow-glass focus:outline-none',
            // Mobile: full-screen sheet, no glass rounding, slide from bottom.
            'inset-0 !rounded-none',
            'data-[state=open]:animate-in data-[state=closed]:animate-out',
            'data-[state=closed]:slide-out-to-bottom data-[state=open]:slide-in-from-bottom',
            // Desktop ≥md: anchored right-side drawer with rounding.
            'md:inset-auto md:right-3 md:top-3 md:bottom-3 md:w-full md:max-w-[480px] md:p-6 md:!rounded-[20px]',
            'md:data-[state=closed]:slide-out-to-right-2 md:data-[state=open]:slide-in-from-right-2',
          )}
        >
          <DialogPrimitive.Title className="sr-only">
            Карточка задачи
          </DialogPrimitive.Title>

          <header className="sticky top-0 z-10 -mx-4 mb-4 flex items-center justify-between border-b border-glass-border bg-bg-alt/95 px-4 py-3 backdrop-blur md:static md:mx-0 md:border-0 md:bg-transparent md:px-0 md:py-0 md:backdrop-blur-none">
            <Badge variant="secondary">Задача</Badge>
            <div className="flex items-center gap-1">
              {task && <WatchControl taskId={task.id} />}
              <DialogPrimitive.Close
                className="inline-flex h-11 w-11 items-center justify-center rounded text-text3 hover:bg-glass hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60 md:h-8 md:w-8"
                aria-label="Закрыть"
              >
                <X className="h-4 w-4" />
              </DialogPrimitive.Close>
            </div>
          </header>

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
            <div className="space-y-5">
              {task.parent_task_id && onOpenTask && (
                <ParentLink
                  parentId={task.parent_task_id}
                  onOpen={onOpenTask}
                />
              )}
              <Input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                onBlur={saveTitle}
                readOnly={readOnly}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault()
                    ;(e.target as HTMLInputElement).blur()
                  }
                }}
                className="h-auto border-transparent bg-transparent px-0 py-1 font-display text-xl font-semibold focus-visible:border-amber"
              />

              <section className="space-y-3 text-sm">
                <Row icon={<Flag className="h-4 w-4 text-text3" />} label="Статус">
                  <div className="flex flex-wrap gap-1">
                    {STATUSES.map((s) => (
                      <button
                        key={s}
                        disabled={readOnly}
                        onClick={() => update.mutate({ id: task.id, status: s })}
                        className={cn(
                          'rounded-md px-2 py-1 text-xs transition-colors',
                          task.status === s
                            ? 'bg-amber text-on-amber'
                            : 'bg-surface text-text2 hover:text-text',
                        )}
                      >
                        {STATUS_LABEL[s]}
                      </button>
                    ))}
                  </div>
                </Row>

                <Row
                  icon={<Tag className="h-4 w-4 text-text3" />}
                  label="Приоритет"
                >
                  <div className="flex flex-wrap gap-1">
                    {PRIORITIES.map((p) => (
                      <button
                        key={p}
                        disabled={readOnly}
                        onClick={() => update.mutate({ id: task.id, priority: p })}
                        className={cn(
                          'rounded-md px-2 py-1 text-xs transition-colors',
                          task.priority === p
                            ? 'bg-amber/30 text-amber'
                            : 'bg-surface text-text2 hover:text-text',
                        )}
                      >
                        {PRIORITY_LABEL[p]}
                      </button>
                    ))}
                  </div>
                </Row>

                <Row
                  icon={<User className="h-4 w-4 text-text3" />}
                  label="Исполнитель"
                >
                  <PeoplePicker
                    value={task.assignee_id}
                    onChange={(id) =>
                      update.mutate({ id: task.id, assignee_id: id })
                    }
                    disabled={readOnly || update.isPending}
                    currentLabel={
                      task.assignee
                        ? task.assignee.full_name || task.assignee.email
                        : null
                    }
                    currentEmail={task.assignee?.email ?? null}
                    placeholder="Не назначен"
                  />
                </Row>

                <Row
                  icon={<Calendar className="h-4 w-4 text-text3" />}
                  label="Старт"
                >
                  <input
                    type="date"
                    value={startAt}
                    disabled={readOnly}
                    onChange={(e) => {
                      setStartAt(e.target.value)
                      void saveStartAt(e.target.value)
                    }}
                    className="rounded-lg border border-glass-border bg-glass px-2 py-1 text-sm text-text"
                  />
                </Row>

                <Row
                  icon={<Calendar className="h-4 w-4 text-text3" />}
                  label="Срок"
                >
                  <input
                    type="date"
                    value={dueAt}
                    disabled={readOnly}
                    onChange={(e) => {
                      setDueAt(e.target.value)
                      void saveDueAt(e.target.value)
                    }}
                    className="rounded-lg border border-glass-border bg-glass px-2 py-1 text-sm text-text"
                  />
                </Row>
              </section>

              <div className="space-y-2">
                <label className="text-xs font-medium text-text2">
                  Описание
                  {!readOnly && (
                    <span className="ml-1 font-normal text-text3">
                      (markdown)
                    </span>
                  )}
                </label>
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
                      'rounded-lg border border-transparent px-1 py-0.5',
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
                    className="w-full rounded-lg border border-dashed border-glass-border px-3 py-2 text-left text-sm text-text3 hover:text-text2 disabled:cursor-default"
                  >
                    Что нужно сделать? Поддерживается markdown.
                  </button>
                )}
              </div>

              <TaskLabels
                taskId={task.id}
                projectId={projectId}
                canEdit={!readOnly}
              />

              {!task.parent_task_id && (
                <SubtaskList
                  taskId={task.id}
                  projectId={projectId}
                  canEdit={!readOnly}
                  onOpenTask={onOpenTask}
                />
              )}

              <TaskCustomFields taskId={task.id} projectId={projectId} />

              <TaskDependencies taskId={task.id} projectId={projectId} />

              <TaskAttachments taskId={task.id} />

              <TaskThread taskId={task.id} />

              <footer className="flex justify-between gap-2 pt-2">
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={readOnly}
                  onClick={async () => {
                    try {
                      await archive.mutateAsync({
                        id: task.id,
                        archive: !task.archived_at,
                      })
                      const wasArchived = !!task.archived_at
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
                  <Archive className="h-4 w-4" />
                  {task.archived_at ? 'Восстановить' : 'В архив'}
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => setShareOpen(true)}
                >
                  <LinkIcon className="h-4 w-4" />
                  Поделиться
                </Button>
              </footer>
            </div>
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

function Row({
  icon,
  label,
  children,
}: {
  icon: React.ReactNode
  label: string
  children: React.ReactNode
}) {
  return (
    <div className="grid grid-cols-[100px_1fr] items-center gap-3">
      <div className="flex items-center gap-2 text-xs font-medium text-text2">
        {icon}
        {label}
      </div>
      <div>{children}</div>
    </div>
  )
}
