import { ChevronDown } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

import { BottomSheet, BottomSheetItem } from '@/components/ui/BottomSheet'
import { cn } from '@/lib/cn'

export interface ViewOption<T extends string> {
  key: T
  label: string
  icon?: ReactNode
}

interface MobileViewControlBarProps<T extends string> {
  options: ViewOption<T>[]
  value: T
  onChange: (next: T) => void
  /** Отступ снизу в rem поверх safe-area: 4.5 = таб-бар 56px + 16px. */
  bottomOffset?: number
  className?: string
}

/**
 * Плавающая пилюля выбора представления по центру над таб-баром («Список ▾»).
 * Стоит на ВСЕХ представлениях проекта: заперев её внутри списка и доски,
 * из календаря, Ганта и дашборда нельзя было вернуться.
 *
 * Портал в `body`: `.glass` с `backdrop-filter` создаёт containing block для
 * `position:fixed`, и внутри любой стеклянной панели пилюля встала бы не там.
 * Подложка непрозрачная (`--bg-alt` 95%) — в светлой теме стекло просвечивало.
 */
export function MobileViewControlBar<T extends string>({
  options,
  value,
  onChange,
  bottomOffset = 4.5,
  className,
}: MobileViewControlBarProps<T>) {
  const [open, setOpen] = useState(false)
  const current = options.find((o) => o.key === value) ?? options[0]
  if (!current) return null
  if (typeof document === 'undefined') return null

  return createPortal(
    <>
      <div
        className={cn('pointer-events-none fixed inset-x-0 z-30 flex justify-center lg:hidden', className)}
        style={{ bottom: `calc(env(safe-area-inset-bottom, 0) + ${bottomOffset}rem)` }}
      >
        <button
          type="button"
          onClick={() => setOpen(true)}
          aria-haspopup="dialog"
          aria-expanded={open}
          className="pointer-events-auto inline-flex min-h-11 items-center gap-1.5 rounded-full border border-glass-border px-[18px] text-[15px] font-medium text-text shadow-[0_8px_24px_rgba(0,0,0,0.35)] backdrop-blur-[8px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60"
          style={{ background: 'color-mix(in srgb, rgb(var(--bg-alt)) 95%, transparent)' }}
        >
          {current.label}
          <ChevronDown className="h-4 w-4 text-text2" />
        </button>
      </div>
      <BottomSheet open={open} onOpenChange={setOpen} title="Выберите вид">
        {options.map((o) => (
          <BottomSheetItem
            key={o.key}
            icon={o.icon}
            onClick={() => {
              onChange(o.key)
              setOpen(false)
            }}
            trailing={o.key === value ? '✓' : null}
          >
            {o.label}
          </BottomSheetItem>
        ))}
      </BottomSheet>
    </>,
    document.body,
  )
}
