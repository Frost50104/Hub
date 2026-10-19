/**
 * Страницы «Входящих» — чистая арифметика поверх голого списка ручки.
 *
 * `GET /api/notifications` отдаёт массив без `has_more` и `total`. Правило
 * «страница полная ⇒ есть ещё» врёт, когда осталось ровно 50: «Показать ещё»
 * приносила бы пустую страницу. Поэтому просим на одну строку больше
 * (`INBOX_FETCH_LIMIT`): 51-я — признак следующей страницы, в список она не
 * попадает, курсор — id последней ПОКАЗАННОЙ строки (50-й). Сервер сортирует
 * и режет по `id` (`api/notifications.py`), так что курсор по `id` не даёт ни
 * пропусков, ни дублей.
 *
 * Дедуп по `id` — страховка на стыке страниц: `fetchNextPage` по умолчанию
 * обрывает фоновый перезапрос и берёт курсор из устаревшей страницы (образец —
 * `lib/employeeList.ts`). Вся логика здесь, а не в JSX, — чтобы vitest без
 * jsdom проверял границы.
 */

import type { Notification } from './notifications'

export const INBOX_PAGE_SIZE = 50
export const INBOX_FETCH_LIMIT = INBOX_PAGE_SIZE + 1

/** Строки страницы без 51-й — она только сигнал. */
export function pageItems<T>(page: readonly T[]): T[] {
  return page.slice(0, INBOX_PAGE_SIZE)
}

/** Курсор следующей страницы или `undefined`, когда страница последняя. */
export function pageCursor(page: readonly { id: number }[]): number | undefined {
  return page.length > INBOX_PAGE_SIZE ? page[INBOX_PAGE_SIZE - 1]?.id : undefined
}

/** Все загруженные строки в порядке сервера, каждая один раз. */
export function flattenPages<T extends { id: number }>(
  pages: readonly (readonly T[])[],
): T[] {
  const byId = new Map<number, T>()
  for (const page of pages) {
    for (const n of pageItems(page)) {
      if (!byId.has(n.id)) byId.set(n.id, n)
    }
  }
  return [...byId.values()]
}

export const WEEK_MS = 7 * 24 * 60 * 60 * 1000

export interface AgeGroup<T> {
  key: '7d' | 'older'
  label: string
  items: T[]
}

/**
 * Группы «Последние 7 дней / Раньше» — подписи списка, а НЕ фильтр: именно
 * заголовок «Последние 7 дней» над усечёнными до 50 строками читался как
 * «показываем только неделю» (заявка 19.10). Граница считается построчно по
 * `created_at`, поэтому порядок строк на неё не влияет.
 */
export function bucketByAge<T extends Pick<Notification, 'created_at'>>(
  items: readonly T[],
  now: number,
): AgeGroup<T>[] {
  const recent: T[] = []
  const older: T[] = []
  for (const n of items) {
    ;(now - Date.parse(n.created_at) <= WEEK_MS ? recent : older).push(n)
  }
  return [
    { key: '7d', label: 'Последние 7 дней', items: recent },
    { key: 'older', label: 'Раньше', items: older },
  ]
}
