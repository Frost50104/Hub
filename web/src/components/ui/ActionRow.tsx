import { type ReactNode } from 'react'

import { cn } from '@/lib/cn'

/**
 * Ряд действий управляющего ПОД контентом карточки (новости, смены, опросы,
 * товары): за `border-top --hair`, с отступом 12px. Правило спеки: текстовая
 * колонка не сжимается иконками в шапке — действия живут отдельной строкой.
 */
export function ActionRow({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn('mt-3 flex flex-wrap items-center gap-2 border-t border-hair pt-3', className)}>
      {children}
    </div>
  )
}
