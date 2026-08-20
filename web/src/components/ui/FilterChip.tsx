import { type ButtonHTMLAttributes } from 'react'

import { cn } from '@/lib/cn'

interface FilterChipProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  active?: boolean
  /** `lg` 44px — тап-цель на телефоне и в learn-экранах; `md` 32px — десктопный тулбар. */
  size?: 'lg' | 'md'
}

/**
 * Чип-фильтр (разделы библиотеки, типы курсов, категории ассортимента):
 * пилюля, активный — плотный амбер + `--on-amber`, неактивный — рамка
 * `--glass-border` + `--text2`. Одна высота на все экраны — раньше три
 * реализации разной высоты.
 */
export function FilterChip({ active = false, size = 'lg', className, ...props }: FilterChipProps) {
  return (
    <button
      type="button"
      aria-pressed={active}
      className={cn(
        'inline-flex shrink-0 items-center justify-center rounded-full border px-4 font-semibold transition-colors',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60',
        size === 'lg' ? 'min-h-11 text-[14px]' : 'min-h-8 text-[13px]',
        active
          ? 'border-transparent bg-amber text-on-amber'
          : 'border-glass-border text-text2 hover:text-text',
        className,
      )}
      {...props}
    />
  )
}
