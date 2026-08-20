import { type ReactNode } from 'react'

import { cn } from '@/lib/cn'

/**
 * Правый рельс десктопа — липкий `<aside>` 220px со сводкой: ярлык 11/700
 * uppercase +0.12em и строки `<dl>` (подпись/значение) с разделителем `--hair`.
 * Каталог, курс, библиотека — один рельс; на телефоне рельса нет, его
 * содержимое уезжает в строки под шапкой.
 */
export function RightRail({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <aside
      className={cn(
        'hidden w-[220px] shrink-0 flex-col gap-6 self-start lg:sticky lg:top-6 lg:flex',
        className,
      )}
    >
      {children}
    </aside>
  )
}

export function RailSection({
  label,
  children,
  className,
}: {
  label: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section className={cn('flex flex-col gap-1', className)}>
      <h3 className="font-body text-[11px] font-bold uppercase tracking-[0.12em] text-text2">
        {label}
      </h3>
      <dl className="flex flex-col">{children}</dl>
    </section>
  )
}

export function RailRow({
  term,
  children,
  tone = 'default',
}: {
  term: ReactNode
  children: ReactNode
  /** Цвет значения: просрочка — красный, пройдено — зелёный. */
  tone?: 'default' | 'danger' | 'success'
}) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-hair py-[11px] last:border-b-0">
      <dt className="text-[13px] text-text2">{term}</dt>
      <dd
        className={cn(
          'min-w-0 text-right text-[15px] font-semibold tabular-nums',
          tone === 'danger' ? 'text-red' : tone === 'success' ? 'text-green' : 'text-text',
        )}
      >
        {children}
      </dd>
    </div>
  )
}
