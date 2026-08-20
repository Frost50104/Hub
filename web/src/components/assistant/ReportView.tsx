import { useMutation, useQuery } from '@tanstack/react-query'
import { ArrowLeft, Download, ListPlus } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { CreateTaskDialog } from '@/components/task/CreateTaskDialog'
import { QueryError } from '@/components/QueryError'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { SkeletonRows } from '@/components/ui/Skeleton'
import { cn } from '@/lib/cn'
import { extractErrorDetail } from '@/lib/errors'
import { reportsApi, type Report, type ReportKind } from '@/lib/assistant'

/**
 * Экран отчётов iiko.
 *
 * Графика — собственные `div`'ы, а не библиотека: полоса это ширина в
 * процентах, гистограмма — высота. Тащить recharts на этот экран нельзя,
 * бандл и так резался code-splitting'ом.
 *
 * Цвет здесь несёт смысл: рост — `--amber`, падение — нейтральный `--text2`,
 * дельта роста — `--green-deep`. **Падение красным не красится**: красный в
 * дизайн-системе занят просрочкой и ошибками, иначе плохая неделя выглядела
 * бы как авария системы.
 */

function StatCard({ label, value, positive }: { label: string; value: string; positive: boolean }) {
  return (
    <div className="flex min-w-[140px] flex-1 shrink-0 flex-col gap-1 rounded-xl border border-glass-border bg-tint px-3.5 py-3">
      <span className="text-[13px] text-text2">{label}</span>
      <span
        className={cn(
          'font-display text-[17px] font-bold leading-[1.2] lg:text-[20px]',
          positive ? 'text-green-deep' : 'text-text',
        )}
      >
        {value}
      </span>
    </div>
  )
}

function Bars({ rows }: { rows: Report['bars'] }) {
  return (
    <div className="space-y-3">
      {rows.map((b) => (
        <div
          key={b.name}
          className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3.5 gap-y-1.5 lg:grid-cols-[170px_minmax(0,1fr)_116px_70px]"
        >
          <span className="truncate text-[15px] text-text lg:order-1">{b.name}</span>
          <span className="order-3 col-span-2 lg:order-2 lg:col-span-1">
            <span
              className={cn(
                'block h-[10px] rounded-[5px]',
                b.up ? 'bg-amber' : 'bg-text2',
              )}
              style={{ width: `${Math.max(b.pct, 2)}%` }}
            />
          </span>
          <span className="text-right font-mono text-[14px] font-semibold text-text lg:order-3">
            {b.sum}
          </span>
          <span
            className={cn(
              'order-2 text-right font-mono text-[14px] font-semibold lg:order-4',
              b.up ? 'text-green-deep' : 'text-text2',
            )}
          >
            {b.delta}
          </span>
        </div>
      ))}
    </div>
  )
}

function Hours({ rows }: { rows: Report['hours'] }) {
  return (
    <div className="flex items-end gap-1.5 overflow-x-auto pb-1">
      {rows.map((h) => (
        <div key={h.label} className="flex min-w-[18px] flex-1 flex-col items-center gap-1.5">
          <span
            className={cn(
              'block w-full rounded-t-[4px]',
              h.pct >= 82 ? 'bg-amber' : 'bg-text2',
            )}
            style={{ height: `${Math.max(Math.round(h.pct * 1.35), 3)}px` }}
          />
          <span className="text-[12px] text-text2">{h.label}</span>
        </div>
      ))}
    </div>
  )
}

