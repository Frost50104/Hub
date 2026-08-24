import { BarChart3, Loader2 } from 'lucide-react'
import { type ReactNode } from 'react'

import { Avatar } from '@/components/ui/Avatar'
import { Donut, type DonutSegment } from '@/components/ui/Donut'
import { EmptyState } from '@/components/ui/EmptyState'
import { ErrorBanner } from '@/components/ui/ErrorBanner'
import { MeterRow } from '@/components/ui/MeterRow'
import { MiniBarChart } from '@/components/ui/MiniBarChart'
import { StatTile } from '@/components/ui/StatTile'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { useProjectStats } from '@/hooks/useProjectStats'
import { useStages } from '@/hooks/useStages'
import { cn } from '@/lib/cn'
import { type CustomFieldStat, type ProjectStats } from '@/lib/stats'
import { type TaskPriority } from '@/lib/tasks'
import { DONE_COLOR, PRIORITY_COLOR, SERIES_COLOR } from '@/lib/tone'
import { plural } from '@/lib/typography'

interface ProjectDashboardProps {
  projectId: string
}

/** Порядок и подписи срезов — из макета: статусы в рабочем порядке, приоритеты от частого к редкому. */
const PRIORITY_ORDER: TaskPriority[] = ['medium', 'high', 'urgent', 'low']
const PRIORITY_TITLE: Record<TaskPriority, string> = {
  medium: 'Обычный',
  high: 'Высокий',
  urgent: 'Срочно',
  low: 'Низкий',
}

/**
 * Дашборд проекта без recharts: кольца — `conic-gradient`, тренд и полосы —
 * `div`'ы. Один словарь тонов на все три вкладки (`lib/tone.ts`): статус —
 * как в списке и на доске, приоритет — планка/полоса. Ни один график не
 * изобретает свой цвет. Значения всегда продублированы текстом — на телефоне
 * нет hover, а тап по столбику 8px невозможен.
 */
