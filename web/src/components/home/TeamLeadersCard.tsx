import { isAxiosError } from 'axios'
import { useState } from 'react'

import { QueryError } from '@/components/QueryError'
import { Avatar } from '@/components/ui/Avatar'
import { SegmentGroup } from '@/components/ui/SegmentGroup'
import { Skeleton } from '@/components/ui/Skeleton'
import { useLeaders } from '@/hooks/useLeaders'
import { useMe } from '@/hooks/useMe'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { cn } from '@/lib/cn'
import {
  LEADER_COLUMNS,
  columnMe,
  columnRows,
  meLine,
  type LeaderColumn,
  type LeaderColumnDef,
} from '@/lib/leaders'
import type { Leader, Leaders } from '@/lib/stats'

function Row({ lead, me, tone }: { lead: Leader; me: boolean; tone: LeaderColumnDef['tone'] }) {
  return (
    <div
      className={cn(
        'flex min-h-[52px] items-center gap-2.5 rounded-xl border px-2.5 py-2',
        me ? 'border-amber/55 bg-amber/[0.08]' : 'border-hair bg-tint',
      )}
    >
      {/* Пилюля места 28×28, как у лидеров гонки: амбер у позитивных колонок,
          у просрочки — красная без «медали». */}
      <span
        className={cn(
          'flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-[13px] font-bold tabular-nums',
          tone === 'danger' ? 'bg-red/15 text-red' : 'bg-amber text-on-amber',
        )}
      >
        {lead.rank}
      </span>
      <Avatar name={lead.full_name} employeeId={lead.employee_id} className="h-7 w-7 shrink-0 text-[11px]" />
      <span className="min-w-0 flex-1 truncate text-[15px] font-semibold leading-[1.3] text-text">
        {lead.full_name}
        {me && <span className="ml-1.5 text-[13px] font-normal text-text2">— это вы</span>}
      </span>
      <span
        className={cn(
          'shrink-0 font-display text-[18px] font-bold tabular-nums',
          tone === 'danger' ? 'text-red' : 'text-text',
        )}
      >
        {lead.count}
      </span>
    </div>
  )
}

function Column({
  def,
  data,
  myId,
  withTitle,
}: {
  def: LeaderColumnDef
  data: Leaders
  myId: string | undefined
  withTitle: boolean
}) {
  const rows = columnRows(data, def.key)
  const line = meLine(def.key, columnMe(data, def.key), rows, myId)
  return (
    <div className="flex flex-col gap-2">
      {withTitle && <h3 className="px-0.5 text-[13px] font-semibold text-text">{def.title}</h3>}
      {rows.length === 0 ? (
        <p className="px-0.5 py-3 text-[14px] text-text2">{def.empty}</p>
      ) : (
        rows.map((lead) => (
          <Row key={lead.employee_id} lead={lead} me={lead.employee_id === myId} tone={def.tone} />
        ))
      )}
      {line && <p className="px-0.5 pt-1 text-[13px] text-text2">{line}</p>}
    </div>
  )
}

/**
 * «Команда за 30 дней» на «Главной»: топ-3 по организации в трёх колонках —
 * выполнили, создали, просрочено сейчас. Видят все сотрудники (решение
 * владельца 01.10); личные пространства и учётки точек сервер исключает.
 * Десктоп — три колонки, телефон — `SegmentGroup` и одна колонка: три стопки
 * заняли бы ≈600px. Без hub-роли ручка отвечает 403 — карточка молча не
 * рисуется, «Главная» краснеть не должна.
 */
export function TeamLeadersCard({ className }: { className?: string }) {
  const isDesktop = useIsDesktop()
  const me = useMe()
  const { data, isLoading, isError, error, refetch } = useLeaders()
  const [column, setColumn] = useState<LeaderColumn>('completed')

  if (isError && isAxiosError(error) && (error.response?.status === 403 || error.response?.status === 404)) {
    return null
  }
  const myId = me.data?.employee_id

  return (
    <section
      className={cn(
        'flex flex-col gap-3.5 rounded-[14px] border border-glass-border bg-tint p-4',
        className,
      )}
    >
      <header className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h2 className="font-body text-[12px] font-bold uppercase tracking-[0.07em] text-text2">
          Команда за 30 дней
        </h2>
        {/* Плитка «Выполнено» выше считает и личные задачи — здесь их нет;
            без подписи два числа одного человека на одном экране расходятся. */}
        <p className="text-[13px] text-text2">По рабочим проектам, без личных · топ-3</p>
      </header>

      {isLoading && (
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
          <Skeleton className="h-[180px]" />
          <Skeleton className="hidden h-[180px] lg:block" />
          <Skeleton className="hidden h-[180px] lg:block" />
        </div>
      )}

      {isError && (
        <QueryError title="Не удалось загрузить рейтинг" onRetry={() => void refetch()} />
      )}

      {data && isDesktop && (
        <div className="grid grid-cols-1 gap-3.5 lg:grid-cols-3">
          {LEADER_COLUMNS.map((def) => (
            <Column key={def.key} def={def} data={data} myId={myId} withTitle />
          ))}
        </div>
      )}

      {data && !isDesktop && (
        <>
          <SegmentGroup
            ariaLabel="Колонка рейтинга"
            options={LEADER_COLUMNS.map((c) => ({ value: c.key, label: c.short }))}
            value={column}
            onChange={setColumn}
            size="lg"
            fullWidth
          />
          <Column
            def={LEADER_COLUMNS.find((c) => c.key === column)!}
            data={data}
            myId={myId}
            withTitle={false}
          />
        </>
      )}
    </section>
  )
}
