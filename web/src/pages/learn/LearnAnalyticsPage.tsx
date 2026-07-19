import { useQuery } from '@tanstack/react-query'
import { BarChart3, Download, TrendingUp, Users } from 'lucide-react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { MobilePageHeader } from '@/components/layout/MobilePageHeader'
import { QueryError } from '@/components/QueryError'
import { Button } from '@/components/ui/Button'
import { SkeletonRows } from '@/components/ui/Skeleton'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { COURSE_TYPE_LABEL, learnApi } from '@/lib/learn'

/**
 * Аналитика обучения (Ф5, ТЗ §21). Скоуп считает сервер (org_scope):
 * админ/публикатор — вся сеть, ТУ/франчайзи — свои магазины.
 * Опросы намеренно не здесь — их агрегаты только на странице опроса.
 */

function StatCard({
  label,
  value,
  hint,
}: {
  label: string
  value: string | number
  hint?: string
}) {
  return (
    <div className="rounded-xl border border-glass-border bg-glass p-4">
      <p className="text-xs text-text3">{label}</p>
      <p className="mt-1 font-display text-2xl font-bold text-text">{value}</p>
      {hint && <p className="mt-0.5 text-xs text-text3">{hint}</p>}
    </div>
  )
}

export function LearnAnalyticsPage() {
  const isDesktop = useIsDesktop()
  const data = useQuery({
    queryKey: ['learn-analytics'],
    queryFn: learnApi.analytics,
    staleTime: 60_000,
  })
  const a = data.data

  return (
    <div className="mx-auto max-w-4xl">
      {!isDesktop && <MobilePageHeader eyebrow="Обучение" title="Аналитика" />}
      <div className="space-y-5 p-4 lg:p-8">
        <div className="flex flex-wrap items-center justify-between gap-2">
          {isDesktop && (
            <h1 className="font-display text-2xl font-bold text-text">
              Аналитика обучения
            </h1>
          )}
          <div className="flex items-center gap-2">
            {a && a.scope !== 'all' && (
              <span className="rounded bg-surface px-2 py-1 text-xs text-text3">
                срез: мои магазины
              </span>
            )}
            <Button
              size="sm"
              variant="secondary"
              onClick={() => void learnApi.downloadAnalyticsCsv()}
            >
              <Download className="h-4 w-4" /> CSV-отчёт
            </Button>
          </div>
        </div>

        {data.isLoading && <SkeletonRows rows={6} />}
        {data.isError && <QueryError onRetry={() => void data.refetch()} />}

        {a && (
          <>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <StatCard label="Сотрудников в срезе" value={a.overview.employees_total} />
              <StatCard
                label="Заходили в Hub"
                value={a.overview.employees_linked}
                hint="привязали аккаунт"
              />
              <StatCard
                label="Активны за 30 дней"
                value={a.overview.engaged_30d}
                hint={
                  a.overview.employees_total
                    ? `${Math.round(
                        (a.overview.engaged_30d / a.overview.employees_total) * 100,
                      )}% вовлечённость`
                    : undefined
                }
              />
              <StatCard label="Баллы за 30 дней" value={a.overview.points_30d} />
            </div>

            <div>
              <h2 className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-text3">
                <TrendingUp className="h-3.5 w-3.5" /> Курсы
              </h2>
              {a.courses.length === 0 ? (
                <p className="text-sm text-text3">Опубликованных курсов пока нет.</p>
              ) : (
                <div className="overflow-x-auto rounded-xl border border-glass-border bg-glass">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-glass-border text-left text-xs text-text3">
                        <th className="px-3 py-2 font-medium">Курс</th>
                        <th className="px-3 py-2 font-medium">Тип</th>
                        <th className="px-3 py-2 text-right font-medium">Начали</th>
                        <th className="px-3 py-2 text-right font-medium">Завершили</th>
                        <th className="px-3 py-2 text-right font-medium">Ср. балл теста</th>
                      </tr>
                    </thead>
                    <tbody>
                      {a.courses.map((c) => (
                        <tr key={c.id} className="border-b border-glass-border/50 last:border-0">
                          <td className="px-3 py-2 text-text">{c.title}</td>
                          <td className="px-3 py-2 text-text3">
                            {COURSE_TYPE_LABEL[c.course_type]}
                          </td>
                          <td className="px-3 py-2 text-right text-text">{c.enrolled}</td>
                          <td className="px-3 py-2 text-right text-text">{c.completed}</td>
                          <td className="px-3 py-2 text-right text-text">
                            {c.avg_quiz_score !== null ? `${c.avg_quiz_score}%` : '—'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            {a.fail_questions.length > 0 && (
              <div>
                <h2 className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-text3">
                  <BarChart3 className="h-3.5 w-3.5" /> Темы провалов (доля неверных
                  ответов)
                </h2>
                <div className="rounded-xl border border-glass-border bg-glass p-3">
                  <ResponsiveContainer width="100%" height={Math.max(180, a.fail_questions.length * 36)}>
                    <BarChart
                      data={a.fail_questions.map((f) => ({
                        name:
                          f.prompt.length > 40 ? `${f.prompt.slice(0, 40)}…` : f.prompt,
                        rate: f.fail_rate_pct,
                      }))}
                      layout="vertical"
                      margin={{ left: 8, right: 24 }}
                    >
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid, #333)" />
                      <XAxis type="number" domain={[0, 100]} unit="%" fontSize={11} />
                      <YAxis
                        type="category"
                        dataKey="name"
                        width={220}
                        fontSize={11}
                        tickLine={false}
                      />
                      <Tooltip formatter={(v) => [`${v}%`, 'провалы']} />
                      <Bar dataKey="rate" fill="#e05252" radius={[0, 4, 4, 0]} barSize={16} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>
            )}

            {a.acks.length > 0 && (
              <div>
                <h2 className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-text3">
                  <Users className="h-3.5 w-3.5" /> Обязательные ознакомления
                </h2>
                <div className="space-y-1.5">
                  {a.acks.map((m) => {
                    const pct = m.total ? Math.round((m.acked / m.total) * 100) : 0
                    return (
                      <div
                        key={m.id}
                        className="rounded-lg border border-glass-border bg-glass px-3 py-2"
                      >
                        <div className="flex items-center justify-between gap-2 text-sm">
                          <span className="min-w-0 flex-1 truncate text-text">{m.title}</span>
                          <span className="shrink-0 text-xs text-text3">
                            {m.acked}/{m.total} ({pct}%)
                          </span>
                        </div>
                        <span className="mt-1.5 block h-1.5 overflow-hidden rounded-full bg-surface">
                          <span
                            className="block h-full rounded-full bg-amber"
                            style={{ width: `${pct}%` }}
                          />
                        </span>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
