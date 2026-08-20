import { ChevronDown } from 'lucide-react'
import { type ReactNode } from 'react'

import { cn } from '@/lib/cn'

interface GroupHeaderProps {
  title: ReactNode
  /** «4 из 41» — моноширинный, 400, `--text2`. Число или готовая строка. */
  count?: ReactNode
  collapsed?: boolean
  onToggle?: () => void
  /** Действия справа — «…», «+». */
  actions?: ReactNode
  /** `desktop` — 32px на прозрачном; `mobile` — 44px на `--tint` с разделителем. */
  variant?: 'desktop' | 'mobile'
  /** Красный заголовок (группа «Просрочено»). Не сворачивается — см. макет. */
  tone?: 'default' | 'danger'
  /** Под курсором при перетаскивании — чип «Отпустите здесь». */
  dropActive?: boolean
  className?: string
}

/**
 * Заголовок сворачиваемой группы — один на секции списка, папки `/projects`,
 * группы «Моих задач»: шеврон + 13/700 uppercase +0.06em + моноширинный
 * счётчик + опциональное действие справа. До этого три разные вёрстки.
 */
export function GroupHeader({
  title,
  count,
  collapsed = false,
  onToggle,
  actions,
  variant = 'desktop',
  tone = 'default',
  dropActive = false,
  className,
}: GroupHeaderProps) {
  const mobile = variant === 'mobile'
  const label = (
    <>
      {onToggle && (
        <ChevronDown
          className={cn(
            'h-3.5 w-3.5 shrink-0 transition-transform',
            collapsed && '-rotate-90',
          )}
          strokeWidth={2.2}
        />
      )}
      <span className="min-w-0 truncate">{title}</span>
      {count != null && (
        <span className="ml-1 shrink-0 font-mono text-[12px] font-normal normal-case tracking-normal text-text2">
          {count}
        </span>
      )}
    </>
  )
  const labelClass = cn(
    'flex min-w-0 flex-1 items-center gap-2 text-left font-bold uppercase tracking-[0.06em]',
    mobile ? 'text-[12px]' : 'text-[13px]',
    tone === 'danger' ? 'text-red' : 'text-text2',
    onToggle && 'hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60 rounded-md',
  )
  return (
    <div
      className={cn(
        'flex items-center gap-2',
        mobile
          ? 'min-h-11 border-b border-glass-border bg-tint px-4'
          : 'min-h-8 px-1.5',
        className,
      )}
    >
      {onToggle ? (
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={!collapsed}
          className={labelClass}
        >
          {label}
        </button>
      ) : (
        <span className={labelClass}>{label}</span>
      )}
      {dropActive && (
        <span className="inline-flex h-[22px] shrink-0 items-center rounded-md bg-amber px-2 text-[11px] font-bold uppercase tracking-[0.08em] text-on-amber">
          Отпустите здесь
        </span>
      )}
      {actions && <span className="flex shrink-0 items-center gap-1">{actions}</span>}
    </div>
  )
}
