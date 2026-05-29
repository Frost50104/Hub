import * as DialogPrimitive from '@radix-ui/react-dialog'
import { Archive, Calendar, Flag, Link as LinkIcon, Tag, User, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { toast } from 'sonner'

import { ShareDialog } from '@/components/share/ShareDialog'
import { TaskAttachments } from '@/components/task/TaskAttachments'
import { TaskCustomFields } from '@/components/task/TaskCustomFields'
import { TaskThread } from '@/components/task/TaskThread'
import { WatchControl } from '@/components/task/WatchControl'
import { Avatar } from '@/components/ui/Avatar'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Input, Textarea } from '@/components/ui/Input'
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
}

const STATUSES: TaskStatus[] = ['todo', 'in_progress', 'in_review', 'done']
const PRIORITIES: TaskPriority[] = ['low', 'medium', 'high', 'urgent']

export function TaskDetailDrawer({ taskId, projectId, onClose }: TaskDetailDrawerProps) {
  const { data: task, isLoading } = useTask(taskId ?? undefined)
  const update = useUpdateTask(projectId)
  const archive = useArchiveTask(projectId)
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [dueAt, setDueAt] = useState('')
  const [startAt, setStartAt] = useState('')
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
    } catch (err) {
      toast.error('Не удалось обновить', { description: (err as Error).message })
    }
  }

  const saveDescription = async () => {
    if (!task || description === (task.description ?? '')) return
    try {
      await update.mutateAsync({ id: task.id, description })
    } catch (err) {
      toast.error('Не удалось обновить', { description: (err as Error).message })
    }
  }

  const saveDueAt = async (val: string) => {
    if (!task) return
    const iso = val ? new Date(val + 'T12:00:00').toISOString() : null
    try {
      await update.mutateAsync({ id: task.id, due_at: iso })
    } catch (err) {
      toast.error('Не удалось обновить', { description: (err as Error).message })
    }
  }

  const saveStartAt = async (val: string) => {
    if (!task) return
    const iso = val ? new Date(val + 'T12:00:00').toISOString() : null
    try {
      await update.mutateAsync({ id: task.id, start_at: iso })
    } catch (err) {
      toast.error('Не удалось обновить', { description: (err as Error).message })
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

          {isLoading && <p className="text-text2">Загружаем…</p>}

          {task && (
            <div className="space-y-5">
              <Input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                onBlur={saveTitle}
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
                        onClick={() => update.mutate({ id: task.id, status: s })}
                        className={cn(
                          'rounded-md px-2 py-1 text-xs transition-colors',
                          task.status === s
                            ? 'bg-amber text-bg'
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
                  {task.assignee ? (
                    <div className="flex items-center gap-2">
                      <Avatar
                        name={task.assignee.full_name}
                        email={task.assignee.email}
                        className="h-6 w-6 text-[10px]"
                      />
                      <span className="text-sm text-text">
                        {task.assignee.full_name || task.assignee.email}
                      </span>
                    </div>
                  ) : (
                    <span className="text-sm text-text3">Не назначен</span>
                  )}
                </Row>

                <Row
                  icon={<Calendar className="h-4 w-4 text-text3" />}
                  label="Старт"
                >
                  <input
                    type="date"
                    value={startAt}
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
                    onChange={(e) => {
                      setDueAt(e.target.value)
                      void saveDueAt(e.target.value)
                    }}
                    className="rounded-lg border border-glass-border bg-glass px-2 py-1 text-sm text-text"
                  />
                </Row>
              </section>

              <div className="space-y-2">
                <label className="text-xs font-medium text-text2">Описание</label>
                <Textarea
                  rows={6}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  onBlur={saveDescription}
                  placeholder="Что нужно сделать?"
                />
              </div>

              <TaskCustomFields taskId={task.id} projectId={projectId} />

              <TaskAttachments taskId={task.id} />

              <TaskThread taskId={task.id} />

              <footer className="flex justify-between gap-2 pt-2">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={async () => {
                    try {
                      await archive.mutateAsync({
                        id: task.id,
                        archive: !task.archived_at,
                      })
                      toast.success(
                        task.archived_at ? 'Задача восстановлена' : 'Задача в архиве',
                      )
                      onClose()
                    } catch (err) {
                      toast.error('Не получилось', {
                        description: (err as Error).message,
                      })
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
