import { ArrowDownRight, ArrowUpRight, Minus } from 'lucide-react'

import { cn } from '@/lib/cn'
import type { Dynamics } from '@/lib/race'
import { DYNAMICS_LABEL } from '@/lib/raceBoard'

const ICON = { up: ArrowUpRight, flat: Minus, down: ArrowDownRight } as const

/** Направление — иконка и слово, цвет вторичен (снижение НЕ красное). */
export function DynamicsMark({ value, compact = false, className }: { value: Dynamics | null; compact?: boolean; className?: string }) {
  if (!value) return <span className={cn('text-text3', className)}>—</span>
  const Icon = ICON[value]
  return (
    <span
      className={cn('inline-flex items-center gap-1 whitespace-nowrap', className)}
      style={{ color: `var(--race-${value})` }}
      title={DYNAMICS_LABEL[value]}
    >
      <Icon className="h-4 w-4 shrink-0" strokeWidth={2.2} />
      {!compact && <span className="text-[13px] font-semibold">{DYNAMICS_LABEL[value]}</span>}
    </span>
  )
}
