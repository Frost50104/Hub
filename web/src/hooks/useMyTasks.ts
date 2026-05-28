import { useQuery, type UseQueryResult } from '@tanstack/react-query'

import { api } from '@/lib/api'
import { type Task, type TaskStatus } from '@/lib/tasks'

export type DueWindow = 'overdue' | 'today' | 'upcoming' | 'all'

export interface MyTasksFilters {
  status?: TaskStatus
  due_window?: DueWindow
  include_archived?: boolean
}

export function useMyTasks(filters: MyTasksFilters = {}): UseQueryResult<Task[]> {
  return useQuery({
    queryKey: ['me-tasks', filters],
    queryFn: () =>
      api.get<Task[]>('/me/tasks', { params: filters }).then((r) => r.data),
  })
}
