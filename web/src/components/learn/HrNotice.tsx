import { Info } from 'lucide-react'

import { cn } from '@/lib/cn'
import { hrLineText, type HrView } from '@/lib/hrLock'

/**
 * Одна строка над кадровыми полями (решение владельца 25.09: поля видны, но
 * неактивны, а строка говорит, где их править). Оформление — как у
 * `TemplateBanner`: значок `blue-deep` — нейтрально-информативное, текст
 * `text2`, ничего мельче 12px. Ссылка — в новой вкладке: auth — другой сайт.
 *
 * Текст зависит от состояния: «заморожено, но не обновляется» маскировать под
 * обычное нельзя — человек должен знать, что правка из auth в Hub не придёт.
 */
export function HrNotice({
  view,
  href,
  text: override,
  className,
}: {
  view: HrView
  /** Куда вести: карточки — `edit_url`, справочники — `org_url`. */
  href?: string
  /** Свой текст вместо текста состояния (плашка справочника). */
  text?: string
  className?: string
}) {
  const line = hrLineText(view)
  return (
    <div
      className={cn(
        'flex items-start gap-2 rounded-lg border border-hair bg-tint px-3 py-2',
        className,
      )}
    >
      <Info className="mt-0.5 h-4 w-4 shrink-0 text-blue-deep" strokeWidth={1.8} />
      <p className="min-w-0 text-xs leading-[1.5] text-text2">
        {view.state === 'synced' && override ? override : line.text}
        {' · '}
        <a
          href={href ?? view.edit_url}
          target="_blank"
          rel="noopener noreferrer"
          className="whitespace-nowrap text-amber hover:underline"
        >
          Открыть в auth →
        </a>
        {line.updated && <span className="text-text3"> · {line.updated}</span>}
      </p>
    </div>
  )
}
