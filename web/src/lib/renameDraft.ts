/**
 * Правка имени на месте — общее правило для папки проектов и колонки доски.
 *
 * Обе поверхности коммитят по Enter И по blur, а blur случается на каждом
 * клике мимо: без этой проверки уход фокуса слал бы PATCH с тем же именем
 * (лишний запрос, лишняя запись в ленте, лишний рефетч списка).
 */

/** Имя для PATCH или null, если запрос слать незачем. */
export function nextName(draft: string, current: string): string | null {
  const name = draft.trim()
  if (!name || name === current.trim()) return null
  return name
}
