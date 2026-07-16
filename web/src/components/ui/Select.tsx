import { forwardRef, type SelectHTMLAttributes } from 'react'

import { cn } from '@/lib/cn'

/**
 * Нативный select в стилистике Input — прагматичный выбор для админ-форм
 * (Ф0 LMS): системный дропдаун отлично работает на мобиле, ноль зависимостей.
 */
export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(
  ({ className, children, ...props }, ref) => (
    <select
      ref={ref}
      className={cn(
        'flex h-9 w-full appearance-none rounded-lg border border-glass-border bg-glass px-3 py-1 text-sm text-text transition-colors focus-visible:outline-none focus-visible:border-amber focus-visible:ring-1 focus-visible:ring-amber disabled:cursor-not-allowed disabled:opacity-50',
        className,
      )}
      {...props}
    >
      {children}
    </select>
  ),
)
Select.displayName = 'Select'
