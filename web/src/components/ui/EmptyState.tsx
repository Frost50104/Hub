import { CircleAlert, ListTree } from 'lucide-react'
import { type ReactNode } from 'react'

import { Button } from '@/components/ui/Button'
import { cn } from '@/lib/cn'

interface EmptyStateProps {
  title: string
  text?: ReactNode
  /** Своя иконка (42–52px отрисует контейнер). По умолчанию — дерево списка. */
  icon?: ReactNode
  cta?: string
  onCta?: () => void
  /** Точечное действие рядом с общим — например «снять приоритет». */
  secondaryCta?: string
  onSecondary?: () => void
  tone?: 'neutral' | 'error'
  /**
   * `panel` — растягивается на область (список, доска);
   * `card` — карточка `tint/r16` с большим отступом (/projects, Гант, дашборд).
   */
  layout?: 'panel' | 'card'
  /** Строка мелким под текстом: «Последние данные — 3 минуты назад». */
  meta?: ReactNode
  className?: string
}

/**
 * Пустое состояние — полноценный экран с одним действием, а не заглушка:
 * иконка, заголовок 20px, пояснение 16px, кнопка 48px. Ошибка отличается
 * только иконкой: красный — в ней и только в ней.
 */
export function EmptyState({
  title,
  text,
  icon,
  cta,
  onCta,
  secondaryCta,
  onSecondary,
  tone = 'neutral',
  layout = 'panel',
  meta,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center gap-4 text-center',
        layout === 'panel'
          ? 'flex-1 p-10'
          : 'rounded-2xl border border-glass-border bg-tint px-6 py-14',
        className,
      )}
    >
      {tone === 'error' ? (
        <span className="flex h-[52px] w-[52px] items-center justify-center rounded-full bg-red/[0.16] text-red">
          {icon ?? <CircleAlert className="h-6 w-6" strokeWidth={2} />}
        </span>
      ) : (
        <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-surface text-text2">
          {icon ?? <ListTree className="h-[26px] w-[26px]" strokeWidth={1.7} />}
        </span>
      )}
      <div className="flex max-w-[440px] flex-col gap-2">
        <h3 className="font-display text-[20px] font-bold leading-[1.25] text-text">
          {title}
        </h3>
        {text && (
          <p className="text-[16px] leading-[1.55] text-text2 [text-wrap:pretty]">{text}</p>
        )}
        {meta && <p className="text-[13px] text-text2">{meta}</p>}
      </div>
      {/* flex-wrap обязателен: то же пустое состояние рисуется в колонке
          доски шириной 288px, где две кнопки в один ряд не помещаются. */}
      {cta && onCta && (
        <div className="flex flex-wrap items-center justify-center gap-2">
          <Button size={layout === 'card' ? 'lg' : 'md'} onClick={onCta}>
            {cta}
          </Button>
          {secondaryCta && onSecondary && (
            <Button variant="ghost" size={layout === 'card' ? 'lg' : 'md'} onClick={onSecondary}>
              {secondaryCta}
            </Button>
          )}
        </div>
      )}
    </div>
  )
}
