/**
 * Избранное: ключ объекта и работа с набором ключей.
 *
 * Сервер отдаёт плоский список строк «тип:id» (`GET /learn/favorites/ids`), а
 * не полноценные объекты: подсветка звезды не должна зависеть ни от лимита
 * списка, ни от того, лежит ли объект в индексе публикаций. Склейка ключа
 * живёт ЗДЕСЬ и нигде больше — три списка (библиотека, курсы, ассортимент)
 * обязаны спрашивать одно и то же.
 */

/** Типы, которые сервер принимает в `toggle` (`FAVORITE_TYPES` в модели). */
export const FAVORITE_TYPES = ['library_material', 'news_post', 'course', 'product'] as const

export type FavoriteType = (typeof FAVORITE_TYPES)[number]

export function favoriteKey(objectType: string, objectId: string): string {
  return `${objectType}:${objectId}`
}

export function isFavorite(
  keys: ReadonlySet<string> | undefined,
  objectType: string,
  objectId: string,
): boolean {
  return keys?.has(favoriteKey(objectType, objectId)) ?? false
}

/**
 * Набор после переключения — для оптимистичного отклика.
 *
 * Возвращает НОВЫЙ Set: TanStack Query сравнивает данные по ссылке, и мутация
 * на месте не перерисовала бы звезду до ответа сервера.
 */
export function toggleFavoriteKey(
  keys: ReadonlySet<string>,
  objectType: string,
  objectId: string,
): Set<string> {
  const key = favoriteKey(objectType, objectId)
  const next = new Set(keys)
  if (!next.delete(key)) next.add(key)
  return next
}

/** Подпись типа в списке избранного — иначе три документа подряд неразличимы. */
export const FAVORITE_TYPE_LABEL: Record<string, string> = {
  library_material: 'Документ',
  news_post: 'Новость',
  course: 'Курс',
  product: 'Товар',
}

/**
 * Фильтры экрана избранного строятся по РЕАЛЬНОМУ составу, а не по всем
 * четырём типам: чип «Курсы», не находящий ни одного курса, — обещание, что
 * там что-то есть.
 */
export function favoriteTypesPresent(items: readonly { object_type: string }[]): string[] {
  const seen = new Set<string>()
  for (const item of items) seen.add(item.object_type)
  return FAVORITE_TYPES.filter((t) => seen.has(t))
}
