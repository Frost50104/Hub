/** Даты в строках и карточках задач — один формат на все представления. */

/** «16 авг» — без точки после месяца: ru-RU short даёт «16 авг.». */
export function shortDate(iso: string): string {
  return new Date(iso)
    .toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })
    .replace('.', '')
}

/**
 * Просрочена ли задача. Готовые не считаются просроченными никогда — иначе
 * закрытая с опозданием задача навсегда осталась бы красной.
 */
export function isOverdue(
  due: string | null,
  status: string,
  now: number = Date.now(),
): boolean {
  return !!due && status !== 'done' && new Date(due).getTime() < now
}

/** «просрочено на 4 дня» для карточки задачи. */
export function overdueDays(due: string, now: number = Date.now()): number {
  const day = 24 * 60 * 60 * 1000
  return Math.max(1, Math.floor((now - new Date(due).getTime()) / day))
}
