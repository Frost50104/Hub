import { Award, Trophy } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import { MobilePageHeader } from '@/components/layout/MobilePageHeader'
import { QueryError } from '@/components/QueryError'
import { SkeletonRows } from '@/components/ui/Skeleton'
import { useMyCertificates, useRating } from '@/hooks/useLearn'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { cn } from '@/lib/cn'
import { type RatingRow } from '@/lib/learn'

/** Рейтинг активности (Ф3b, ТЗ §7): лидерборд за месяц/квартал, вся сеть
 * или мой магазин. Баллы идут за «первые действия» — повторы не считаются. */

function Row({ row }: { row: RatingRow }) {
  const medal = row.rank === 1 ? '🥇' : row.rank === 2 ? '🥈' : row.rank === 3 ? '🥉' : null
  return (
    <div
      className={cn(
        'flex items-center gap-3 rounded-lg border px-3 py-2',
        row.is_me ? 'border-amber/60 bg-amber/5' : 'border-glass-border bg-glass',
      )}
    >
      <span className="w-8 shrink-0 text-center text-sm font-semibold text-text2">
        {medal ?? row.rank}
      </span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-text">
          {row.full_name}
          {row.is_me && <span className="ml-1.5 text-xs text-amber">— это вы</span>}
        </p>
        <p className="truncate text-xs text-text3">
          {[row.position_name, row.store_name].filter(Boolean).join(' · ') || '—'}
        </p>
      </div>
      <span className="shrink-0 text-sm font-semibold text-amber">
        {Number.isInteger(row.points) ? row.points : row.points.toFixed(1)}
      </span>
    </div>
  )
}

function Toggle<T extends string>({
  value,
  options,
  onChange,
}: {
  value: T
  options: [T, string][]
  onChange: (v: T) => void
}) {
  return (
    <div className="flex items-center gap-1 rounded-lg border border-glass-border p-0.5">
      {options.map(([key, label]) => (
        <button
          key={key}
          type="button"
          onClick={() => onChange(key)}
          className={cn(
            'rounded px-2.5 py-1 text-xs font-medium',
            value === key ? 'bg-surface text-amber' : 'text-text3 hover:text-text',
          )}
        >
          {label}
        </button>
      ))}
    </div>
  )
}

export function LearnRatingPage() {
  const isDesktop = useIsDesktop()
  const [period, setPeriod] = useState<'month' | 'quarter'>('month')
  const [scope, setScope] = useState<'all' | 'store'>('all')
  const rating = useRating(period, scope)
  const certificates = useMyCertificates()

  const rows = rating.data?.rows ?? []
  const me = rating.data?.me ?? null
  const meOutsideTop = me !== null && !rows.some((r) => r.is_me)

  return (
    <div className="mx-auto max-w-3xl">
      {!isDesktop && <MobilePageHeader eyebrow="Обучение" title="Рейтинг" />}
      <div className="space-y-4 p-4 lg:p-8">
        <div className="flex flex-wrap items-center justify-between gap-2">
          {isDesktop && (
            <h1 className="font-display text-2xl font-bold text-text">Рейтинг активности</h1>
          )}
          <div className="flex flex-wrap gap-2">
            <Toggle
              value={period}
              options={[
                ['month', 'Месяц'],
                ['quarter', 'Квартал'],
              ]}
              onChange={setPeriod}
            />
            <Toggle
              value={scope}
              options={[
                ['all', 'Вся сеть'],
                ['store', 'Мой магазин'],
              ]}
              onChange={setScope}
            />
          </div>
        </div>
        <p className="text-xs text-text3">
          Баллы начисляются за первые действия: пройденные уроки и тесты,
          ознакомления, опросы. Повторы не удваивают баллы.
        </p>

        {rating.isLoading && <SkeletonRows rows={6} />}
        {rating.isError && <QueryError onRetry={() => void rating.refetch()} />}

        {rating.data && rows.length === 0 && (
          <div className="rounded-xl border border-glass-border bg-glass p-8 text-center">
            <Trophy className="mx-auto h-8 w-8 text-text3" />
            <p className="mt-3 text-sm text-text2">
              За этот период активности пока нет.
            </p>
          </div>
        )}

        <div className="space-y-1.5">
          {rows.map((row) => (
            <Row key={row.profile_id} row={row} />
          ))}
          {meOutsideTop && me && (
            <>
              <p className="py-1 text-center text-xs text-text3">···</p>
              <Row row={me} />
            </>
          )}
        </div>

        {(certificates.data?.length ?? 0) > 0 && (
          <div className="space-y-1.5">
            <p className="pt-2 text-[11px] font-semibold uppercase tracking-wider text-text3">
              Мои сертификаты
            </p>
            {certificates.data!.map((cert) => (
              <Link
                key={cert.id}
                to={`/learn/certificates/${cert.id}`}
                className="flex items-center gap-2.5 rounded-lg border border-glass-border bg-glass px-3 py-2 text-sm text-text transition-colors hover:border-amber/50"
              >
                <Award className="h-4 w-4 shrink-0 text-amber" />
                <span className="min-w-0 flex-1 truncate">{cert.course_title}</span>
                <span className="shrink-0 text-xs text-text3">
                  {new Date(cert.issued_at).toLocaleDateString('ru-RU')}
                </span>
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
