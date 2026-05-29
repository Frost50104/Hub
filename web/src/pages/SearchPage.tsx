import { Search } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { SearchChips } from '@/components/search/SearchChips'
import { SearchResults } from '@/components/search/SearchResults'
import { useAdvancedSearch } from '@/hooks/useSearch'
import { type ParsedDsl } from '@/lib/search'

/**
 * Field token shapes the parser produces — see `app/services/search_dsl.py`.
 * Chip-remove maps logical `parsed` key → token regex so we can strip the
 * matching `field:value` (or `field:<value`) out of the raw query string.
 */
const TOKEN_REMOVERS: Partial<Record<keyof ParsedDsl, RegExp>> = {
  assignee: /\bassignee:\S+/i,
  status: /\bstatus:\S+/i,
  priority: /\bpriority:\S+/i,
  due_date: /\bdue:[<>=]?\S+/i,
  created_date: /\bcreated:[<>=]?\S+/i,
}

export function SearchPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const initialQ = searchParams.get('q') ?? ''
  const [query, setQuery] = useState(initialQ)
  const result = useAdvancedSearch(query)

  // Two-way sync: URL is the source of truth; input edits push to URL with
  // a tiny debounce so back/forward works. (TanStack debounces the fetch.)
  useEffect(() => {
    const handle = window.setTimeout(() => {
      const next = new URLSearchParams(searchParams)
      const trimmed = query.trim()
      if (trimmed) next.set('q', trimmed)
      else next.delete('q')
      const before = searchParams.get('q') ?? ''
      if (trimmed !== before.trim()) {
        setSearchParams(next, { replace: true })
      }
    }, 200)
    return () => window.clearTimeout(handle)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query])

  const removeChip = (key: keyof ParsedDsl) => {
    const pattern = TOKEN_REMOVERS[key]
    if (!pattern) return
    setQuery((prev) => prev.replace(pattern, '').replace(/\s{2,}/g, ' ').trim())
  }

  const empty = useMemo(
    () =>
      !result.isLoading &&
      !result.isError &&
      query.trim().length >= 2 &&
      (result.data?.total ?? 0) === 0,
    [query, result.data, result.isError, result.isLoading],
  )

  return (
    <div className="mx-auto max-w-4xl space-y-5 py-4 md:py-8">
      <header className="space-y-2">
        <h1 className="font-display text-2xl font-bold text-text">Поиск</h1>
        <p className="text-sm text-text2">
          DSL-фильтры:{' '}
          <code className="rounded bg-surface px-1.5 py-0.5 text-[12px] text-text">
            assignee:me
          </code>{' '}
          <code className="rounded bg-surface px-1.5 py-0.5 text-[12px] text-text">
            status:in_progress
          </code>{' '}
          <code className="rounded bg-surface px-1.5 py-0.5 text-[12px] text-text">
            priority:urgent
          </code>{' '}
          <code className="rounded bg-surface px-1.5 py-0.5 text-[12px] text-text">
            due:&lt;2026-06-01
          </code>{' '}
          <code className="rounded bg-surface px-1.5 py-0.5 text-[12px] text-text">
            "точная фраза"
          </code>
        </p>
      </header>

      <div className="relative">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text3" />
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder='напр. assignee:me status:in_progress "договор"'
          autoFocus
          className="w-full rounded-md border border-glass-border bg-glass px-10 py-2 text-sm text-text placeholder:text-text3 focus:border-amber focus:outline-none"
        />
      </div>

      {result.data && (
        <SearchChips parsed={result.data.parsed} onRemove={removeChip} />
      )}

      {query.trim().length < 2 ? (
        <p className="text-sm text-text3">
          Введите не меньше двух символов, чтобы начать поиск.
        </p>
      ) : (
        <SearchResults
          groups={result.data?.groups ?? []}
          total={result.data?.total ?? 0}
          loading={result.isLoading}
          empty={empty}
        />
      )}
    </div>
  )
}
