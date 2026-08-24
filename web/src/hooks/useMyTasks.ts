import { useQuery, type UseQueryResult } from '@tanstack/react-query'
import { useCallback } from 'react'

import { useMe } from '@/hooks/useMe'
import { api } from '@/lib/api'
import { excludeProject } from '@/lib/personalTasks'
import { type Task } from '@/lib/tasks'

export type DueWindow = 'overdue' | 'today' | 'upcoming' | 'all'

export interface MyTasksFilters {
  /** `false` — невыполненные, `true` — выполненные, отсутствие — все. */
  done?: boolean
  due_window?: DueWindow
  include_archived?: boolean
}

export function useMyTasks(filters: MyTasksFilters = {}): UseQueryResult<Task[]> {
  const personalId = useMe().data?.personal_project_id ?? null
  // Личные задачи живут в своей секции — в окнах дедлайнов они были бы вторым
  // экземпляром той же строки. Основной фильтр серверный
  // (`include_personal=false`), это страховка на окно деплоя.
  //
  // `select` не входит в queryKey: в кэше остаются серверные данные, поэтому
  // оптимистика useUpdateTask (setQueriesData(['me-tasks'])) и откат работают
  // как раньше. useCallback обязателен — TanStack пере-вычисляет select при
  // смене идентичности функции.
  const select = useCallback(
    (tasks: Task[]) => excludeProject(tasks, personalId),
    [personalId],
  )
  return useQuery({
    queryKey: ['me-tasks', filters],
    queryFn: () =>
      api.get<Task[]>('/me/tasks', { params: filters }).then((r) => r.data),
    select,
  })
}
