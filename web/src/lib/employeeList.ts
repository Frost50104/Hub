/**
 * Полный список сотрудников: склейка страниц и честная подпись.
 *
 * ОС владельца 31.08: «в Сотрудниках видно не всех». `useEmployees` слал
 * `limit: 100`, на проде активных было 149 — сорок девять человек не
 * показывались нигде, а рядом стояло «Всего: 149». Тем же потолком были
 * обрезаны пикер руководителя, цели привязки в «Непривязанных входах» и состав
 * групп в оргструктуре.
 */

/** Максимум, который принимает ручка (`le=500` в `app/api/employees.py`). */
export const EMPLOYEE_PAGE_SIZE = 500
/** Жёсткий предел добора: 4 × 500 = 2000 человек. */
export const EMPLOYEE_MAX_PAGES = 4

export interface EmployeePage<T> {
  items: T[]
  total: number
}

/**
 * Добирает набор страницами до конца — или до предела.
 *
 * Останов ДВОЙНОЙ, и это не перестраховка: `while (собрано < total)` не
 * закончится никогда, если `total` окажется больше отдаваемого (гонка с
 * заведением сотрудника, скоуп, баг ручки) — вкладка просто зависнет. Поэтому
 * выходим и по короткой странице тоже.
 *
 * Дедупликация по `id`: между запросами набор может измениться и границы
 * страниц сдвинутся. `Map` сохраняет порядок первого появления, то есть
 * порядок сервера.
 */
export async function collectEmployees<T extends { id: string }>(
  fetchPage: (limit: number, offset: number) => Promise<EmployeePage<T>>,
): Promise<EmployeePage<T>> {
  const byId = new Map<string, T>()
  let total = 0
  for (let page = 0; page < EMPLOYEE_MAX_PAGES; page++) {
    const res = await fetchPage(EMPLOYEE_PAGE_SIZE, page * EMPLOYEE_PAGE_SIZE)
    total = res.total
    for (const item of res.items) byId.set(item.id, item)
    if (res.items.length < EMPLOYEE_PAGE_SIZE) break
    if (byId.size >= total) break
  }
  return { items: [...byId.values()], total }
}

/** Показали не всех — сработал предел добора. */
export function isTruncated(shown: number, total: number): boolean {
  return shown < total
}

/**
 * Подпись над списком «Сотрудники». Всегда что-то говорит: раньше здесь стояло
 * «Всего: N» над обрезанным списком, и экран противоречил сам себе.
 */
export function employeeListCaption(shown: number, total: number): string {
  return isTruncated(shown, total)
    ? `Показаны ${shown} из ${total} — уточните поиск, чтобы найти остальных`
    : `Всего: ${total}`
}

/**
 * То же правило для пикеров: там при полном списке подпись не нужна, а вот
 * молчаливая обрезка недопустима — выбрать невидимого человека нельзя.
 */
export function employeeTruncationNote(shown: number, total: number): string | null {
  return isTruncated(shown, total)
    ? `Показаны ${shown} из ${total} — уточните поиск`
    : null
}
