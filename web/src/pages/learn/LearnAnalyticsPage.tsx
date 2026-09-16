import { useQuery } from '@tanstack/react-query'
import { Download } from 'lucide-react'

import { MobilePageHeader } from '@/components/layout/MobilePageHeader'
import { QueryError } from '@/components/QueryError'
import { Button } from '@/components/ui/Button'
import { MeterRow } from '@/components/ui/MeterRow'
import { SkeletonRows } from '@/components/ui/Skeleton'
import { StatTile } from '@/components/ui/StatTile'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { COURSE_TYPE_LABEL, learnApi } from '@/lib/learn'
import { nbsp } from '@/lib/typography'

import { useAdminEmbedded } from './adminEmbed'

/**
 * Аналитика обучения (Ф5, ТЗ §21) по макету «Управление → Аналитика»:
 * четыре KPI-плитки, таблица курсов, «Темы провалов» и «Обязательные
 * ознакомления» — CSS-полосами (`MeterRow`), без recharts. Красный у провалов
 * допустим: это семантика ошибки, не акцент. Скоуп считает сервер
 * (org_scope): админ/публикатор — вся сеть, ТУ/франчайзи — свои магазины.
 * Опросы намеренно не здесь — их агрегаты только на странице опроса.
 */

export function LearnAnalyticsPage() {
  const isDesktop = useIsDesktop()
  const embedded = useAdminEmbedded()
  const data = useQuery({
    queryKey: ['learn-analytics'],
    queryFn: learnApi.analytics,
    staleTime: 60_000,
  })
  const a = data.data
  const engagement =
    a && a.overview.employees_total
      ? Math.round((a.overview.engaged_30d / a.overview.employees_total) * 100)
      : null

  return (
    <div className={embedded ? undefined : 'mx-auto max-w-4xl'}>
      {!isDesktop && !embedded && <MobilePageHeader eyebrow="Обучение" title="Аналитика" />}
      <div className={embedded ? 'flex flex-col gap-5' : 'flex flex-col gap-5 p-4 lg:p-8'}>
        <div className="flex flex-wrap items-center justify-between gap-2">
          {isDesktop && !embedded && (
            <h1 className="font-display text-2xl font-bold text-text">Аналитика обучения</h1>
          )}
          <div className="flex flex-wrap items-center gap-2">
            {a && (
              <span className="text-[13px] text-text2">
                {a.scope === 'all' ? 'срез: вся сеть' : 'срез: мои точки'} · считает сервер
              </span>
            )}
            <Button variant="secondary" className="bg-transparent" onClick={() => void learnApi.downloadAnalyticsCsv()}>
              <Download className="h-4 w-4" /> Выгрузить CSV
            </Button>
          </div>
        </div>

        {data.isLoading && <SkeletonRows rows={6} />}
        {data.isError && <QueryError onRetry={() => void data.refetch()} />}

        {a && (
          <>
            <div className="grid grid-cols-2 gap-2.5 lg:grid-cols-4">
              <StatTile variant="kpi" label="Сотрудников в срезе" value={String(a.overview.employees_total)} />
              <StatTile
                variant="kpi"
                label="Заходили в Hub"
                value={String(a.overview.employees_linked)}
                hint="привязали аккаунт"
              />
              <StatTile
                variant="kpi"
                label="Активны за 30 дней"
                value={String(a.overview.engaged_30d)}
                hint={engagement !== null ? `${engagement}% вовлечённость` : undefined}
              />
              <StatTile variant="kpi" label="Баллы за 30 дней" value={nbsp(a.overview.points_30d.toLocaleString('ru-RU'))} />
            </div>

            <section className="flex flex-col gap-2">
              <h2 className="text-[12px] font-bold uppercase tracking-[0.09em] text-text2">Курсы</h2>
              {a.courses.length === 0 ? (
                <p className="text-[14px] text-text2">Опубликованных курсов пока нет.</p>
              ) : (
                <div className="overflow-hidden rounded-xl border border-hair">
                  <div className="hidden grid-cols-[1fr_150px_90px_90px_110px] gap-2.5 border-b border-hair bg-tint px-3.5 py-[9px] text-[11px] font-bold uppercase tracking-[0.07em] text-text2 lg:grid">
                    <span>Курс</span>
                    <span>Тип</span>
                    <span className="text-right">Начали</span>
                    <span className="text-right">Завершили</span>
                    <span className="text-right">Ср. балл теста</span>
                  </div>
                  {a.courses.map((c, i) => (
                    <div
                      key={c.id}
                      className={
                        'flex flex-wrap items-center gap-x-2.5 gap-y-1 px-3.5 py-2.5 text-[14px] lg:grid lg:grid-cols-[1fr_150px_90px_90px_110px]' +
                        (i > 0 ? ' border-t border-hair' : '')
                      }
                    >
                      <span className="min-w-0 basis-full truncate font-semibold text-text lg:basis-auto">{c.title}</span>
                      <span className="text-text2">{COURSE_TYPE_LABEL[c.course_type]}</span>
                      <span className="tabular-nums text-text lg:text-right">
                        <span className="lg:hidden">начали </span>
                        {c.enrolled}
                      </span>
                      <span className="tabular-nums text-text lg:text-right">
                        <span className="lg:hidden">· завершили </span>
                        {c.completed}
                      </span>
                      <span className="font-semibold tabular-nums text-text lg:text-right">
                        <span className="lg:hidden">· тест </span>
                        {c.avg_quiz_score !== null ? `${c.avg_quiz_score}%` : '—'}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </section>

            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              {a.fail_questions.length > 0 && (
                <section className="flex flex-col gap-2.5 rounded-xl border border-hair p-4">
                  <h2 className="text-[12px] font-bold uppercase tracking-[0.09em] text-text2">
                    Темы провалов · доля неверных
                  </h2>
                  {a.fail_questions.map((f, i) => (
                    <MeterRow
                      key={i}
                      label={
                        <span className="block truncate" title={f.prompt}>
                          {f.prompt}
                        </span>
                      }
                      pct={f.fail_rate_pct}
                      value={`${f.fail_rate_pct}%`}
                      tone="red"
                      labelWidth={isDesktop ? 200 : 140}
                    />
                  ))}
                </section>
              )}
              {a.acks.length > 0 && (
                <section className="flex flex-col gap-2.5 rounded-xl border border-hair p-4">
                  <h2 className="text-[12px] font-bold uppercase tracking-[0.09em] text-text2">
                    Обязательные ознакомления
                  </h2>
                  {a.acks.map((m) => {
                    const pct = m.total ? Math.round((m.acked / m.total) * 100) : 0
                    return (
                      <MeterRow
                        key={m.id}
                        label={
                          <span className="block truncate" title={m.title}>
                            {m.title}
                          </span>
                        }
                        pct={pct}
                        value={nbsp(`${m.acked}/${m.total} (${pct}%)`)}
                        tone="amber"
                        labelWidth={isDesktop ? 200 : 140}
                      />
                    )
                  })}
                </section>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
