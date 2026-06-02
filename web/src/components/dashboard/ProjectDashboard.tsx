import { AlertCircle, Loader2 } from 'lucide-react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { Avatar } from '@/components/ui/Avatar'
import { useProjectStats } from '@/hooks/useProjectStats'
import { type CustomFieldStat, type ProjectStats } from '@/lib/stats'

interface ProjectDashboardProps {
  projectId: string
}

const STATUS_LABEL: Record<string, string> = {
  todo: 'К выполнению',
  in_progress: 'В работе',
  in_review: 'На проверке',
  done: 'Готово',
}

const PRIORITY_LABEL: Record<string, string> = {
  low: 'низкий',
  medium: 'средний',
  high: 'высокий',
  urgent: 'срочно',
}

// Theme-derived chart palette. Hex literals because recharts can't read CSS
// vars at SVG-paint time.
const STATUS_COLOR: Record<string, string> = {
  todo: '#55556a',
  in_progress: '#ffb200',
  in_review: '#9090a8',
  done: '#34d399',
}

const PRIORITY_COLOR: Record<string, string> = {
  low: '#55556a',
  medium: '#9090a8',
  high: '#ffb200',
  urgent: '#ef4444',
}

const SELECT_PALETTE = [
  '#ffb200',
  '#34d399',
  '#9090a8',
  '#ef4444',
  '#55556a',
  '#f0f0f5',
]

