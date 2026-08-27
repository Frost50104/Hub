import { Star } from 'lucide-react'

import { useFavoriteIds, useToggleFavorite } from '@/hooks/useLearn'
import { useMe } from '@/hooks/useMe'
import { cn } from '@/lib/cn'
import { isFavorite } from '@/lib/favorites'

/**
 * Звезда «в избранное» — одна на библиотеку, курсы и ассортимент.
 *
 * Две вещи, которые нельзя потерять при переносе в другой список:
 *
 * 1. **Звезды нет у того, у кого нет учебного профиля.** Избранное ключуется
 *    `employee_profiles.id`, и `toggle` без профиля отвечает 404: кнопка была
 *    бы кнопкой, которая всегда ломается. На проде такие сотрудники есть.
 * 2. **`preventDefault` + `stopPropagation` обязательны.** Строка списка —
 *    ссылка или кнопка целиком; без остановки события клик по звезде уводил бы
 *    на курс или открывал карточку.
 */
export function FavoriteStar({
  objectType,
  objectId,
  title,
  className,
}: {
  objectType: string
  objectId: string
  /** Название объекта — только для подписи кнопки в скринридере. */
  title: string
  className?: string
}) {
  const me = useMe()
  const hasProfile = Boolean(me.data?.profile)
  const favorites = useFavoriteIds(hasProfile)
  const toggle = useToggleFavorite()

  if (!hasProfile) return null

  const active = isFavorite(favorites.data, objectType, objectId)
  return (
    <button
      type="button"
      aria-pressed={active}
      title={active ? 'Убрать из избранного' : 'В избранное'}
      aria-label={`${active ? 'Убрать из избранного' : 'В избранное'}: ${title}`}
      onClick={(e) => {
        e.preventDefault()
        e.stopPropagation()
        toggle.mutate({ objectType, objectId })
      }}
      className={cn(
        'flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-text3 transition-colors hover:bg-glass hover:text-amber',
        active && 'text-amber',
        className,
      )}
    >
      <Star className={cn('h-4 w-4', active && 'fill-amber')} strokeWidth={1.9} />
    </button>
  )
}
