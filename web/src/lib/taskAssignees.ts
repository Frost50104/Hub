import { type Task, type TaskAssigneeBrief } from './tasks'

/**
 * Исполнители задачи с фолбэком на легаси-поле.
 *
 * ЕДИНСТВЕННЫЙ способ читать исполнителей в UI: прямое `task.assignees.map()`
 * упадёт на объекте из react-query-кэша, пережившего деплой, и на ответе
 * откаченного бэкенда, где поля ещё нет.
 *
 * Отдельный модуль (а не `tasks.ts`), потому что импорт из `tasks.ts` тянет
 * `api` → `auth` → `window`, а vitest в проекте бежит без jsdom. Здесь —
 * только type-only импорт, он стирается при компиляции.
 */
export function taskAssignees(t: Task): TaskAssigneeBrief[] {
  return t.assignees ?? (t.assignee ? [t.assignee] : [])
}
