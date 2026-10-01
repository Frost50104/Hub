import { Chip } from '@/components/ui/Chip'
import { cn } from '@/lib/cn'
import type { RaceParticipant } from '@/lib/race'
import { formatAvg, formatCells, formatPct, type RacePeriods } from '@/lib/raceBoard'
import { nbsp } from '@/lib/typography'

import { DynamicsMark } from './DynamicsMark'

/**
 * Цифры точки: процент к базе главным числом, средняя, база, чеки.
 * `periods` — за какие дни это посчитано (`racePeriods`): строка под именем —
 * период живых чисел, строка под «Базой» — её окно.
 */
export function GooseTooltip({
  p,
  periods,
  variant = 'floating',
  className,
}: {
  p: RaceParticipant
  periods?: RacePeriods | null
  variant?: 'floating' | 'card'
  className?: string
}) {
  return (
    <div
      className={cn(
        variant === 'floating'
          ? 'glass-solid w-[240px] rounded-xl border border-hair p-3 shadow-glass'
          : 'rounded-xl border border-hair bg-tint p-3',
        className,
      )}
      role="status"
    >
      <div className="flex items-center gap-2">
        {p.code && (
          <Chip variant="outline" size="sm">
            {p.code}
          </Chip>
        )}
        <span className="min-w-0 truncate text-[14px] font-semibold text-text">{p.name}</span>
      </div>
      {periods?.live && <p className="mt-1 text-[12px] text-text2">{periods.live}</p>}
      {p.needs_baseline ? (
        <p className="mt-2 text-[13px] text-text2">База не задана — точка вне зачёта. Администратор задаст базу в «Управлении».</p>
      ) : (
        <>
          <p className="mt-2 font-display text-[22px] font-bold leading-none tabular-nums text-text">
            {formatPct(p.pct)} <span className="text-[12px] font-normal text-text2">к базе</span>
          </p>
          <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-[13px]">
            <dt className="text-text2">В чеке сейчас</dt>
            <dd className="text-right tabular-nums text-text">{formatAvg(p.avg)}</dd>
            <dt className="text-text2">База</dt>
            <dd className="text-right tabular-nums text-text">{formatAvg(p.base)}</dd>
            {periods?.base && <dd className="col-span-2 -mt-0.5 text-[12px] text-text2">{periods.base}</dd>}
            <dt className="text-text2">Клеток</dt>
            <dd className="text-right tabular-nums text-text">{formatCells(p.cells)}</dd>
            <dt className="text-text2">Чеков</dt>
            <dd className="text-right tabular-nums text-text">{nbsp(String(p.receipts))}</dd>
          </dl>
          <div className="mt-2">
            <DynamicsMark value={p.dynamics} />
          </div>
        </>
      )}
    </div>
  )
}
