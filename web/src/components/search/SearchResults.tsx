import { MessageSquare } from 'lucide-react'
import { Link } from 'react-router-dom'

import { QueryError } from '@/components/QueryError'
import { Badge } from '@/components/ui/Badge'
import { cn } from '@/lib/cn'
import { type SearchGroup, type SearchTaskHit } from '@/lib/search'

import { HighlightedSnippet } from './HighlightedSnippet'

const STATUS_LABEL: Record<SearchTaskHit['status'], string> = {
  todo: 'К выполнению',
  in_progress: 'В работе',
  in_review: 'На проверке',
  done: 'Готово',
}

const PRIORITY_TONE: Record<SearchTaskHit['priority'], string> = {
  low: 'text-text3',
  medium: 'text-text2',
  high: 'text-amber',
  urgent: 'text-red',
}

const PRIORITY_LABEL: Record<SearchTaskHit['priority'], string> = {
  low: 'низкий',
  medium: 'средний',
  high: 'высокий',
  urgent: 'срочно',
}

interface SearchResultsProps {
  groups: SearchGroup[]
  total: number
  loading?: boolean
  empty?: boolean
  /** Ошибка запроса поиска — при наличии рендерится вместо результатов. */
  error?: unknown
  onRetry?: () => void
}

export function SearchResults({
  groups,
  total,
  loading,
  empty,
  error,
  onRetry,
}: SearchResultsProps) {
  if (loading) {
    return <p className="px-1 text-sm text-text3">Ищем…</p>
  }
  if (error !== undefined) {
    return (
      <QueryError error={error} onRetry={onRetry} title="Поиск не удался" />
    )
  }
  if (empty) {
    return (
      <p className="px-1 text-sm text-text3">
        Ничего не нашлось. Попробуйте сократить запрос или убрать фильтры.
      </p>
    )
  }
  return (
    <div className="space-y-5">
      <p className="text-xs text-text3">
        Найдено: {total} результатов в {groups.length}{' '}
        {groups.length === 1 ? 'проекте' : 'проектах'}.
      </p>
      {groups.map((g) => (
        <section key={g.project_id} className="space-y-1.5">
          <header className="flex items-center gap-2">
            <Link
              to={`/projects/${g.project_id}`}
              className="font-display text-sm font-semibold text-text hover:text-amber"
            >
              {g.project_name}
            </Link>
            <Badge variant="outline">{g.project_key}</Badge>
            <span className="text-xs text-text3">
              {g.tasks.length}
              {g.comments.length > 0 && ` + ${g.comments.length} комм.`}
            </span>
          </header>

          {g.tasks.length > 0 && (
            <ul className="space-y-0.5">
              {g.tasks.map((t) => (
                <li key={t.id}>
                  <Link
                    to={`/projects/${g.project_id}?task=${t.id}`}
                    className="flex flex-col gap-1 rounded-md border border-glass-border bg-surface px-3 py-2 text-sm hover:bg-glass focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <span
                        className={cn(
                          'truncate',
                          t.status === 'done'
                            ? 'text-text3 line-through'
                            : 'text-text',
                        )}
                      >
                        {t.title}
                      </span>
                      <span className="flex shrink-0 items-center gap-2">
                        {t.due_at && (
                          <span className="text-[10px] text-text3">
                            {new Date(t.due_at).toLocaleDateString('ru-RU', {
                              day: 'numeric',
                              month: 'short',
                            })}
                          </span>
                        )}
                        <span
                          className={cn(
                            'text-[10px] uppercase tracking-wider',
                            PRIORITY_TONE[t.priority],
                          )}
                        >
                          {PRIORITY_LABEL[t.priority]}
                        </span>
                        <span className="rounded bg-glass px-1.5 py-0.5 text-[10px] text-text2">
                          {STATUS_LABEL[t.status]}
                        </span>
                      </span>
                    </div>
                    {t.headline && (
                      <HighlightedSnippet
                        text={t.headline}
                        className="line-clamp-2 text-xs text-text3"
                      />
                    )}
                  </Link>
                </li>
              ))}
            </ul>
          )}

          {g.comments.length > 0 && (
            <div className="space-y-1 pt-1">
              <p className="px-1 text-[10px] font-semibold uppercase tracking-wider text-text3">
                Комментарии
              </p>
              <ul className="space-y-0.5">
                {g.comments.map((c, i) => (
                  <li key={`${c.task_id}-${i}`}>
                    <Link
                      to={`/projects/${g.project_id}?task=${c.task_id}`}
                      className="flex items-start gap-2 rounded-md border border-glass-border bg-surface px-3 py-2 text-xs hover:bg-glass focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
                    >
                      <MessageSquare className="mt-0.5 h-3 w-3 shrink-0 text-text3" />
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-text">{c.task_title}</p>
                        <HighlightedSnippet
                          text={c.snippet}
                          className="line-clamp-2 text-text3"
                        />
                      </div>
                      {c.author_initials && (
                        <span className="shrink-0 text-[10px] text-text3">
                          {c.author_initials}
                        </span>
                      )}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>
      ))}
    </div>
  )
}