export function ProjectDashboard({ projectId }: ProjectDashboardProps) {
  const stats = useProjectStats(projectId)

  if (stats.isLoading) {
    return (
      <div className="flex items-center gap-2 text-sm text-text2">
        <Loader2 className="h-4 w-4 animate-spin" /> Загружаем агрегаты…
      </div>
    )
  }
  if (stats.isError || !stats.data) {
    return (
      <p className="text-sm text-red">
        Не удалось загрузить статистику. Обновите страницу.
      </p>
    )
  }

  const d = stats.data

  return (
    <div className="space-y-5">
      <KpiRow stats={d} />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card title="По статусу">
          <PieFromCounts
            counts={d.status_breakdown}
            colorBy={(k) => STATUS_COLOR[k] ?? '#9090a8'}
            labelBy={(k) => STATUS_LABEL[k] ?? k}
          />
        </Card>
        <Card title="По приоритету">
          <PieFromCounts
            counts={d.priority_breakdown}
            colorBy={(k) => PRIORITY_COLOR[k] ?? '#9090a8'}
            labelBy={(k) => PRIORITY_LABEL[k] ?? k}
          />
        </Card>
      </div>

      <Card title="Готово за 30 дней">
        <TrendBars trend={d.completed_trend} />
      </Card>

      <Card title="Загрузка по людям">
        <WorkloadTable workload={d.workload} />
      </Card>

      {d.custom_field_stats.length > 0 && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {d.custom_field_stats.map((s) => (
            <Card key={s.field_id} title={s.name}>
              <CustomFieldStatBlock stat={s} />
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}

// ─── Pieces ─────────────────────────────────────────────────────────────────

function KpiRow({ stats }: { stats: ProjectStats }) {
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
      <Kpi label="Активных" value={stats.total_active} />
      <Kpi label="В архиве" value={stats.total_archived} tone="muted" />
      <Kpi label="Готово 30д" value={sumTrend(stats.completed_trend)} tone="green" />
      <Kpi
        label="Просрочено"
        value={stats.overdue_count}
        tone={stats.overdue_count > 0 ? 'red' : 'muted'}
        icon={stats.overdue_count > 0 ? <AlertCircle className="h-3.5 w-3.5" /> : undefined}
      />
    </div>
  )
}

function Kpi({
  label,
  value,
  tone = 'default',
  icon,
}: {
  label: string
  value: number
  tone?: 'default' | 'muted' | 'green' | 'red'
  icon?: React.ReactNode
}) {
  const toneCn =
    tone === 'red'
      ? 'text-red'
      : tone === 'green'
        ? 'text-green'
        : tone === 'muted'
          ? 'text-text3'
          : 'text-text'
  return (
    <div className="glass space-y-1 p-4">
      <p className="flex items-center gap-1 text-[10px] uppercase tracking-wider text-text3">
        {icon}
        {label}
      </p>
      <p className={`font-display text-2xl font-bold ${toneCn}`}>{value}</p>
    </div>
  )
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="glass space-y-3 p-4">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-text3">
        {title}
      </h3>
      {children}
    </section>
  )
}

function PieFromCounts({
  counts,
  colorBy,
  labelBy,
}: {
  counts: Record<string, number>
  colorBy: (key: string) => string
  labelBy: (key: string) => string
}) {
  const data = Object.entries(counts)
    .filter(([, count]) => count > 0)
    .map(([key, count]) => ({ name: labelBy(key), key, count }))
  if (data.length === 0) {
    return <p className="text-sm text-text3">Нет данных.</p>
  }
  return (
    <div className="h-56">
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Tooltip
            contentStyle={{
              background: 'rgba(15, 18, 32, 0.95)',
              border: '1px solid rgba(255,255,255,0.1)',
              borderRadius: 8,
              fontSize: 12,
            }}
          />
          <Pie
            data={data}
            dataKey="count"
            nameKey="name"
            innerRadius={48}
            outerRadius={80}
            paddingAngle={2}
          >
            {data.map((d) => (
              <Cell key={d.key} fill={colorBy(d.key)} stroke="none" />
            ))}
          </Pie>
        </PieChart>
      </ResponsiveContainer>
      <div className="-mt-2 flex flex-wrap justify-center gap-3 text-xs">
        {data.map((d) => (
          <span key={d.key} className="flex items-center gap-1.5 text-text2">
            <span
              className="inline-block h-2 w-2 rounded-full"
              style={{ background: colorBy(d.key) }}
            />
            {d.name} <span className="text-text3">({d.count})</span>
          </span>
        ))}
      </div>
    </div>
  )
}

function TrendBars({ trend }: { trend: ProjectStats['completed_trend'] }) {
  const data = trend.map((t) => ({
    day: t.day.slice(5), // MM-DD
    count: t.count,
  }))
  return (
    <div className="h-48">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 5, right: 10, left: -16, bottom: 0 }}>
          <CartesianGrid stroke="rgba(255,255,255,0.05)" vertical={false} />
          <XAxis
            dataKey="day"
            stroke="#9090a8"
            fontSize={10}
            tickLine={false}
            interval={4}
          />
          <YAxis
            stroke="#9090a8"
            fontSize={10}
            tickLine={false}
            allowDecimals={false}
          />
          <Tooltip
            cursor={{ fill: 'rgba(255,178,0,0.08)' }}
            contentStyle={{
              background: 'rgba(15, 18, 32, 0.95)',
              border: '1px solid rgba(255,255,255,0.1)',
              borderRadius: 8,
              fontSize: 12,
            }}
          />
          <Bar dataKey="count" fill="#ffb200" radius={[3, 3, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

function WorkloadTable({
  workload,
}: {
  workload: ProjectStats['workload']
}) {
  if (workload.length === 0) {
    return <p className="text-sm text-text3">Нет назначенных задач.</p>
  }
  const maxActive = Math.max(1, ...workload.map((w) => w.active_count))
  return (
    <ul className="space-y-1.5">
      {workload.map((w, idx) => {
        const label = w.full_name ?? w.email ?? 'Без исполнителя'
        const widthPct = (w.active_count / maxActive) * 100
        return (
          <li
            key={w.employee_id ?? `unassigned-${idx}`}
            className="flex items-center gap-3"
          >
            <Avatar
              name={w.full_name}
              email={w.email}
              className="h-7 w-7 shrink-0 text-[10px]"
            />
            <div className="min-w-0 flex-1">
              <div className="flex items-baseline justify-between gap-2">
                <span className="truncate text-sm text-text">{label}</span>
                <span className="shrink-0 text-xs text-text3">
                  {w.active_count} активных · {w.done_count} готово
                </span>
              </div>
              <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-glass">
                <div
                  className="h-full rounded-full bg-amber/70"
                  style={{ width: `${widthPct}%` }}
                />
              </div>
            </div>
          </li>
        )
      })}
    </ul>
  )
}

function CustomFieldStatBlock({ stat }: { stat: CustomFieldStat }) {
  if (stat.type === 'number' && stat.number) {
    const n = stat.number
    if (n.count === 0) {
      return <p className="text-sm text-text3">Пусто.</p>
    }
    return (
      <div className="grid grid-cols-4 gap-2 text-center">
        <NumStat label="Сумма" value={n.sum} />
        <NumStat label="Среднее" value={n.avg} fraction />
        <NumStat label="Мин" value={n.min} fraction />
        <NumStat label="Макс" value={n.max} fraction />
      </div>
    )
  }
  if (
    (stat.type === 'select' || stat.type === 'multi_select') &&
    stat.select
  ) {
    const opts = stat.select.options
    if (opts.length === 0) {
      return <p className="text-sm text-text3">Никто не выбрал опцию.</p>
    }
    const total = opts.reduce((s, o) => s + o.count, 0) || 1
    return (
      <ul className="space-y-1.5">
        {opts.map((o, i) => {
          const color = SELECT_PALETTE[i % SELECT_PALETTE.length]!
          const pct = (o.count / total) * 100
          return (
            <li key={o.id} className="text-xs">
              <div className="flex items-baseline justify-between">
                <span className="truncate text-text">{o.label}</span>
                <span className="shrink-0 text-text3">
                  {o.count} ({pct.toFixed(0)}%)
                </span>
              </div>
              <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-glass">
                <div
                  className="h-full rounded-full"
                  style={{ width: `${pct}%`, background: color }}
                />
              </div>
            </li>
          )
        })}
      </ul>
    )
  }
  return <p className="text-sm text-text3">Тип не агрегируется.</p>
}

function NumStat({
  label,
  value,
  fraction,
}: {
  label: string
  value: number | null
  fraction?: boolean
}) {
  return (
    <div className="rounded-md border border-glass-border bg-surface p-2">
      <p className="text-[10px] uppercase tracking-wider text-text3">{label}</p>
      <p className="font-display text-sm font-semibold text-text">
        {value === null
          ? '—'
          : fraction
            ? value.toFixed(1)
            : Number.isInteger(value)
              ? value
              : value.toFixed(1)}
      </p>
    </div>
  )
}

function sumTrend(trend: ProjectStats['completed_trend']): number {
  return trend.reduce((s, p) => s + p.count, 0)
}
