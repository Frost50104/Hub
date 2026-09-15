/**
 * Группировка «Моих задач» по срокам.
 *
 * Вынесена из `MyTasksPage.tsx` в чистый модуль (ОС 15.09): jsdom в проекте
 * нет, и тестом можно накрыть только функцию — а правило «бессрочные идут
 * последней группой, а не пропадают» стоит того, чтобы его зафиксировать.
 *
 * Ключи дней — display tz (`lib/taskDates`), та же семантика, что у окон
 * сервера: день срока, а не мгновение.
 */

import { addDaysKey, dayKey, todayKey } from '@/lib/taskDates'
import { type Task } from '@/lib/tasks'

export type GroupKey = 'overdue' | 'today' | 'week' | 'later' | 'nodate'

export const GROUP_LABEL: Record<GroupKey, string> = {
  overdue: 'Просрочено',
  today: 'Сегодня',
  week: 'Ближайшая неделя',
  later: 'Позже',
  nodate: 'Без срока',
}

export const GROUP_ORDER: GroupKey[] = ['overdue', 'today', 'week', 'later', 'nodate']

/** В какую группу попадает задача. Отдельно от раскладки — ради теста. */
export function groupKeyFor(task: Pick<Task, 'due_at' | 'done'>, today: string): GroupKey {
  if (!task.due_at) return 'nodate'
  const day = dayKey(task.due_at)
  // Выполненные задачи не считаем просроченными — оставляем в своей дате.
  if (day < today && !task.done) return 'overdue'
  if (day <= today) return 'today'
  if (day <= addDaysKey(today, 7)) return 'week'
  return 'later'
}

export function groupTasksByDue<T extends Pick<Task, 'due_at' | 'done'>>(
  tasks: readonly T[],
): { key: GroupKey; items: T[] }[] {
  const today = todayKey()
  const buckets = new Map<GroupKey, T[]>(GROUP_ORDER.map((k) => [k, []]))
  for (const task of tasks) buckets.get(groupKeyFor(task, today))!.push(task)
  return GROUP_ORDER.map((key) => ({ key, items: buckets.get(key)! }))
}
