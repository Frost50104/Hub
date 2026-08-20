import { type ReactNode } from 'react'

import { cn } from '@/lib/cn'

export interface SegmentOption<T extends string> {
  value: T
  label: ReactNode
  disabled?: boolean
}

interface SegmentGroupProps<T extends string> {
  options: SegmentOption<T>[]
  value: T
  onChange: (value: T) => void
  /** Обязателен: две группы рядом («Период», «Охват») должны читаться как две. */
  ariaLabel: string
  /** `lg` 44px — мобильный и learn-экраны; `md` 34px — десктопные тулбары; `sm` 30px — сайдбар. */
  size?: 'lg' | 'md' | 'sm'
  /** Растянуть на всю ширину с равными долями (мобильный). */
  fullWidth?: boolean
  className?: string
}

/**
 * Сегмент-контрол: контейнер с рамкой и padding 2, внутри сегменты без
 * собственной рамки; активный — `--surface` + `--text`, неактивный —
 * прозрачный + `--text2`. Амбер здесь НЕ используется: переключение среза —
 * навигация, а не действие, и амбер остаётся кнопкам.
 * Идемпотентно: повторный клик по активному сегменту ничего не делает.
 */
export function SegmentGroup<T extends string>({
  options,
  value,
  onChange,
  ariaLabel,
  size = 'lg',
  fullWidth = false,
  className,
}: SegmentGroupProps<T>) {
  const h = size === 'lg' ? 'min-h-11 text-[14px]' : size === 'md' ? 'min-h-[34px] text-[13px]' : 'min-h-[30px] text-[12px]'
  return (
    <div
      role="group"
      aria-label={ariaLabel}
      className={cn(
        'inline-flex rounded-[10px] border border-glass-border p-0.5',
        fullWidth && 'flex w-full',
        className,
      )}
    >
      {options.map((o) => {
        const active = o.value === value
        return (
          <button
            key={o.value}
            type="button"
            aria-pressed={active}
            disabled={o.disabled}
            onClick={() => {
              if (!active) onChange(o.value)
            }}
            className={cn(
              'inline-flex items-center justify-center rounded-lg px-3.5 font-semibold transition-colors',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60',
              'disabled:opacity-50',
              h,
              fullWidth && 'flex-1',
              active ? 'bg-surface text-text' : 'text-text2 hover:text-text',
            )}
          >
            {o.label}
          </button>
        )
      })}
    </div>
  )
}