function ProjectDashboard({ projectId }: ProjectDashboardProps) {
  const stats = useProjectStats(projectId)
  const stages = useStages(projectId)

  if (stats.isLoading) {
    return (
      <div className="flex items-center gap-2 p-2 text-[14px] text-text2">
        <Loader2 className="h-4 w-4 animate-spin" /> Загружаем агрегаты…
      </div>
    )
  }
  if (stats.isError || !stats.data) {
    return (
      <ErrorBanner
        title="Не удалось загрузить статистику"
        text="Агрегаты считаются на сервере — обновите страницу."
        actionLabel="Обновить"
        onAction={() => void stats.refetch()}
      />
    )
  }

  const d = stats.data
  if (d.total_active + d.total_archived === 0) {
    return (
      <EmptyState
        layout="card"
        icon={<BarChart3 className="h-[26px] w-[26px]" strokeWidth={1.6} />}
        title="Считать пока нечего"
        text="Дашборд оживает с первыми задачами: разрезы по статусу и приоритету, тренд закрытий, загрузка по людям."
      />
    )
  }

  // Срез по колонкам доски: имена колонок задаёт пользователь, поэтому цвет
  // берётся по кругу из палитры графиков (0044 — системных статусов, по
  // которым раньше красили, больше нет). Без колонок — срез по состоянию.
  const byStages = d.stage_breakdown && stages.data && stages.data.length > 0
  const statusSegments: DonutSegment[] = byStages
    ? stages.data!.map((st, i) => ({
        key: st.id,
        label: st.name,
        value: d.stage_breakdown?.[st.id] ?? 0,
        color: SERIES_COLOR[i % SERIES_COLOR.length]!,
      }))
    : [
        { key: 'open', label: 'Не выполнено', value: d.done_breakdown.open ?? 0, color: DONE_COLOR.open },
        { key: 'done', label: 'Выполнено', value: d.done_breakdown.done ?? 0, color: DONE_COLOR.done },
      ]
  const prioritySegments: DonutSegment[] = PRIORITY_ORDER.map((p) => ({
    key: p,
    label: PRIORITY_TITLE[p],
    value: d.priority_breakdown[p] ?? 0,
    color: PRIORITY_COLOR[p],
  }))
  const done30 = d.completed_trend.reduce((s, p) => s + p.count, 0)

  return (
    <div className="flex flex-col gap-4">
      {/* KPI: подпись 12/700 uppercase, значение Unbounded 26 tabular; краска по
          смыслу — архив приглушён, готово зелёное, просрочка красная. */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile variant="kpi" label="Активных" value={String(d.total_active)} />
        <StatTile variant="kpi" label="В архиве" value={String(d.total_archived)} tone="muted" />
        <StatTile variant="kpi" label="Готово 30 д" value={String(done30)} tone="success" />
        <StatTile
          variant="kpi"
          label="Просрочено"
          value={String(d.overdue_count)}
          tone={d.overdue_count > 0 ? 'danger' : 'muted'}
        />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card title={byStages ? 'По колонкам' : 'По состоянию'}>
          <Donut segments={statusSegments} />
        </Card>
        <Card title="По приоритету">
          <Donut segments={prioritySegments} />
        </Card>
      </div>

      <Card title="Готово за 30 дней">
        <TrendBlock trend={d.completed_trend} />
      </Card>

      <WorkloadTable workload={d.workload} />

      {d.custom_field_stats.length > 0 && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {d.custom_field_stats.map((s, i) => (
            <Card key={s.field_id} title={s.name}>
              <CustomFieldStatBlock stat={s} tone={i % 2 === 0 ? 'amber' : 'blue'} />
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}

// ─── Pieces ─────────────────────────────────────────────────────────────────

function Card({ title, children, trailing }: { title: string; children: ReactNode; trailing?: ReactNode }) {
  return (
    <section className="flex flex-col gap-3.5 rounded-[14px] border border-glass-border bg-tint p-4">
      <header className="flex items-center justify-between gap-3">
        <h3 className="font-body text-[12px] font-bold uppercase tracking-[0.07em] text-text2">{title}</h3>
        {trailing}
      </header>
      {children}
    </section>
  )
}

function fmtDay(iso: string): string {
  return new Date(iso + 'T12:00:00').toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' })
}

function TrendBlock({ trend }: { trend: ProjectStats['completed_trend'] }) {
  const max = Math.max(0, ...trend.map((t) => t.count))
  const first = trend[0]
  const last = trend[trend.length - 1]
  return (
    <MiniBarChart
      points={trend.map((t) => ({
        key: t.day,
        value: t.count,
        title: `${fmtDay(t.day)} — ${plural(t.count, 'закрыта', 'закрыто', 'закрыто')}`,
      }))}
      height={104}
      maxLabel={`Максимум за день — ${max}`}
      startLabel={first ? fmtDay(first.day) : undefined}
      endLabel={last ? fmtDay(last.day) : undefined}
    />
  )
}

/**
 * Загрузка по людям — таблица `1fr 132 92` с шапкой на `--surface`, зебра,
 * полоса 8px амбер + число, колонка «Просрочено» 14/600 (красная при >0 —
 * это просрочка, ей красный и положен). На телефоне три колонки не влезают:
 * полоса уходит под строку, числа сводятся в одну подпись «9 · 3 просроч.».
 */
function WorkloadTable({ workload }: { workload: ProjectStats['workload'] }) {
  const isDesktop = useIsDesktop()
  const maxActive = Math.max(1, ...workload.map((w) => w.active_count))
  return (
    <section className="overflow-hidden rounded-[14px] border border-glass-border bg-tint">
      {isDesktop ? (
        <header className="grid grid-cols-[minmax(0,1fr)_132px_92px] items-center gap-3 bg-surface px-4 py-2.5 text-[12px] font-bold uppercase tracking-[0.07em] text-text2">
          <span>Загрузка по людям</span>
          <span>Открытые</span>
          <span className="text-right">Просрочено</span>
        </header>
      ) : (
        <header className="flex items-center bg-surface px-4 py-2.5 text-[12px] font-bold uppercase tracking-[0.07em] text-text2">
          Загрузка по людям
        </header>
      )}
      {workload.length === 0 ? (
        <p className="px-4 py-4 text-[14px] text-text2">Нет назначенных задач.</p>
      ) : (
        <ul>
          {workload.map((w, idx) => {
            const label = w.full_name ?? w.email ?? 'Не назначено'
            const overdue = w.overdue_count ?? 0
            const pct = (w.active_count / maxActive) * 100
            const avatar = w.employee_id ? (
              <Avatar name={w.full_name} email={w.email} className="h-6 w-6 shrink-0 text-[12px]" />
            ) : (
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-dashed border-glass-border text-[12px] text-text2">
                —
              </span>
            )
            const meter = (
              <span className="block h-2 flex-1 overflow-hidden rounded-full bg-surface">
                <span className="block h-full rounded-full bg-amber" style={{ width: `${pct}%` }} />
              </span>
            )
            if (isDesktop) {
              return (
                <li
                  key={w.employee_id ?? `unassigned-${idx}`}
                  className={cn(
                    'grid grid-cols-[minmax(0,1fr)_132px_92px] items-center gap-3 px-4 py-2.5 text-[14px]',
                    idx % 2 === 1 && 'bg-tint',
                  )}
                >
                  <span className="flex min-w-0 items-center gap-2.5">
                    {avatar}
                    <span className="min-w-0 truncate text-text">{label}</span>
                  </span>
                  <span className="flex items-center gap-2.5">
                    {meter}
                    <span className="w-6 shrink-0 text-right tabular-nums text-text">{w.active_count}</span>
                  </span>
                  <span
                    className={cn(
                      'text-right text-[14px] font-semibold tabular-nums',
                      overdue > 0 ? 'text-red' : 'text-text2',
                    )}
                  >
                    {overdue}
                  </span>
                </li>
              )
            }
            // Телефон: три колонки не влезают — полоса под строкой, числа
            // сводятся в одну подпись «9 · 3 просроч.».
            return (
              <li
                key={w.employee_id ?? `unassigned-${idx}`}
                className={cn('flex flex-col gap-1.5 px-4 py-2.5 text-[14px]', idx % 2 === 1 && 'bg-tint')}
              >
                <span className="flex items-center gap-2.5">
                  {avatar}
                  <span className="min-w-0 flex-1 truncate text-text">{label}</span>
                  <span className="shrink-0 text-right tabular-nums text-text2">
                    {w.active_count}
                    {overdue > 0 && (
                      <>
                        {' · '}
                        <span className="font-semibold text-red">{overdue} просроч.</span>
                      </>
                    )}
                  </span>
                </span>
                <span className="flex items-center">{meter}</span>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}

function CustomFieldStatBlock({ stat, tone }: { stat: CustomFieldStat; tone: 'amber' | 'blue' }) {
  if (stat.type === 'number' && stat.number) {
    const n = stat.number
    if (n.count === 0) return <p className="text-[14px] text-text2">Пусто.</p>
    const fmt = (v: number | null, fraction?: boolean) =>
      v === null ? '—' : fraction || !Number.isInteger(v) ? v.toFixed(1) : String(v)
    return (
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <StatTile label="Сумма" value={fmt(n.sum)} className="min-w-0" />
        <StatTile label="Среднее" value={fmt(n.avg, true)} className="min-w-0" />
        <StatTile label="Мин" value={fmt(n.min, true)} className="min-w-0" />
        <StatTile label="Макс" value={fmt(n.max, true)} className="min-w-0" />
      </div>
    )
  }
  if ((stat.type === 'select' || stat.type === 'multi_select') && stat.select) {
    const opts = stat.select.options
    if (opts.length === 0) return <p className="text-[14px] text-text2">Никто не выбрал опцию.</p>
    const total = opts.reduce((s, o) => s + o.count, 0) || 1
    return (
      <div className="flex flex-col gap-2">
        {opts.map((o) => (
          <MeterRow
            key={o.id}
            label={o.label}
            pct={(o.count / total) * 100}
            value={o.count}
            tone={tone}
            labelWidth={88}
          />
        ))}
      </div>
    )
  }
  return <p className="text-[14px] text-text2">Тип не агрегируется.</p>
}

// Default export — required so `React.lazy(() => import(...))` works.
export default ProjectDashboard
