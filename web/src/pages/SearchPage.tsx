import { CheckSquare, ChevronRight, Folder, RotateCcw, Search, UserCircle, Users } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { MobilePageHeader } from '@/components/layout/MobilePageHeader'
import { SearchChips } from '@/components/search/SearchChips'
import { SearchResults } from '@/components/search/SearchResults'
import { useAdvancedSearch } from '@/hooks/useSearch'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { useMe } from '@/hooks/useMe'
import { cn } from '@/lib/cn'
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

const PILL_FILTERS = [
  { key: 'tasks', label: 'Задачи', icon: CheckSquare },
  { key: 'projects', label: 'Проекты', icon: Folder },
  { key: 'people', label: 'Люди', icon: Users },
] as const

const QUICK_FILTERS = [
  { id: 'me', label: 'Назначенные мне', dsl: 'assignee:me' },
  { id: 'in_progress', label: 'В работе', dsl: 'status:in_progress' },
  { id: 'urgent', label: 'Срочные', dsl: 'priority:urgent' },
]

const SHORTCUTS = [
  { id: 'recent_mine', label: 'Назначенные мне', dsl: 'assignee:me' },
  {
    id: 'completed',
    label: 'Недавно завершённые',
    dsl: 'status:done',
  },
]

export function SearchPage() {
  const isDesktop = useIsDesktop()
  return isDesktop ? <DesktopSearch /> : <MobileSearch />
}

// ─── Mobile ─────────────────────────────────────────────────────────────────

function MobileSearch() {
  const [searchParams, setSearchParams] = useSearchParams()
  const initialQ = searchParams.get('q') ?? ''
  const [query, setQuery] = useState(initialQ)
  const me = useMe()
  const result = useAdvancedSearch(query)

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

  const empty = useMemo(
    () =>
      !result.isLoading &&
      !result.isError &&
      query.trim().length >= 2 &&
      (result.data?.total ?? 0) === 0,
    [query, result.data, result.isError, result.isLoading],
  )

  const isIdle = query.trim().length < 2
  const tenantSlug = me.data?.tenant_slug ?? ''

  return (
    <>
      <MobilePageHeader title="Поиск" />

      <div className="space-y-4 px-4">
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text3" />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={`Поиск в ${tenantSlug.toUpperCase() || 'Hub'}`}
            className="w-full rounded-xl border border-glass-border bg-surface px-10 py-2.5 text-sm text-text placeholder:text-text3 focus:border-amber focus:outline-none"
          />
        </div>

        <div className="-mx-4 overflow-x-auto px-4">
          <ul className="flex gap-2">
            {PILL_FILTERS.map((p) => (
              <li key={p.key}>
                <button
                  type="button"
                  className="shrink-0 rounded-full border border-glass-border bg-glass px-3.5 py-1.5 text-sm text-text active:bg-surface"
                >
                  {p.label}
                </button>
              </li>
            ))}
          </ul>
        </div>

        {isIdle ? (
          <div className="space-y-5">
            <section className="space-y-1">
              <h2 className="text-[15px] font-semibold text-text">Быстрые фильтры</h2>
              <ul className="overflow-hidden rounded-2xl border border-glass-border bg-bg-alt/60">
                {QUICK_FILTERS.map((f, i) => (
                  <li
                    key={f.id}
                    className={cn(
                      i > 0 && 'border-t border-glass-border/60',
                    )}
                  >
                    <button
                      type="button"
                      onClick={() => setQuery(f.dsl)}
                      className="flex w-full items-center gap-3 px-4 py-3 text-left active:bg-glass"
                    >
                      <UserCircle className="h-5 w-5 text-text3" />
                      <span className="flex-1 text-sm text-text">{f.label}</span>
                      <ChevronRight className="h-4 w-4 text-text3" />
                    </button>
                  </li>
                ))}
              </ul>
            </section>

            <section className="space-y-1">
              <h2 className="text-[15px] font-semibold text-text">Ярлыки</h2>
              <ul className="overflow-hidden rounded-2xl border border-glass-border bg-bg-alt/60">
                {SHORTCUTS.map((s, i) => (
                  <li
                    key={s.id}
                    className={cn(
                      i > 0 && 'border-t border-glass-border/60',
                    )}
                  >
                    <button
                      type="button"
                      onClick={() => setQuery(s.dsl)}
                      className="flex w-full items-center gap-3 px-4 py-3 text-left active:bg-glass"
                    >
                      <RotateCcw className="h-5 w-5 text-text3" />
                      <span className="flex-1 text-sm text-text">{s.label}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          </div>
        ) : (
          <div className="space-y-3">
            {result.data && (
              <SearchChips
                parsed={result.data.parsed}
                onRemove={(key) => {
                  const pattern = TOKEN_REMOVERS[key]
                  if (!pattern) return
                  setQuery((prev) =>
                    prev.replace(pattern, '').replace(/\s{2,}/g, ' ').trim(),
                  )
                }}
              />
            )}
            <SearchResults
              groups={result.data?.groups ?? []}
              total={result.data?.total ?? 0}
              loading={result.isLoading}
              empty={empty}
            />
          </div>
        )}
      </div>
    </>
  )
}

// ─── Desktop ────────────────────────────────────────────────────────────────

function DesktopSearch() {
  const [searchParams, setSearchParams] = useSearchParams()
  const initialQ = searchParams.get('q') ?? ''
  const [query, setQuery] = useState(initialQ)
  const result = useAdvancedSearch(query)

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
        <SearchChips
          parsed={result.data.parsed}
          onRemove={(key) => {
            const pattern = TOKEN_REMOVERS[key]
            if (!pattern) return
            setQuery((prev) =>
              prev.replace(pattern, '').replace(/\s{2,}/g, ' ').trim(),
            )
          }}
        />
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

