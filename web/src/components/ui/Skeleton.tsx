import { cn } from '@/lib/cn'

/**
 * Заглушка загрузки. Размеры задаются className.
 *
 * Без пульсации (редизайн): на слабых Android анимация дороже, чем полезна,
 * а скелетон обязан повторять ритм контента, а не привлекать внимание.
 */
export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      className={cn('rounded-md bg-surface', className)}
      aria-hidden
    />
  )
}

/** Столбик строк-заглушек — под списки задач/уведомлений. */
export function SkeletonRows({
  rows = 4,
  className,
  rowClassName,
}: {
  rows?: number
  className?: string
  rowClassName?: string
}) {
  return (
    <div className={cn('space-y-2', className)} aria-hidden>
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className={cn('h-9 w-full', rowClassName)} />
      ))}
    </div>
  )
}
