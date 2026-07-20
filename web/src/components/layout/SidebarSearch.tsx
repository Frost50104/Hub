import { Search } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { useSearch } from '@/hooks/useSearch'
import { cn } from '@/lib/cn'

export function SidebarSearch() {
  const [q, setQ] = useState('')
  const [focused, setFocused] = useState(false)
  const { data, isLoading } = useSearch(q)
  const nav = useNavigate()
  const inputRef = useRef<HTMLInputElement>(null)

  // Global Cmd+K / Ctrl+K → focus search input.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        inputRef.current?.focus()
        inputRef.current?.select()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const show = focused && q.trim().length >= 2

  const goto = (path: string) => {
    setQ('')
    setFocused(false)
    nav(path)
  }

  const openAdvanced = () => {
    const trimmed = q.trim()
    setQ('')
    setFocused(false)
    nav(trimmed ? `/search?q=${encodeURIComponent(trimmed)}` : '/search')
  }

  return (
    <div className="relative">
      <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text3" />
      <input
        ref={inputRef}
        type="search"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onFocus={() => setFocused(true)}
        onBlur={() => window.setTimeout(() => setFocused(false), 150)}
        onKeyDown={(e) => {
          if (e.key === 'Escape') {
            ;(e.target as HTMLInputElement).blur()
            setQ('')
          }
        }}
        placeholder="Поиск…  ⌘K"
        className="w-full rounded-md border border-glass-border bg-glass px-7 py-1.5 text-sm text-text placeholder:text-text3 focus:border-amber focus:outline-none"
      />
      {show && (
        <div
          className={cn(
            // bg-bg (непрозрачный): glass-фон просвечивал нав-пункты под дропдауном
            'absolute left-0 right-0 top-full z-30 mt-1 max-h-96 overflow-y-auto rounded-lg border border-glass-border bg-bg p-1 shadow-glass',
          )}
        >
          {isLoading && (
            <p className="px-2 py-2 text-xs text-text3">Ищем…</p>
          )}
          {data && data.projects.length === 0 && data.tasks.length === 0 && (
            <p className="px-2 py-2 text-xs text-text3">Ничего не найдено</p>
          )}
          {data && data.projects.length > 0 && (
            <div className="mb-1">
              <p className="px-2 pb-0.5 pt-1 text-[10px] font-semibold uppercase tracking-wider text-text3">
                Проекты
              </p>
              {data.projects.map((p) => (
                <button
                  key={p.id}
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => goto(`/projects/${p.id}`)}
                  className="flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left text-sm text-text hover:bg-surface"
                >
                  <span className="truncate">{p.title}</span>
                  {p.subtitle && (
                    <span className="ml-2 shrink-0 text-xs text-text3">
                      {p.subtitle}
                    </span>
                  )}
                </button>
              ))}
            </div>
          )}
          {data && data.tasks.length > 0 && (
            <div>
              <p className="px-2 pb-0.5 pt-1 text-[10px] font-semibold uppercase tracking-wider text-text3">
                Задачи
              </p>
              {data.tasks.map((t) => (
                <button
                  key={t.id}
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() =>
                    goto(`/projects/${t.project_id}?task=${t.id}`)
                  }
                  className="flex w-full flex-col rounded-md px-2 py-1.5 text-left hover:bg-surface"
                >
                  <span className="truncate text-sm text-text">{t.title}</span>
                  {t.subtitle && (
                    <span className="truncate text-xs text-text3">
                      {t.subtitle}
                    </span>
                  )}
                </button>
              ))}
            </div>
          )}
          <div className="mt-1 border-t border-glass-border pt-1">
            <button
              onMouseDown={(e) => e.preventDefault()}
              onClick={openAdvanced}
              className="flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-left text-xs text-text2 hover:bg-surface hover:text-text"
            >
              <Search className="h-3 w-3" />
              Расширенный поиск с фильтрами
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
