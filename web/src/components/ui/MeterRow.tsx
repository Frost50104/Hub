import { type ReactNode } from 'react'

import { cn } from '@/lib/cn'

type MeterTone = 'amber' | 'blue' | 'red' | 'neutral'

const FILL: Record<MeterTone, string> = {
  amber: 'bg-amber',
  blue: 'bg-blue-deep',
  // Красный здесь — только для «провалов/просрочки», не для «падения метрики».
  red: 'bg-red',
  neutral: 'bg-text2',
}

interface MeterRowProps {
  label: ReactNode
  /** Доля заполнения 0–100. */
  pct: number
  /** Значение справа: «9», «38/47 (81%)». */
  value?: ReactNode
  tone?: MeterTone
  /** Ширина подписи, px (88 на десктопе, 76 на телефоне). */
  labelWidth?: number
  className?: string
}

/**
 * Строка «подпись фиксированной ширины + полоса 8px + значение tabular».
 * Загрузка по людям, агрегаты кастом-полей, темы провалов, ознакомления,
 * результаты опроса — одна строка на все.
 */
export function MeterRow({
  label,
  pct,
  value,
  tone = 'amber',
  labelWidth = 88,
  className,
}: MeterRowProps) {
  const width = Math.max(0, Math.min(100, pct))
  return (
    <div
      className={cn('grid items-center gap-3 text-[14px]', className)}
      style={{ gridTemplateColumns: `${labelWidth}px minmax(0,1fr) auto` }}
    >
      <span className="min-w-0 truncate text-text2">{label}</span>
      <span className="block h-2 overflow-hidden rounded-full bg-surface">
        <span
          className={cn('block h-full rounded-full', FILL[tone])}
          style={{ width: `${width}%` }}
        />
      </span>
      <span className="min-w-[2ch] text-right tabular-nums text-text">{value}</span>
    </div>
  )
}