function ItemList({ title, rows, muted }: { title: string; rows: Report['top']; muted?: boolean }) {
  return (
    <div className="min-w-0 flex-1">
      <div className="flex items-baseline justify-between gap-2">
        <p className="font-display text-[15px] font-semibold text-text">{title}</p>
        {/* Подпись колонки, а не единица у каждого числа: iiko отдаёт в
            одном поле и штуки, и килограммы. */}
        <p className="shrink-0 text-[12px] text-text2">продано · доля</p>
      </div>
      <ul className="mt-1.5">
        {rows.map((t, i) => (
          <li
            key={t.name}
            className={cn(
              'flex min-h-[38px] items-center gap-2.5',
              i > 0 && 'border-t border-hair',
            )}
          >
            <span className="min-w-0 flex-1 truncate text-[15px] text-text">{t.name}</span>
            <span className="shrink-0 text-[13px] text-text2">{t.qty}</span>
            <span
              className={cn(
                'shrink-0 font-mono text-[14px] font-semibold',
                muted ? 'text-text2' : 'text-text',
              )}
            >
              {t.share}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

export function ReportView({
  initialKind,
  onBack,
}: {
  initialKind?: ReportKind
  onBack?: () => void
}) {
  const [kind, setKind] = useState<ReportKind>(initialKind ?? 'revenue')
  const [range, setRange] = useState<{ from: string; to: string } | null>(null)
  const [picking, setPicking] = useState(false)
  const [taskFrom, setTaskFrom] = useState<string | null>(null)

  const catalog = useQuery({ queryKey: ['iiko-catalog'], queryFn: reportsApi.catalog })
  const report = useQuery({
    queryKey: ['iiko-report', kind, range?.from, range?.to],
    queryFn: () => reportsApi.get(kind, range?.from, range?.to),
    enabled: catalog.data?.configured === true,
    retry: false,
  })

  const csv = useMutation({
    mutationFn: () => reportsApi.downloadCsv(kind, range?.from, range?.to),
    meta: { suppressGlobalError: true },
    onError: (e) => toast.error('CSV не выгрузился', { description: extractErrorDetail(e) }),
  })

  const data = report.data

  return (
    <div className="space-y-5">
      {/* Кнопка возврата — ОТДЕЛЬНОЙ строкой: в общей flex-обёртке она
          затесывалась между переносящимися вкладками и читалась как ещё
          одна вкладка. */}
      {onBack && (
        <Button size="sm" variant="ghost" className="-ml-2" onClick={onBack}>
          <ArrowLeft className="h-4 w-4" /> В журнал
        </Button>
      )}
      <div className="flex items-center gap-2">
        <div className="flex min-w-0 flex-1 flex-wrap gap-2">
          {(catalog.data?.reports ?? []).map((r) => (
            <button
              key={r.key}
              type="button"
              onClick={() => setKind(r.key)}
              className={cn(
                'inline-flex min-h-[34px] shrink-0 items-center rounded-full px-3.5 text-[13px] font-semibold',
                kind === r.key
                  ? 'bg-surface text-text'
                  : 'border border-glass-border text-text2 hover:text-text',
              )}
            >
              {r.title}
            </button>
          ))}
        </div>
      </div>

      {catalog.data && !catalog.data.configured && (
        <div className="rounded-[14px] border border-glass-border bg-tint p-6 text-center">
          <p className="font-display text-[15px] font-semibold text-text">
            Отчёты iiko не подключены
          </p>
          <p className="mx-auto mt-1.5 max-w-md text-[15px] leading-[1.5] text-text2">
            Администратору нужно задать адрес сервера iiko и учётную запись с правом
            на отчёты — после этого ассистент начнёт собирать выручку, средний чек и
            списания.
          </p>
        </div>
      )}

      {report.isLoading && <SkeletonRows rows={5} />}
      {report.isError && (
        <div className="rounded-[14px] border border-glass-border bg-tint p-5">
          <p className="text-[15px] leading-[1.5] text-text2">
            {extractErrorDetail(report.error)}
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button size="sm" variant="secondary" onClick={() => void report.refetch()}>
              Повторить
            </Button>
            {range && (
              <Button size="sm" variant="ghost" onClick={() => setRange(null)}>
                Вернуть период по умолчанию
              </Button>
            )}
          </div>
        </div>
      )}

      {data && (
        <>
          <div>
            <h2 className="font-display text-[20px] font-bold leading-[1.25] text-text lg:text-[24px]">
              {data.title}
            </h2>
            <p className="mt-1 text-[15px] text-text2">{data.subtitle}</p>
          </div>

          <div className="flex flex-wrap gap-2.5">
            {data.stats.map((s) => (
              <StatCard key={s.label} {...s} />
            ))}
          </div>

          <div className="rounded-[14px] border border-glass-border bg-tint p-4">
            {data.chart === 'bars' && <Bars rows={data.bars} />}
            {data.chart === 'hours' && <Hours rows={data.hours} />}
            {data.chart === 'lists' && (
              <div className="flex flex-col gap-5 lg:flex-row lg:gap-8">
                <ItemList title="Топ продаж" rows={data.top} />
                <ItemList title="Тянут вниз" rows={data.anti} muted />
              </div>
            )}
            {!data.bars.length && !data.hours.length && !data.top.length && (
              <p className="text-[15px] text-text2">
                За этот период iiko не отдал ни одной строки. Проверьте период — или
                продаж действительно не было.
              </p>
            )}
          </div>

          {data.note && (
            <p className="max-w-[760px] text-[15px] leading-[1.5] text-text2">{data.note}</p>
          )}

          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="secondary" onClick={() => setPicking((v) => !v)}>
              Другой период
            </Button>
            <Button
              size="sm"
              variant="secondary"
              disabled={csv.isPending}
              onClick={() => csv.mutate()}
            >
              <Download className="h-4 w-4" /> CSV
            </Button>
            <Button size="sm" onClick={() => setTaskFrom(`${data.title} · ${data.subtitle}`)}>
              <ListPlus className="h-4 w-4" /> Создать задачу по отчёту
            </Button>
          </div>

          {picking && (
            <div className="flex flex-wrap items-end gap-2 rounded-[14px] border border-glass-border bg-tint p-3.5">
              <label className="text-[13px] text-text2">
                С
                <Input
                  type="date"
                  className="mt-1"
                  defaultValue={data.period.from}
                  onChange={(e) =>
                    setRange((r) => ({ from: e.target.value, to: r?.to ?? data.period.to }))
                  }
                />
              </label>
              <label className="text-[13px] text-text2">
                По
                <Input
                  type="date"
                  className="mt-1"
                  defaultValue={data.period.to}
                  onChange={(e) =>
                    setRange((r) => ({ from: r?.from ?? data.period.from, to: e.target.value }))
                  }
                />
              </label>
              <Button size="sm" variant="ghost" onClick={() => setRange(null)}>
                Сбросить
              </Button>
            </div>
          )}
        </>
      )}

      {catalog.isError && <QueryError onRetry={() => void catalog.refetch()} />}

      {taskFrom && (
        <CreateTaskDialog open onOpenChange={() => setTaskFrom(null)} />
      )}
    </div>
  )
}
