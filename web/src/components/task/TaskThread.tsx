import { ChevronDown, ChevronRight, History, Trash2 } from 'lucide-react'
import { Fragment, useState } from 'react'

import { MentionTextarea } from '@/components/task/MentionTextarea'
import { Avatar } from '@/components/ui/Avatar'
import { Button } from '@/components/ui/Button'
import { useMe } from '@/hooks/useMe'
import {
  useActivity,
  useComments,
  useCreateComment,
  useDeleteComment,
} from '@/hooks/useThreads'
import { cn } from '@/lib/cn'
import { STATUS_LABEL, type TaskStatus } from '@/lib/tasks'
import { type Activity, type Comment } from '@/lib/threads'

const MENTION_TOKEN_RE = /(@[A-Za-z0-9._-]+)/g

function renderCommentBody(body: string): React.ReactNode {
  const parts = body.split(MENTION_TOKEN_RE)
  return parts.map((part, idx) => {
    if (MENTION_TOKEN_RE.test(part)) {
      MENTION_TOKEN_RE.lastIndex = 0
      return (
        <span key={idx} className="rounded bg-amber/20 px-1 font-medium text-amber">
          {part}
        </span>
      )
    }
    return <Fragment key={idx}>{part}</Fragment>
  })
}

function renderActivity(a: Activity): string | null {
  const actor = a.actor_full_name || a.actor_email || 'Кто-то'
  const p = (a.payload ?? {}) as Record<string, unknown>
  switch (a.kind) {
    case 'created':
      return `${actor} создал задачу`
    case 'updated':
      return `${actor} обновил задачу`
    case 'status_changed': {
      const newStatus = (p['new'] as TaskStatus | undefined) ?? null
      const label = newStatus ? STATUS_LABEL[newStatus] : ''
      return `${actor} перевёл в «${label}»`
    }
    case 'assigned': {
      const isUnassign = !p['new']
      return isUnassign
        ? `${actor} снял исполнителя`
        : `${actor} назначил исполнителя`
    }
    case 'archived':
      return `${actor} архивировал`
    case 'unarchived':
      return `${actor} восстановил из архива`
    case 'watcher_added':
      return `${actor} подписался на задачу`
    case 'watcher_removed':
      return `${actor} отписался от задачи`
    case 'attached':
      return `${actor} прикрепил файл «${String(p['filename'] ?? '—')}»`
    case 'unattached':
      return `${actor} удалил файл «${String(p['filename'] ?? '—')}»`
    case 'labeled':
      return `${actor} добавил метку «${String(p['name'] ?? '—')}»`
    case 'unlabeled':
      return `${actor} снял метку «${String(p['name'] ?? '—')}»`
    case 'commented':
      // Rendered as the comment itself — skip the activity row.
      return null
    default:
      return `${actor}: ${a.kind}`
  }
}

