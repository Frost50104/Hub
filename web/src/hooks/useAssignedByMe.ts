import { useQuery, type UseQueryResult } from '@tanstack/react-query'

import { api } from '@/lib/api'
import { type Task } from '@/lib/tasks'

/**
 * «Назначенные мной» — что я поручил другим, по всем проектам.
 *
 * Поглощает прежнюю секцию «Я поставил» (`GET /me/delegated`), которая видела
 * только поручения в чужое личное: на проде это 2 задачи из 37.
 *
 * Выполненные не показываем (`done=false` на сервере по умолчанию): вкладка —
 * про «за кем числится», а не про историю. Закрытая исполнителем задача уходит
 * отсюда сама.
 */
export function useAssignedByMe(): UseQueryResult<Task[]> {
  return useQuery({
    queryKey: ['me-assigned-by-me'],
    queryFn: () => api.get<Task[]>('/me/assigned-by-me').then((r) => r.data),
  })
}
