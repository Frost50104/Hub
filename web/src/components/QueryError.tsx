import { RotateCcw } from 'lucide-react'

import { Button } from '@/components/ui/Button'
import { extractErrorDetail } from '@/lib/errors'
import { cn } from '@/lib/cn'

interface QueryErrorProps {
  /** Ошибка запроса — из неё достаётся detail для подписи. */
  error?: unknown
  /** Обычно `() => query.refetch()`. Без него кнопка не рендерится. */
  onRetry?: () => void
  title?: string
  className?: string
}

/** Блок ошибки загрузки вместо контента — чтобы ошибка не маскировалась под пустое состояние. */
export function QueryError({
  error,
  onRetry,
  title = 'Не удалось загрузить',
  className,
}: QueryErrorProps) {
  return (
    <div
      role="alert"
      className={cn(
        'flex flex-col items-start gap-2 rounded-lg border border-red/30 bg-red/5 p-4',
        className,
      )}
    >
      <p className="text-sm font-medium text-text">{title}</p>
      {error !== undefined && (
        <p className="text-xs text-text2">{extractErrorDetail(error)}</p>
      )}
      {onRetry && (
        <Button variant="secondary" size="sm" onClick={onRetry}>
          <RotateCcw className="h-3.5 w-3.5" />
          Повторить
        </Button>
      )}
    </div>
  )
}
