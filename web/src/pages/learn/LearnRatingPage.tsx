import { Award, Trophy } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import { QueryError } from '@/components/QueryError'
import { EmptyState } from '@/components/ui/EmptyState'
import { SegmentGroup, type SegmentOption } from '@/components/ui/SegmentGroup'
import { SkeletonRows } from '@/components/ui/Skeleton'
import { useMyCertificates, useRating } from '@/hooks/useLearn'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { cn } from '@/lib/cn'
import { type RatingRow } from '@/lib/learn'
import { nbsp } from '@/lib/typography'

/**
 * Рейтинг активности (Ф3b, ТЗ §7) по макету «Урок — редизайн» (route rating):
 * два независимых среза — Период и Охват — двумя `SegmentGroup` (в одном
 * плоском ряду «Месяц» и «Вся сеть» читались как два выбранных значения
 * одного фильтра); медали-эмодзи заменены плотной плашкой ранга (эмодзи не
 * читается на 8px); баллы — Unbounded `--text`, а не амбер; «это вы» —
 * строка с амбер-рамкой, за пределами топа — под разделителем.
 */

function formatPoints(points: number): string {
  return Number.isInteger(points) ? String(points) : points.toFixed(1)
}

function Row({ row, me = false }: { row: RatingRow; me?: boolean }) {
  const top = row.rank <= 3 && !me
  return (
    <div
      className={cn(
        'flex items-center gap-3 rounded-xl border px-3 py-2.5',
        me ? 'border-amber/55 bg-amber/[0.08]' : 'border-hair bg-tint',
      )}
    >
      <span
        className={cn(
          'flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-[13px] font-bold tabular-nums',
          top ? 'bg-amber text-on-amber' : 'bg-surface text-text2',
          me && 'text-text',
        )}
      >
        {row.rank}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[16px] font-semibold leading-[1.3] text-text lg:text-[17px]">
          {row.full_name}
          {me && <span className="ml-1.5 text-[13px] font-normal text-text2 lg:text-[14px]">— это вы</span>}
        </span>
        <span className="mt-0.5 block truncate text-[13px] text-text2 lg:text-[14px]">
          {[row.position_name, row.store_name].filter(Boolean).join(' · ') || '—'}
        </span>
      </span>
      <span className="shrink-0 font-display text-[16px] font-bold tabular-nums text-text lg:text-[18px]">
        {formatPoints(row.points)}
      </span>
    </div>
  )
}

const PERIODS: SegmentOption<'month' | 'quarter'>[] = [
  { value: 'month', label: 'Месяц' },
  { value: 'quarter', label: 'Квартал' },
]
const SCOPES: SegmentOption<'all' | 'store'>[] = [
  { value: 'all', label: 'Вся сеть' },
  { value: 'store', label: 'Мой магазин' },
]

export function LearnRatingPage() {
  const isDesktop = useIsDesktop()
  const [period, setPeriod] = useState<'month' | 'quarter'>('month')
  const [scope, setScope] = useState<'all' | 'store'>('all')
  const rating = useRating(period, scope)
  const certificates = useMyCertificates()

  const rows = rating.data?.rows ?? []
  const me = rating.data?.me ?? null
  const meOutsideTop = me !== null && !rows.some((r) => r.is_me)
  const total =
    rating.data !== undefined ? nbsp(`Участников: ${rating.data.total_participants}`) : ''

  return (
    <div className="mx-auto max-w-[800px] px-5 pb-16 pt-11 lg:px-8">
      <header className="flex flex-col gap-4 lg:flex-row lg:flex-wrap lg:items-end lg:justify-between lg:gap-3.5">
        <div className="min-w-0">
          <p className="mb-1 min-h-[1em] text-[12px] leading-[1.35] text-text2 lg:hidden">{total}</p>
          <h1 className="font-display text-[28px] font-bold leading-[1.18] tracking-[0.01em] text-text lg:text-[34px] lg:leading-[1.15]">
            Рейтинг активности
          </h1>
          <p className="mt-2.5 hidden min-h-[1em] text-[18px] leading-[1.6] text-text2 lg:block">{total}</p>
        </div>
        <div className="flex flex-col gap-2 lg:flex-row lg:flex-wrap lg:gap-2.5">
          <SegmentGroup
            ariaLabel="Период"
            options={PERIODS}
            value={period}
            onChange={setPeriod}
            size={isDesktop ? 'md' : 'lg'}
            fullWidth={!isDesktop}
          />
          <SegmentGroup
            ariaLabel="Охват"
            options={SCOPES}
            value={scope}
            onChange={setScope}
            size={isDesktop ? 'md' : 'lg'}
            fullWidth={!isDesktop}
          />
        </div>
      </header>

      <p className="mt-3.5 max-w-[640px] text-[14px] leading-[1.55] text-text2 [text-wrap:pretty] lg:mt-[22px] lg:text-[15px] lg:leading-[1.6]">
        Баллы начисляются за первые действия: пройденные уроки и тесты, ознакомления, опросы.
        Повторы не удваивают баллы.
      </p>

      <div className="mt-4 flex flex-col gap-[7px] lg:mt-[22px] lg:gap-2">
        {rating.isLoading && <SkeletonRows rows={6} />}
        {rating.isError && <QueryError onRetry={() => void rating.refetch()} />}
        {rating.data && rows.length === 0 && (
          <EmptyState
            layout="card"
            icon={<Trophy className="h-7 w-7" />}
            title="За этот период активности пока нет"
            text="Первые пройденные уроки, тесты и ознакомления появятся здесь с баллами."
          />
        )}
        {rows.map((row) => (
          <Row key={row.profile_id} row={row} me={row.is_me} />
        ))}
        {meOutsideTop && me && (
          <>
            <p className="my-0.5 text-center text-[14px] text-text2 lg:text-[15px]">···</p>
            <Row row={me} me />
          </>
        )}
      </div>

      {(certificates.data?.length ?? 0) > 0 && (
        <section className="mt-6 flex flex-col gap-[7px] lg:gap-2">
          <p className="text-[12px] font-bold uppercase tracking-[0.08em] text-text2">Мои сертификаты</p>
          {certificates.data!.map((cert) => (
            <Link
              key={cert.id}
              to={`/learn/certificates/${cert.id}`}
              className="flex min-h-[52px] items-center gap-2.5 rounded-xl border border-hair bg-tint px-3 py-2.5 text-text transition-colors hover:border-amber/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60 lg:min-h-12 lg:gap-[11px]"
            >
              <Award className="h-[18px] w-[18px] shrink-0 text-text2" />
              <span className="min-w-0 flex-1 text-[15px] font-semibold leading-[1.35] lg:text-[16px]">
                {cert.course_title}
              </span>
              <span className="shrink-0 text-[13px] text-text2 lg:text-[14px]">
                {new Date(cert.issued_at)
                  .toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' })
                  .replace(/\s*г\.$/, '')}
              </span>
            </Link>
          ))}
        </section>
      )}
    </div>
  )
}
