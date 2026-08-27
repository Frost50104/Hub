import { type LucideIcon } from 'lucide-react'

import { cn } from '@/lib/cn'

/**
 * Плашка вместо картинки: заливка + узор + глиф, без единого ассета.
 *
 * Рецепт написан ОДИН раз и на два места — обложка курса (`CourseCover`) и
 * карточки «Новинок» на витрине. До этого новинка без `image_url` (а сервер
 * заполняет его только товарам, `app/api/learn_home.py`) получала пустой серый
 * квадрат с иконкой 20px: документ, курс и новость выглядели одинаково никак.
 *
 * Узор выводится из `currentColor` через `color-mix` и работает в обеих темах
 * одним кодом; если браузер не знает `color-mix`, невалидным становится только
 * `background-image` — заливка и глиф остаются на месте.
 */

const PATTERNS = [
  'repeating-linear-gradient(45deg, PP 0 2px, transparent 2px 9px)',
  'radial-gradient(PP 1.2px, transparent 1.5px)',
  'repeating-linear-gradient(135deg, PP 0 1px, transparent 1px 6px)',
  'repeating-radial-gradient(circle at 25% 115%, PP 0 1px, transparent 1px 10px)',
  'repeating-linear-gradient(0deg, PP 0 1px, transparent 1px 8px), repeating-linear-gradient(90deg, PP 0 1px, transparent 1px 8px)',
  'linear-gradient(135deg, PP 0 46%, transparent 46%)',
]

const PATTERN_INK = 'color-mix(in srgb, currentColor 18%, transparent)'

/** Сколько всего узоров — потребителям нужно, чтобы разводить соседей. */
export const COVER_PATTERN_COUNT = PATTERNS.length

export function CoverTile({
  icon: Icon,
  index,
  tone,
  className,
  iconClassName,
}: {
  icon: LucideIcon
  /** Номер узора; берётся у объекта, а не у позиции в отфильтрованном списке. */
  index: number
  /** Пара «фон + цвет глифа» классами — цвет здесь несёт смысл, не украшает. */
  tone: string
  className?: string
  iconClassName?: string
}) {
  const pattern = PATTERNS[index % PATTERNS.length]!.replaceAll('PP', PATTERN_INK)
  return (
    <span
      aria-hidden
      className={cn('flex shrink-0 items-center justify-center rounded-xl', tone, className)}
      style={{ backgroundImage: pattern, backgroundSize: '9px 9px' }}
    >
      <Icon className={cn('h-6 w-6', iconClassName)} strokeWidth={1.9} />
    </span>
  )
}
