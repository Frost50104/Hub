import { EmptyState } from '@/components/ui/EmptyState'

/**
 * Пустые состояния списка и доски — обёртка над общим `EmptyState`
 * (`components/ui/EmptyState.tsx`): силуэт один на трекер и обучение.
 * Оставлена, чтобы не трогать 11 точек вызова.
 */
export function TaskEmptyState({
  title,
  text,
  cta,
  onCta,
  secondaryCta,
  onSecondary,
  tone = 'neutral',
  meta,
}: {
  title: string
  text: string
  cta?: string
  onCta?: () => void
  /** Точечное действие рядом с общим — например «снять приоритет». */
  secondaryCta?: string
  onSecondary?: () => void
  tone?: 'neutral' | 'error'
  /** «Последние данные — 3 минуты назад». */
  meta?: React.ReactNode
}) {
  return (
    <EmptyState
      title={title}
      text={text}
      cta={cta}
      onCta={onCta}
      secondaryCta={secondaryCta}
      onSecondary={onSecondary}
      tone={tone}
      meta={meta}
    />
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
