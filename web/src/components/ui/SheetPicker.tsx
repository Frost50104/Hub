import { Check, Search } from 'lucide-react'
import { useEffect, useMemo, useState, type ReactNode } from 'react'

import { ResponsiveDialog } from '@/components/ui/ResponsiveDialog'
import { cn } from '@/lib/cn'

export interface SheetPickerItem {
  id: string
  label: string
  /** Вторая строка — почта, роль, описание. */
  meta?: string
  icon?: ReactNode
  selected?: boolean
  disabled?: boolean
}

interface SheetPickerProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: ReactNode
  items: SheetPickerItem[]
  onSelect: (id: string) => void
  /** Поле поиска 44px над списком (фильтр по label/meta на клиенте). */
  searchable?: boolean
  searchPlaceholder?: string
  /** Выбор нескольких: шторка не закрывается после клика. */
  multi?: boolean
  emptyText?: string
  /** Низ списка: «Очистить всех», «Максимум 10 исполнителей». */
  footer?: ReactNode
}

/**
 * Выбор из списка на телефоне — шторка с поиском 44px и пунктами 52px с ✓;
 * на десктопе — та же модалка. Исполнители, метки, @-упоминания, окно
 * дедлайнов, папка проекта, вид доски — один пикер на всё.
 */
export function SheetPicker({
  open,
  onOpenChange,
  title,
  items,
  onSelect,
  searchable = false,
  searchPlaceholder = 'Поиск…',
  multi = false,
  emptyText = 'Ничего не найдено',
  footer,
}: SheetPickerProps) {
  const [q, setQ] = useState('')
  useEffect(() => {
    if (!open) setQ('')
  }, [open])
  const visible = useMemo(() => {
    const needle = q.trim().toLowerCase()
    if (!needle) return items
    return items.filter(
      (i) =>
        i.label.toLowerCase().includes(needle) ||
        (i.meta ?? '').toLowerCase().includes(needle),
    )
  }, [items, q])

  return (
    <ResponsiveDialog
      open={open}
      onOpenChange={onOpenChange}
      title={title}
      dismissLabel={multi ? 'Готово' : 'Отмена'}
      desktopWidth={400}
      bodyClassName="gap-2 px-2 lg:px-3"
      footer={footer}
    >
      {searchable && (
        <label className="relative block px-1">
          <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-text2" />
          <input
            type="search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={searchPlaceholder}
            className="h-11 w-full rounded-[10px] border border-glass-border bg-surface pl-10 pr-3 text-[15px] text-text placeholder:text-text2 focus:border-amber focus:outline-none"
          />
        </label>
      )}
      <ul className="flex max-h-[min(60vh,420px)] flex-col overflow-y-auto">
        {visible.length === 0 && (
          <li className="px-3 py-4 text-center text-[14px] text-text2">{emptyText}</li>
        )}
        {visible.map((item) => (
          <li key={item.id}>
            <button
              type="button"
              disabled={item.disabled}
              onClick={() => {
                onSelect(item.id)
                if (!multi) onOpenChange(false)
              }}
              className={cn(
                'flex min-h-[52px] w-full items-center gap-3 rounded-[10px] px-3 text-left transition-colors',
                'hover:bg-surface focus-visible:bg-surface focus-visible:outline-none',
                item.disabled && 'pointer-events-none opacity-50',
              )}
            >
              {item.icon && (
                <span className="flex shrink-0 items-center justify-center text-text2">
                  {item.icon}
                </span>
              )}
              <span className="flex min-w-0 flex-1 flex-col">
                <span className="truncate text-[16px] text-text">{item.label}</span>
                {item.meta && (
                  <span className="truncate text-[13px] text-text2">{item.meta}</span>
                )}
              </span>
              {item.selected && <Check className="h-[18px] w-[18px] shrink-0 text-amber" strokeWidth={2.2} />}
            </button>
          </li>
        ))}
      </ul>
    </ResponsiveDialog>
  )
}
