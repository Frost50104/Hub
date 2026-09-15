import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from '@tanstack/react-query'

import { api } from '@/lib/api'
import { type Task } from '@/lib/tasks'

/**
 * Поручение задачи ЛИЧНО человеку и секция «Я поставил».
 *
 * Отдельная ручка, а не `POST /projects/{id}/tasks`: чужой личный проект
 * клиенту неизвестен (в `GET /projects` личных нет ни у кого), да и знать его
 * не нужно — адресуем человеком, проект резолвит сервер.
 */
export interface DelegateBody {
  employee_id: string
  title: string
  description?: string
  due_at?: string | null
}

/** Что я положил людям в личное и это ещё не закрыто. */
export function useDelegated(): UseQueryResult<Task[]> {
  return useQuery({
    queryKey: ['me-delegated'],
    queryFn: () => api.get<Task[]>('/me/delegated').then((r) => r.data),
  })
}

export function useDelegateTask() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: DelegateBody) =>
      api.post<Task>('/me/delegate', body).then((r) => r.data),
    onSuccess: () => {
      // Только своя секция: в `me-tasks` поручение не попадает — автор там не
      // исполнитель, а получателю оно приедет его же запросом.
      void qc.invalidateQueries({ queryKey: ['me-delegated'] })
    },
  })
}