function CommentBubble({
  comment,
  isMine,
  onDelete,
}: {
  comment: Comment
  isMine: boolean
  onDelete: () => void
}) {
  return (
    <div className="group flex gap-3">
      <Avatar
        name={comment.author_full_name}
        email={comment.author_email}
        className="h-8 w-8 shrink-0 text-[10px]"
      />
      <div className="min-w-0 flex-1 space-y-1">
        <div className="flex items-baseline gap-2">
          <span className="text-sm font-medium text-text">
            {comment.author_full_name || comment.author_email || 'Аноним'}
          </span>
          <span className="text-[10px] text-text3">
            {new Date(comment.created_at).toLocaleString('ru-RU', {
              day: 'numeric',
              month: 'short',
              hour: '2-digit',
              minute: '2-digit',
            })}
            {comment.edited_at && (
              <span className="ml-1 italic text-text3">(ред.)</span>
            )}
          </span>
          {isMine && (
            <button
              onClick={onDelete}
              className="ml-auto rounded p-0.5 text-text3 opacity-0 transition-opacity hover:text-red group-hover:opacity-100"
              aria-label="Удалить"
              title="Удалить"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
        <p className="whitespace-pre-wrap break-words text-sm text-text">
          {renderCommentBody(comment.body)}
        </p>
      </div>
    </div>
  )
}

function ActivityRow({ text, at }: { text: string; at: string }) {
  return (
    <div className="flex items-center gap-3 py-1 text-xs text-text3">
      <span className="ml-1 h-1 w-1 shrink-0 rounded-full bg-text3" />
      <span className="flex-1">{text}</span>
      <span>
        {new Date(at).toLocaleString('ru-RU', {
          day: 'numeric',
          month: 'short',
          hour: '2-digit',
          minute: '2-digit',
        })}
      </span>
    </div>
  )
}

interface TaskThreadProps {
  taskId: string
}

export function TaskThread({ taskId }: TaskThreadProps) {
  const me = useMe()
  const comments = useComments(taskId)
  const activity = useActivity(taskId)
  const create = useCreateComment(taskId)
  const del = useDeleteComment(taskId)
  const [draft, setDraft] = useState('')
  const [historyOpen, setHistoryOpen] = useState(false)

  const visibleActivity = (activity.data ?? []).filter((a) => a.kind !== 'commented')

  const submit = async (e?: React.FormEvent) => {
    e?.preventDefault()
    const trimmed = draft.trim()
    if (!trimmed) return
    try {
      await create.mutateAsync(trimmed)
      setDraft('')
    } catch {
      // черновик сохраняем в поле; тост показывает глобальный onError мутаций
    }
  }

  return (
    <div className="space-y-5">
      <section className="space-y-3">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-text3">
          Комментарии {comments.data ? `(${comments.data.length})` : ''}
        </h3>

        <div className="space-y-3">
          {comments.isError && (
            <p className="text-xs text-red">Не удалось загрузить комментарии.</p>
          )}
          {comments.data?.map((c) => (
            <CommentBubble
              key={c.id}
              comment={c}
              isMine={c.author_id === me.data?.employee_id}
              onDelete={() => {
                if (confirm('Удалить комментарий?')) {
                  del.mutate(c.id)
                }
              }}
            />
          ))}
          {comments.data && comments.data.length === 0 && (
            <p className="text-xs text-text3">Комментариев пока нет.</p>
          )}
        </div>

        <form onSubmit={submit} className="flex flex-col gap-2 pt-1">
          <MentionTextarea
            rows={3}
            value={draft}
            onValueChange={setDraft}
            placeholder="Комментарий… Наберите @ для упоминания"
            onKeyDown={(e) => {
              if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
                e.preventDefault()
                void submit()
              }
            }}
          />
          <div className="flex items-center justify-between">
            <span className="text-[10px] text-text3">
              ⌘/Ctrl + Enter — отправить · @имя — упоминание
            </span>
            <Button type="submit" size="sm" disabled={create.isPending || !draft.trim()}>
              Отправить
            </Button>
          </div>
        </form>
      </section>

      <section className="rounded-md border border-glass-border">
        <button
          type="button"
          onClick={() => setHistoryOpen((v) => !v)}
          className={cn(
            'flex w-full items-center gap-2 px-3 py-2 text-left text-xs font-medium',
            'text-text2 hover:bg-glass hover:text-text',
          )}
        >
          {historyOpen ? (
            <ChevronDown className="h-3.5 w-3.5" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5" />
          )}
          <History className="h-3.5 w-3.5" />
          История {visibleActivity.length > 0 ? `(${visibleActivity.length})` : ''}
        </button>
        {historyOpen && (
          <div className="space-y-0.5 px-3 pb-3">
            {activity.isError ? (
              <p className="text-xs text-red">Не удалось загрузить историю.</p>
            ) : visibleActivity.length === 0 ? (
              <p className="text-xs text-text3">Событий пока нет.</p>
            ) : (
              visibleActivity.map((a) => {
                const text = renderActivity(a)
                if (!text) return null
                return <ActivityRow key={a.id} text={text} at={a.created_at} />
              })
            )}
          </div>
        )}
      </section>
    </div>
  )
}
