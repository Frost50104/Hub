import { CircleAlert } from 'lucide-react'
import { type ReactNode } from 'react'

import { Button } from '@/components/ui/Button'
import { cn } from '@/lib/cn'

interface ErrorBannerProps {
  title: string
  text?: ReactNode
  actionLabel?: string
  onAction?: () => void
  className?: string
}

/**
 * Баннер ошибки внутри экрана: иконка + заголовок 15/600 + пояснение 14 +
 * «Повторить». Для частичных отказов — когда папки не загрузились, а проекты
 * есть; когда агрегаты не посчитались, а список жив. Красный — только иконка.
 */
export function ErrorBanner({ title, text, actionLabel, onAction, className }: ErrorBannerProps) {
  return (
    <div
      role="alert"
      className={cn(
        'flex flex-wrap items-start gap-3 rounded-xl border border-glass-border bg-tint px-4 py-3.5',
        className,
      )}
    >
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-red/[0.16] text-red">
        <CircleAlert className="h-[18px] w-[18px]" strokeWidth={2} />
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-[15px] font-semibold leading-[1.35] text-text">{title}</p>
        {text && <p className="mt-0.5 text-[14px] leading-[1.45] text-text2">{text}</p>}
      </div>
      {actionLabel && onAction && (
        <Button variant="secondary" size="sm" onClick={onAction} className="shrink-0">
          {actionLabel}
        </Button>
      )}
    </div>
  )
}
