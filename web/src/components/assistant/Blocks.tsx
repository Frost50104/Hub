import { Copy } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/Button'
import { CreateTaskDialog } from '@/components/task/CreateTaskDialog'
import { cn } from '@/lib/cn'
import { plural } from '@/lib/typography'
import { type Report, type ReportKind, type TurnData } from '@/lib/assistant'

/**
 * Блоки журнала. Общий силуэт — `--tint` + `--glass-border`, радиус 14,
 * `shrink-0` (в мобильной прокручиваемой колонке иначе срезается последняя
 * строка). Амбер-рамка есть ТОЛЬКО у карточки плана: остальные блоки
 * сообщают, а не требуют решения.
 */

const BLOCK = 'shrink-0 overflow-hidden rounded-[14px] border border-glass-border bg-tint'

export function SummaryBlock({ lines }: { lines: string[] }) {
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(lines.map((l) => `— ${l}`).join('\n'))
      toast.success('Скопировано')
    } catch {
      // clipboard недоступен без https или при отказе в разрешении —
      // молча ничего не делать хуже, чем сказать.
      toast.error('Буфер обмена недоступен — выделите текст вручную')
    }
  }
  return (
    <div className={BLOCK}>
      <ul className="space-y-2.5 px-4 py-3.5">
        {lines.map((line) => (
          <li key={line} className="flex items-start gap-2.5">
            <span className="mt-[9px] block h-[5px] w-[5px] shrink-0 rounded-full bg-text3" />
            <span className="text-[15px] leading-[1.5] text-text">{line}</span>
          </li>
        ))}
      </ul>
      <div className="border-t border-hair px-4 py-3">
        <Button size="sm" variant="secondary" onClick={() => void copy()}>
          <Copy className="h-4 w-4" />
          Скопировать {plural(lines.length, 'строку', 'строки', 'строк')}
        </Button>
      </div>
    </div>
  )
}

/**
 * Отказ по правам. Смысл блока — не «нельзя», а «вот кого попросить»:
 * без второй половины сотрудник остаётся без следующего шага.
 */
export function DeniedBlock({ data }: { data: TurnData }) {
  const [asking, setAsking] = useState(false)
  const first = data.who_can?.[0]
  if (!data.who_can?.length) return null
  return (
    <div className={BLOCK}>
      <div className="px-4 py-3.5">
        <p className="text-[15px] leading-[1.5] text-text2">
          Права на этот проект есть у{' '}
          {data.who_can.map((w, i) => (
            <span key={w.name}>
              {i > 0 && ' и у '}
              <span className="text-text">{w.name}</span> ({w.role})
            </span>
          ))}
          .
        </p>
        {first && (
          <Button
            size="sm"
            variant="secondary"
            className="mt-3"
            onClick={() => setAsking(true)}
          >
            Попросить {first.name.split(' ')[0]}
          </Button>
        )}
      </div>
      {asking && <CreateTaskDialog open onOpenChange={() => setAsking(false)} />}
    </div>
  )
}

export function ErrorBlock({
  content,
  data,
  onRetry,
  onNarrow,
}: {
  content: string
  data?: TurnData | null
  onRetry: () => void
  onNarrow: () => void
}) {
  const failure = data?.report_error
  return (
    <div className={BLOCK}>
      <div className="px-4 py-3.5">
        <p className="text-[15px] leading-[1.5] text-text2">{content}</p>
        {failure?.nothing_changed && (
          // Главное, что нужно знать после сбоя: данные не тронуты.
          <p className="mt-1.5 text-[13px] leading-[1.45] text-text2">
            Ничего не изменено — можно повторить или сузить период.
          </p>
        )}
        <div className="mt-3 flex flex-wrap gap-2">
          <Button size="sm" variant="secondary" onClick={onRetry}>
            Повторить
          </Button>
          {failure?.can_narrow && (
            <Button size="sm" variant="ghost" onClick={onNarrow}>
              Сузить до недели
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}

/**
 * Компактный отчёт в журнале. Чип источника — `--blue-deep`: синий в
 * ассистенте закреплён за «откуда данные», к сравнению периодов он
 * отношения не имеет.
 *
 * Данные — снимок на момент запроса (в отличие от плана, который живёт):
 * отчёт это зафиксированный факт, и пересобирать его при открытии журнала
 * было бы и дорого (слот лицензии iiko), и неверно.
 */
export function ReportBlock({
  report,
  onExpand,
}: {
  report: Report
  onExpand: (kind: ReportKind) => void
}) {
  const rows = report.bars.slice(0, 3)
  const items = rows.length ? [] : report.top.slice(0, 3)
  return (
    <div className={BLOCK}>
      <div className="flex flex-wrap items-center gap-2.5 border-b border-hair px-4 py-3">
        <span className="inline-flex h-[22px] shrink-0 items-center rounded-md bg-blue-deep px-2 text-[11px] font-bold uppercase tracking-[0.06em] text-bg">
          iiko
        </span>
        <p className="min-w-0 flex-1 truncate text-[15px] font-semibold text-text">
          {report.title} · {report.subtitle.split(' · ')[0]}
        </p>
        <button
          type="button"
          onClick={() => onExpand(report.kind)}
          className="shrink-0 text-[14px] font-semibold text-amber hover:opacity-80"
        >
          Развернуть отчёт →
        </button>
      </div>
      <ul className="px-4 py-1">
        {rows.map((b, i) => (
          <li
            key={b.name}
            className={cn(
              'flex min-h-[38px] items-center gap-2.5',
              i > 0 && 'border-t border-hair',
            )}
          >
            <span className="min-w-0 flex-1 truncate text-[15px] text-text">{b.name}</span>
            <span className="shrink-0 font-mono text-[14px] font-semibold text-text">
              {b.sum}
            </span>
            <span
              className={cn(
                'w-14 shrink-0 text-right font-mono text-[14px] font-semibold',
                b.up ? 'text-green-deep' : 'text-text2',
              )}
            >
              {b.delta}
            </span>
          </li>
        ))}
        {items.map((t, i) => (
          <li
            key={t.name}
            className={cn(
              'flex min-h-[38px] items-center gap-2.5',
              i > 0 && 'border-t border-hair',
            )}
          >
            <span className="min-w-0 flex-1 truncate text-[15px] text-text">{t.name}</span>
            <span className="shrink-0 font-mono text-[14px] font-semibold text-text">
              {t.share}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}
