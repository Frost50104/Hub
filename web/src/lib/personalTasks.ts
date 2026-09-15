/**
 * Вкладка «Личные» на «Моих задачах»: разбор списка без React.
 *
 * Компонент остаётся раскладкой — соглашение проекта (эталон пары
 * `inlineDraft.ts` ↔ `TaskInlineCreate.tsx`): jsdom в проекте нет, тестируются
 * только чистые функции.
 *
 * Здесь осталась одна функция. `excludeProject` (страховка «личные не
 * дублируются в окнах»), `resolvePersonalTaskParam` (гвард `?task=`) и
 * `personalSectionState` ушли вместе с секцией «ЛИЧНОЕ» 16.09: личные задачи
 * теперь часть общего списка, а карточка открывается по id отдельным запросом
 * и списка не ждёт.
 */

import { type SubtaskStats, type Task } from './tasks'

/** Сколько выполненных личных задач показываем без «показать все». */
export const DONE_PREVIEW_LIMIT = 3

export interface PersonalListView<T> {
  /** Верхнеуровневые незавершённые, в порядке ответа сервера. */
  open: T[]
  /** Выполненные, обрезанные до лимита. */
  done: T[]
  /** Сколько выполненных скрыто за «Показать все выполненные». */
  hiddenDone: number
  /** Для шапки: «3 · 1 выполнено». */
  counts: { open: number; done: number }
  /** Чип «k/N» у родителя: подзадачи приезжают тем же ответом. */
  subtasksByParent: Map<string, SubtaskStats>
}

/**
 * Разложить ответ `GET /projects/{personal}/tasks` в то, что рисует вкладка.
 *
 * Подзадачи в строки не попадают (как на странице проекта), но считаются в чип
 * родителя. Выполненные тонут вниз и по умолчанию урезаются: личный список —
 * это inbox, за полгода под инпутом накопилась бы стена «Готово». Сколько
 * именно показывать, решает вызывающий: вкладка «Личные» передаёт `doneLimit: 0`
 * и раскрывает их чипом.
 */
export function personalListView<
  T extends Pick<Task, 'id' | 'done' | 'parent_task_id'>,
>(
  tasks: readonly T[] | undefined,
  opts: { doneLimit?: number; showAllDone?: boolean } = {},
): PersonalListView<T> {
  const { doneLimit = DONE_PREVIEW_LIMIT, showAllDone = false } = opts
  const open: T[] = []
  const done: T[] = []
  const subtasksByParent = new Map<string, SubtaskStats>()

  for (const task of tasks ?? []) {
    if (task.parent_task_id) {
      const stats = subtasksByParent.get(task.parent_task_id) ?? { total: 0, done: 0 }
      stats.total += 1
      if (task.done) stats.done += 1
      subtasksByParent.set(task.parent_task_id, stats)
      continue
    }
    ;(task.done ? done : open).push(task)
  }

  const shown = showAllDone ? done : done.slice(0, doneLimit)
  return {
    open,
    done: shown,
    hiddenDone: done.length - shown.length,
    counts: { open: open.length, done: done.length },
    subtasksByParent,
  }
}
