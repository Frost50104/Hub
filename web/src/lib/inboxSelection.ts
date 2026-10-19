/**
 * Режим выбора во «Входящих»: множество выбранных id и подписи панели.
 *
 * Чистые функции — `pages/InboxPage.tsx` только рисует. Выбор — локальное
 * состояние страницы, живёт до «Отмены», отметки или смены чипа
 * «Все / Непрочитанные» (окна выборки разные, id из одного нельзя слать как
 * выбор другого).
 */

import { plural } from './typography'

/**
 * Потолок id в одном `POST /notifications/read-state` — зеркало
 * `app/schemas/notification.py::READ_STATE_MAX_IDS`, меняется ПАРОЙ; сторож —
 * `tests/unit/test_notification_schemas.py`. Больший выбор клиент режет
 * чанками (`chunkIds`).
 */
export const READ_STATE_MAX = 500

export function toggleId(set: ReadonlySet<number>, id: number): Set<number> {
  const next = new Set(set)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  return next
}

export function allIds(items: readonly { id: number }[]): Set<number> {
  return new Set(items.map((n) => n.id))
}

/**
 * Выбор переживает фоновый перезапрос только пересечением с загруженным:
 * строка, прочитанная с другого устройства, уходит из «Непрочитанных» при
 * фокусе окна, и слать её id серверу незачем. Производное состояние, не
 * синхронизируемое: считается на каждом рендере от `picked` и `items`.
 */
export function pruneSelection(
  set: ReadonlySet<number>,
  items: readonly { id: number }[],
): Set<number> {
  const loaded = allIds(items)
  return new Set([...set].filter((id) => loaded.has(id)))
}

export function chunkIds(ids: readonly number[], size = READ_STATE_MAX): number[][] {
  const chunks: number[][] = []
  for (let i = 0; i < ids.length; i += size) chunks.push(ids.slice(i, i + size))
  return chunks
}

export function selectionLabel(count: number): string {
  return count > 0 ? `Выбрано ${count}` : 'Ничего не выбрано'
}

/** Число в подписи и есть ответ на «все — это какие»: все ЗАГРУЖЕННЫЕ. */
export function selectAllLabel(loaded: number, allSelected: boolean): string {
  return allSelected ? 'Снять выбор' : `Выбрать все (${loaded})`
}

/** Тост после массовой отметки — по числу РЕАЛЬНО изменённых строк от сервера. */
export function bulkReadToast(updated: number, isRead: boolean): string {
  if (updated === 0) {
    return isRead ? 'Все выбранные уже прочитаны' : 'Все выбранные уже непрочитаны'
  }
  const n = plural(updated, 'уведомление', 'уведомления', 'уведомлений')
  return isRead ? `Прочитано ${n}` : `Отмечено как непрочитанное: ${n}`
}
