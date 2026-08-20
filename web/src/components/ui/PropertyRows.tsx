import { type ReactNode } from 'react'

import { cn } from '@/lib/cn'

/**
 * Мобильный блок свойств: контейнер `tint/r14`, строки 48px
 * «подпись слева / прозрачный контрол справа», разделитель `--hair`.
 * Ряды чипов на телефоне превращались в стену из разнородных блоков —
 * этот контейнер заменяет их одним компактным списком.
 */
export function PropertyRows({
  children,
  className,
}: {
  children: ReactNode
  className?: string
}) {
  return (
    <div
      className={cn(
        'flex flex-col overflow-hidden rounded-[14px] border border-glass-border bg-tint',
        className,
      )}
    >
      {children}
    </div>
  )
}

interface PropertyRowProps {
  label: ReactNode
  /** Контрол или значение справа — выравнивание по правому краю. */
  children: ReactNode
  /** Строка целиком — кнопка (открыть пикер). */
  onClick?: () => void
  className?: string
}

export function PropertyRow({ label, children, onClick, className }: PropertyRowProps) {
  const inner = (
    <>
      <span className="shrink-0 text-[15px] text-text2">{label}</span>
      <span className="flex min-h-[46px] min-w-0 flex-1 items-center justify-end text-right text-[16px] text-text">
        {children}
      </span>
    </>
  )
  const base = cn(
    'flex min-h-12 w-full items-center gap-3 border-t border-hair pl-3.5 pr-1 first:border-t-0',
    className,
  )
  if (onClick) {
    return (
      <button
        type="button"
        onClick={onClick}
        className={cn(base, 'text-left hover:bg-glass focus-visible:outline-none focus-visible:bg-glass')}
      >
        {inner}
      </button>
    )
  }
  return <div className={base}>{inner}</div>
}
