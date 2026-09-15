import { useMutation, useQueryClient } from '@tanstack/react-query'

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

export function useDelegateTask() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: DelegateBody) =>
      api.post<Task>('/me/delegate', body).then((r) => r.data),
    onSuccess: () => {
      // Только своя вкладка: в `me-tasks` поручение не попадает — автор там не
      // исполнитель, а получателю оно приедет его же запросом.
      void qc.invalidateQueries({ queryKey: ['me-assigned-by-me'] })
    },
  })
}
