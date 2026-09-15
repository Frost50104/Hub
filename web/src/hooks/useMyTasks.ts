import { useQuery, type UseQueryResult } from '@tanstack/react-query'

import { api } from '@/lib/api'
import { type Task } from '@/lib/tasks'

export type DueWindow = 'overdue' | 'today' | 'upcoming' | 'all'

export interface MyTasksFilters {
  /** `false` — невыполненные, `true` — выполненные, отсутствие — все. */
  done?: boolean
  due_window?: DueWindow
  include_archived?: boolean
}

/**
 * Кросс-проектный список «моего»: назначенное мне И мои личные задачи.
 *
 * Клиентской страховки `excludeProject` здесь больше нет (16.09). Она вырезала
 * личные задачи из окон дедлайнов, пока те стояли на экране отдельной секцией
 * «ЛИЧНОЕ» и строка иначе оказалась бы на экране дважды. Секции нет, личные —
 * часть списка, и фильтр теперь прятал бы ровно то, ради чего всё затевалось.
 *
 * `include_personal` не шлём: серверный дефолт с 16.09 `true`. Явный параметр в
 * queryKey развёл бы кэш «Главной» и `/my` на два запроса одного и того же.
 */
export function useMyTasks(filters: MyTasksFilters = {}): UseQueryResult<Task[]> {
  return useQuery({
    queryKey: ['me-tasks', filters],
    queryFn: () =>
      api.get<Task[]>('/me/tasks', { params: filters }).then((r) => r.data),
  })
}
