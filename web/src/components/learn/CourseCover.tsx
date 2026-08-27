import { BookOpen, ShieldCheck, TrendingUp } from 'lucide-react'

import { CoverTile } from '@/components/learn/CoverTile'
import { cn } from '@/lib/cn'
import { type CourseType } from '@/lib/learn'

/**
 * Обложка курса без единого ассета: фото курсов нет и не будет.
 *
 * Тон и иконка — от типа курса, паттерн — от индекса (шесть градиентов по
 * кругу), поэтому 18 курсов различимы на глаз. Сам рецепт плашки живёт в
 * `CoverTile`: тот же узор рисует «Новинки» на витрине, и разъезжаться им
 * незачем.
 *
 * Индекс берётся у КУРСА, а не у позиции в отфильтрованном списке: иначе
 * обложка менялась бы при переключении фильтра.
 */

const ICON: Record<CourseType, typeof BookOpen> = {
  mandatory: ShieldCheck,
  career: TrendingUp,
  recommended: TrendingUp,
  info: BookOpen,
}

// Плотная заливка, а не тинт: цветная иконка на тинте того же цвета давала
// 2,65:1 при норме 3:1 для значимых нетекстовых элементов.
//
// Карьерный — синий, а не зелёный: зелёная заливка зарезервирована за
// состоянием «пройдено», иначе тип курса и его состояние читаются одним
// цветом.
const TONE: Record<CourseType, string> = {
  mandatory: 'bg-amber text-on-amber',
  career: 'bg-blue-deep text-bg',
  recommended: 'bg-blue-deep text-bg',
  info: 'border border-hair bg-surface text-text2',
}

/**
 * Пройденное гасится СМЕНОЙ ПАРЫ, а не opacity: полупрозрачность душит
 * заливку и глиф вместе и роняет иконку до 2,4-2,7:1 при норме 3:1.
 * Нейтральная пара даёт 4,6:1 в обеих темах и читается как «убрано из
 * работы» — тип при этом опознаётся глифом и подписью.
 */
const MUTED_TONE = 'border border-hair bg-tint text-text2'

/** Бейдж типа курса. Тот же код цвета, что у обложки — один источник. */
export function courseTypeBadgeClass(courseType: CourseType, muted = false): string {
  const base =
    'inline-flex h-[19px] items-center rounded-[5px] px-1.5 text-[10px] font-bold uppercase tracking-[0.08em]'
  if (muted) return `${base} bg-surface text-text2`
  if (courseType === 'mandatory') return `${base} bg-amber text-on-amber`
  if (courseType === 'career' || courseType === 'recommended') {
    return `${base} bg-blue-deep text-bg`
  }
  return `${base} bg-surface text-text2`
}

export function CourseCover({
  courseType,
  index,
  muted,
  className,
}: {
  courseType: CourseType
  index: number
  /** Курс пройден — обложка уходит в нейтраль и перестаёт бороться за внимание. */
  muted?: boolean
  className?: string
}) {
  return (
    <CoverTile
      icon={ICON[courseType]}
      index={index}
      tone={muted ? MUTED_TONE : TONE[courseType]}
      className={cn('h-[60px] w-[60px] lg:h-[72px] lg:w-[72px]', className)}
    />
  )
}
