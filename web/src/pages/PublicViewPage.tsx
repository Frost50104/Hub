import { Calendar, Loader2, Paperclip } from 'lucide-react'
import { useEffect } from 'react'
import { useParams } from 'react-router-dom'

import { usePublicShare } from '@/hooks/usePublicShare'
import { cn } from '@/lib/cn'
import { type PublicProjectView, type PublicTaskView } from '@/lib/publicApi'

const STATUS_LABEL: Record<string, string> = {
  todo: 'К выполнению',
  in_progress: 'В работе',
  in_review: 'На проверке',
  done: 'Готово',
}

const PRIORITY_TONE: Record<string, string> = {
  low: 'text-text3',
  medium: 'text-text2',
  high: 'text-amber',
  urgent: 'text-red',
}

const PRIORITY_LABEL: Record<string, string> = {
  low: 'низкий',
  medium: 'средний',
  high: 'высокий',
  urgent: 'срочно',
}

function formatDate(iso: string | null | undefined): string | null {
  if (!iso) return null
  return new Date(iso).toLocaleDateString('ru-RU', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
}

function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString('ru-RU', {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} Б`
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} КБ`
  return `${Math.round((n / (1024 * 1024)) * 10) / 10} МБ`
}

function Initials({ value }: { value: string | null }) {
  if (!value) {
    return (
      <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-glass text-[10px] text-text3">
        ?
      </span>
    )
  }
  return (
    <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-amber/20 text-[10px] font-semibold text-amber">
      {value}
    </span>
  )
}

/**
 * Read-only public view of a task or project.  Rendered OUTSIDE the auth
 * Shell so visitors don't need an account — `publicApi` is a separate
 * axios instance with no Bearer interceptor.
 */
export function PublicViewPage() {
  const { token } = useParams<{ token: string }>()
  const result = usePublicShare(token)

  useEffect(() => {
    // CSP/Referer hygiene: per page, request the browser not to leak the
    // token to any outbound link's Referer. Backed up by nginx-side header
    // for cold loads.
    const tag = document.createElement('meta')
    tag.name = 'referrer'
    tag.content = 'no-referrer'
    document.head.appendChild(tag)
    return () => {
      document.head.removeChild(tag)
    }
  }, [])

  if (result.isLoading) {
    return (
      <PageShell>
        <div className="flex items-center gap-2 text-sm text-text2">
          <Loader2 className="h-4 w-4 animate-spin" /> Загружаем…
        </div>
      </PageShell>
    )
  }

  if (result.isError || !result.data) {
    const status = (result.error as { response?: { status?: number } } | null)?.response
      ?.status
    return (
      <PageShell>
        <div className="glass space-y-2 p-6 text-center">
          <h1 className="font-display text-lg font-semibold text-text">
            {status === 503 ? 'Публичные ссылки отключены' : 'Ссылка недействительна'}
          </h1>
          <p className="text-sm text-text2">
            {status === 503
              ? 'Администратор временно отключил публичные ссылки. Попробуйте позже.'
              : 'Ссылка отозвана, истекла или никогда не существовала. Попросите создавшего сделать новую.'}
          </p>
        </div>
      </PageShell>
    )
  }

  return (
    <PageShell>
      {result.data.kind === 'task' ? (
        <TaskView data={result.data} />
      ) : (
        <ProjectViewBlock data={result.data} />
      )}
    </PageShell>
  )
}

function PageShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen">
      <header className="border-b border-glass-border bg-bg-alt/95 px-4 py-3 backdrop-blur">
        <div className="mx-auto flex max-w-3xl items-center gap-2">
          <img
            src="/brand/signaris-horizontal-on-dark.svg"
            alt="Signaris"
            className="h-5"
          />
          <span className="font-display text-base font-black leading-none tracking-tight">
            Hub
          </span>
          <span className="ml-auto text-[11px] text-text3">view-only</span>
        </div>
      </header>
      <main className="mx-auto max-w-3xl space-y-4 px-4 py-6 md:py-10">
        {children}
      </main>
      <footer className="mx-auto max-w-3xl px-4 pb-8 pt-4 text-center text-[11px] text-text3">
        Powered by Signaris Hub
      </footer>
    </div>
  )
}

