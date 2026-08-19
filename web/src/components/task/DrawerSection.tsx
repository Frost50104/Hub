import { cn } from '@/lib/cn'

/**
 * Заголовок секции карточки задачи: 12/700 uppercase +0.09em на `--text2`,
 * счётчик рядом — моноширинный. Один компонент на все секции, иначе они
 * разъезжаются по кеглю и отбивке, как это было до редизайна.
 */
export function DrawerSection({
  title,
  count,
  action,
  children,
  className,
}: {
  title: string
  /** Счётчик рядом с заголовком: «2» или «1/3». */
  count?: string | number | null
  /** Контрол справа от заголовка. */
  action?: React.ReactNode
  children: React.ReactNode
  className?: string
}) {
  return (
    <section className={cn('flex flex-col gap-2.5', className)}>
      <h3 className="m-0 flex items-center gap-2 text-[12px] font-bold uppercase tracking-[0.09em] text-text2">
        {title}
        {count != null && count !== '' && (
          <span className="font-mono text-[13px] font-normal normal-case tracking-normal text-text2">
            {count}
          </span>
        )}
        {action && <span className="ml-auto normal-case tracking-normal">{action}</span>}
      </h3>
      {children}
    </section>
  )
}
