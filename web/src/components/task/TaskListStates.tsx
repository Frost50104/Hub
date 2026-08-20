import { CircleAlert, ListTree } from 'lucide-react'

import { Button } from '@/components/ui/Button'

/**
 * Пустые состояния списка и доски. Пустое и почти пустое — сегодняшний
 * основной режим трекера (семь проектов, из них живой один), поэтому это
 * полноценные экраны с одним действием, а не заглушки.
 */
export function TaskEmptyState({
  title,
  text,
  cta,
  onCta,
  secondaryCta,
  onSecondary,
  tone = 'neutral',
}: {
  title: string
  text: string
  cta?: string
  onCta?: () => void
  /** Точечное действие рядом с общим — например «снять приоритет». */
  secondaryCta?: string
  onSecondary?: () => void
  tone?: 'neutral' | 'error'
}) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-4 p-10 text-center">
      {tone === 'error' ? (
        <span className="flex h-[52px] w-[52px] items-center justify-center rounded-full bg-red/[0.16] text-red">
          <CircleAlert className="h-6 w-6" strokeWidth={2} />
        </span>
      ) : (
        <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-surface text-text2">
          <ListTree className="h-[26px] w-[26px]" strokeWidth={1.7} />
        </span>
      )}
      <div className="flex max-w-[440px] flex-col gap-2">
        <h3 className="font-display text-[20px] font-bold leading-[1.25] text-text">
          {title}
        </h3>
        <p className="text-[16px] leading-[1.55] text-text2 [text-wrap:pretty]">{text}</p>
      </div>
      {/* flex-wrap обязателен: то же пустое состояние рисуется в колонке
          доски шириной 288px, где две кнопки в один ряд не помещаются. */}
      {cta && onCta && (
        <div className="flex flex-wrap items-center justify-center gap-2">
          <Button onClick={onCta}>{cta}</Button>
          {secondaryCta && onSecondary && (
            <Button variant="ghost" onClick={onSecondary}>
              {secondaryCta}
            </Button>
          )}
        </div>
      )}
    </div>
  )
}

/**
 * Скелетон списка: те же 64px и та же сетка, что у настоящих строк, ширины
 * плейсхолдеров чередуются, анимации нет — мигание на длинном списке утомляет
 * сильнее, чем ожидание.
 */
const SKELETON_WIDTHS = [88, 64, 76, 52, 84, 60, 72, 48, 80]

export function TaskListSkeleton({ compact = false }: { compact?: boolean }) {
  return (
    <div aria-hidden className={compact ? 'px-4' : 'px-6'}>
      {SKELETON_WIDTHS.map((w, i) => (
        <div key={i} className="flex h-16 items-center gap-3 border-b border-hair">
          <span className="h-5 w-5 shrink-0 rounded-full bg-surface" />
          <span className="flex min-w-0 flex-1 flex-col gap-[7px]">
            <span
              className="h-3.5 rounded-[5px] bg-surface"
              style={{ width: `${w}%` }}
            />
            <span className="h-[11px] w-[120px] rounded bg-surface" />
          </span>
          <span className="h-6 w-6 shrink-0 rounded-full bg-surface" />
          <span className="h-3 w-[52px] shrink-0 rounded bg-surface" />
        </div>
      ))}
    </div>
  )
}
