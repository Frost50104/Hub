import { type UseQueryResult } from '@tanstack/react-query'

import { useMe } from '@/hooks/useMe'
import { useTasks } from '@/hooks/useTasks'
import { type Task } from '@/lib/tasks'

export interface PersonalTasksResult {
  /** id личного проекта; undefined — /me ещё грузится ИЛИ бэкенд поля не отдал. */
  projectId: string | undefined
  /** Тот же кэш `['tasks', projectId, {}]`, что у страницы проекта. */
  query: UseQueryResult<Task[]>
  meIsPending: boolean
}

/**
 * Личные задачи = обычный список задач скрытого проекта «Личное».
 *
 * Намеренно `useTasks`, а не свой queryKey: по ключу `['tasks', projectId]`
 * уже бьют инвалидации шести существующих мутаций и оптимистика
 * `useUpdateTask` — включая те, что дёргает карточка задачи. Свой ключ
 * пришлось бы синхронизировать с ними вечно.
 *
 * `enabled: !!projectId` внутри useTasks даёт бесплатный guard на старый
 * бэкенд: без `personal_project_id` запрос не уходит.
 */
export function usePersonalTasks(): PersonalTasksResult {
  const me = useMe()
  const projectId = me.data?.personal_project_id ?? undefined
  return { projectId, query: useTasks(projectId), meIsPending: me.isPending }
}
