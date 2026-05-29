import { Link } from 'react-router-dom'

import { Badge } from '@/components/ui/Badge'
import { cn } from '@/lib/cn'
import { type SearchGroup, type SearchTaskHit } from '@/lib/search'

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

interface SearchResultsProps {
  groups: SearchGroup[]
  total: number
  loading?: boolean
  empty?: boolean
}

export function SearchResults({
  groups,
  total,
  loading,
  empty,
}: SearchResultsProps) {
  if (loading) {
    return <p className="px-1 text-sm text-text3">Ищем…</p>
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
        Найдено задач: {total} в {groups.length}{' '}
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
            <span className="text-xs text-text3">{g.tasks.length}</span>
          </header>
          <ul className="space-y-0.5">
            {g.tasks.map((t) => (
              <li key={t.id}>
                <Link
                  to={`/projects/${g.project_id}?task=${t.id}`}
                  className="flex items-center justify-between gap-3 rounded-md border border-glass-border bg-surface px-3 py-2 text-sm hover:bg-glass focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
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
                      {t.priority}
                    </span>
                    <span className="rounded bg-glass px-1.5 py-0.5 text-[10px] text-text2">
                      {STATUS_LABEL[t.status]}
                    </span>
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  )
}
