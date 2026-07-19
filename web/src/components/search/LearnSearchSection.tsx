import { useQuery } from '@tanstack/react-query'
import { GraduationCap } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { learnApi } from '@/lib/learn'

/**
 * Секция «Обучение» в общем поиске (Ф5): FTS по единому индексу
 * learn-домена (библиотека, курсы, новости, опросы, ассортимент).
 * DSL-операторы таск-поиска не передаются — ищем по чистому тексту.
 */
export function LearnSearchSection({ query }: { query: string }) {
  const [debounced, setDebounced] = useState(query)
  useEffect(() => {
    const handle = window.setTimeout(() => setDebounced(query), 300)
    return () => window.clearTimeout(handle)
  }, [query])

  // Чистим DSL-токены (assignee:me и т.п.) — learn-поиску нужен текст.
  const clean = debounced
    .replace(/\b\w+:[<>=]?\S+/g, '')
    .replace(/\s{2,}/g, ' ')
    .trim()

  const result = useQuery({
    queryKey: ['learn-search', clean],
    queryFn: () => learnApi.learnSearch(clean),
    enabled: clean.length >= 2,
    staleTime: 15_000,
    placeholderData: (prev) => prev,
    retry: false,
    meta: { suppressGlobalError: true },
  })

  if (clean.length < 2 || !result.data || result.data.total === 0) return null

  return (
    <div className="mt-4">
      <h2 className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-text3">
        <GraduationCap className="h-3.5 w-3.5" /> Обучение
      </h2>
      <ul className="divide-y divide-glass-border overflow-hidden rounded-xl border border-glass-border bg-glass">
        {result.data.hits.map((hit) => (
          <li key={`${hit.object_type}-${hit.object_id}`}>
            <Link
              to={hit.url_path}
              className="flex items-center gap-3 px-4 py-2.5 hover:bg-surface/50"
            >
              <span className="shrink-0 rounded bg-surface px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-text3">
                {hit.type_label}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm text-text">{hit.title}</span>
                {hit.snippet && (
                  <span className="block truncate text-xs text-text3">{hit.snippet}</span>
                )}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  )
}