function TaskView({ data }: { data: PublicTaskView }) {
  const due = formatDate(data.due_at)
  const start = formatDate(data.start_at)
  return (
    <article className="glass space-y-4 p-5 md:p-6">
      <header className="space-y-2">
        <h1 className="font-display text-xl font-semibold text-text">
          {data.title}
        </h1>
        <div className="flex flex-wrap items-center gap-2 text-xs text-text2">
          <span className="rounded bg-surface px-1.5 py-0.5 text-text">
            {STATUS_LABEL[data.status] ?? data.status}
          </span>
          <span className={cn('uppercase tracking-wider', PRIORITY_TONE[data.priority])}>
            {PRIORITY_LABEL[data.priority] ?? data.priority}
          </span>
          {(start || due) && (
            <span className="flex items-center gap-1">
              <Calendar className="h-3 w-3" />
              {start && due ? `${start} → ${due}` : (start ?? due)}
            </span>
          )}
          <span className="ml-auto flex items-center gap-1.5">
            <span className="text-text3">от</span>
            <Initials value={data.created_by_initials} />
            {data.assignee_initials && (
              <>
                <span className="text-text3">для</span>
                <Initials value={data.assignee_initials} />
              </>
            )}
          </span>
        </div>
      </header>

      {data.description && (
        <section className="whitespace-pre-wrap text-sm text-text">
          {data.description}
        </section>
      )}

      {data.attachments.length > 0 && (
        <section className="space-y-1.5">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-text3">
            Вложения ({data.attachments.length})
          </h2>
          <ul className="space-y-1">
            {data.attachments.map((a, i) => (
              <li
                key={`${a.filename}-${i}`}
                className="flex items-center gap-2 rounded-md border border-glass-border bg-surface px-3 py-1.5 text-xs text-text2"
              >
                <Paperclip className="h-3.5 w-3.5 shrink-0 text-text3" />
                <span className="flex-1 truncate text-text">{a.filename}</span>
                <span className="shrink-0 text-text3">{formatBytes(a.size_bytes)}</span>
              </li>
            ))}
          </ul>
          <p className="text-[11px] text-text3">
            Скачивание недоступно по публичной ссылке — попросите доступ у владельца.
          </p>
        </section>
      )}

      {data.comments.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-text3">
            Комментарии ({data.comments.length})
          </h2>
          <ul className="space-y-2">
            {data.comments.map((c, i) => (
              <li
                key={`${c.created_at}-${i}`}
                className="rounded-md border border-glass-border bg-surface px-3 py-2 text-sm"
              >
                <header className="flex items-center gap-2 text-[11px] text-text3">
                  <Initials value={c.author_initials} />
                  <span>{formatDateTime(c.created_at)}</span>
                </header>
                <p className="mt-1 whitespace-pre-wrap text-text">{c.body}</p>
              </li>
            ))}
          </ul>
        </section>
      )}
    </article>
  )
}

function ProjectViewBlock({ data }: { data: PublicProjectView }) {
  return (
    <article className="space-y-5">
      <header className="glass space-y-1.5 p-5">
        <h1 className="font-display text-xl font-semibold text-text">{data.name}</h1>
        {data.description && (
          <p className="whitespace-pre-wrap text-sm text-text2">{data.description}</p>
        )}
      </header>

      {data.sections.length === 0 && (
        <p className="text-sm text-text3">Пока нет задач.</p>
      )}

      {data.sections.map((s) => (
        <section key={s.id} className="space-y-1.5">
          <h2 className="font-display text-sm font-semibold text-text">
            {s.name} <span className="text-text3">({s.tasks.length})</span>
          </h2>
          <ul className="space-y-1">
            {s.tasks.map((t) => (
              <li
                key={t.id}
                className="flex items-center justify-between gap-3 rounded-md border border-glass-border bg-surface px-3 py-2 text-sm"
              >
                <span
                  className={cn(
                    'truncate',
                    t.status === 'done' ? 'text-text3 line-through' : 'text-text',
                  )}
                >
                  {t.title}
                </span>
                <span className="flex shrink-0 items-center gap-2">
                  {t.has_attachments && (
                    <Paperclip className="h-3 w-3 text-text3" />
                  )}
                  {t.due_at && (
                    <span className="text-[10px] text-text3">
                      {formatDate(t.due_at)}
                    </span>
                  )}
                  <span
                    className={cn(
                      'text-[10px] uppercase tracking-wider',
                      PRIORITY_TONE[t.priority],
                    )}
                  >
                    {t.priority}
                  </span>
                  <Initials value={t.assignee_initials} />
                </span>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </article>
  )
}
