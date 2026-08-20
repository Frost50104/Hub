import { Copy } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/Button'
import { CreateTaskDialog } from '@/components/task/CreateTaskDialog'
import { plural } from '@/lib/typography'
import { type TurnData } from '@/lib/assistant'

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
  onRetry,
}: {
  content: string
  onRetry: () => void
}) {
  return (
    <div className={BLOCK}>
      <div className="px-4 py-3.5">
        <p className="text-[15px] leading-[1.5] text-text2">{content}</p>
        <Button size="sm" variant="secondary" className="mt-3" onClick={onRetry}>
          Повторить
        </Button>
      </div>
    </div>
  )
}
