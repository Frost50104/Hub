/**
 * Какие ключи TanStack Query принадлежат конкретному проекту.
 *
 * Нужен ровно в одном месте — после удаления проекта: пережившие запросы
 * перерисовали бы мёртвые данные. Правило «сносим всё, где встречается id»
 * имеет исключения, поэтому оно вынесено сюда под тест, а не размазано
 * списком литералов по хуку.
 *
 * Ключи-источники: hooks/useProjects.ts, useTasks.ts, useCalendarTasks.ts,
 * useStages.ts, useLabels.ts, useCustomFields.ts, useProjectStats.ts,
 * useTimeline.ts. При добавлении нового проектного запроса — сюда же и в тест.
 */

/** Корни, у которых projectId стоит вторым элементом: ['корень', id, …]. */
const SECOND_POSITION = ['projects', 'tasks', 'stages', 'labels', 'stats', 'timeline']
/** Корни, у которых projectId стоит третьим: ['custom-fields', 'defs', id]. */
const THIRD_POSITION = ['custom-fields']

export function isProjectScopedQueryKey(key: readonly unknown[], projectId: string): boolean {
  const [root, second, third] = key
  if (typeof root !== 'string') return false
  if (SECOND_POSITION.includes(root)) {
    // ['projects', { includeArchived }] — это СПИСОК, а не проект. Его
    // инвалидируют, а не сносят: он обязан перезапроситься без удалённого.
    return second === projectId
  }
  if (THIRD_POSITION.includes(root)) return third === projectId
  return false
}
