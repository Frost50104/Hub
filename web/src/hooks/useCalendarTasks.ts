import { useQuery, type UseQueryResult } from '@tanstack/react-query'

import { tasksApi, type CalendarFilters, type Task } from '@/lib/tasks'

export const calendarKeys = {
  range: (projectId: string, from: string, to: string, filters?: CalendarFilters) =>
    ['tasks', projectId, 'calendar', from, to, filters ?? {}] as const,
}

/**
 * Fetch every task whose [start_at, due_at] interval overlaps the visible
 * month grid (six rows × seven days = up to 42 cells). The backend window
 * is inclusive on both ends so the boundaries align with `toLocaleDateString`
 * on the client.
 */
export function useCalendarTasks(
  projectId: string | undefined,
  from: string,
  to: string,
  filters?: CalendarFilters,
): UseQueryResult<Task[]> {
  return useQuery({
    queryKey: projectId
      ? calendarKeys.range(projectId, from, to, filters)
      : ['tasks', 'none', 'calendar', from, to],
    queryFn: () => tasksApi.calendar(projectId!, { from, to }, filters),
    enabled: !!projectId,
    staleTime: 30_000,
  })
}
