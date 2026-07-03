import { cn } from '@/lib/cn'

/** Пульсирующая заглушка загрузки. Размеры задаются className. */
export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      className={cn('animate-pulse rounded-md bg-glass', className)}
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
