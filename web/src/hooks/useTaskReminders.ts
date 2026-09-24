import {
  useIsMutating,
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from '@tanstack/react-query'
import { isAxiosError } from 'axios'
import { toast } from 'sonner'

import { TASK_UPDATE_KEY, type UpdateVars } from '@/hooks/useTasks'
import {
  momentText,
  type ReminderCreateBody,
  type TaskReminderItem,
  type TaskRemindersResponse,
} from '@/lib/taskReminders'
import { taskRemindersApi } from '@/lib/taskRemindersApi'

/** Под префиксом `['task', id]`: его уже инвалидирует перенос задачи
 *  (`MOVE_TOUCHES`), а `useUpdateTask` — при правке срока и галочки. */
export const reminderKeys = {
  list: (taskId: string) => ['task', taskId, 'reminders'] as const,
}

export function useTaskReminders(
  taskId: string | undefined,
  enabled: boolean,
): UseQueryResult<TaskRemindersResponse> {
  return useQuery({
    queryKey: reminderKeys.list(taskId ?? 'none'),
    queryFn: () => taskRemindersApi.list(taskId!),
    enabled: enabled && !!taskId,
    staleTime: 30_000,
  })
}

/** Идёт ли правка ЭТОЙ задачи: POST напоминания, ушедший раньше PATCH срока,
 *  посчитался бы от старого срока и мог получить 422 «время прошло». */
export function useTaskUpdatePending(taskId: string | undefined): boolean {
  return (
    useIsMutating({
      mutationKey: TASK_UPDATE_KEY,
      predicate: (m) => (m.state.variables as UpdateVars | undefined)?.id === taskId,
    }) > 0
  )
}

function sameReminder(item: TaskReminderItem, body: ReminderCreateBody): boolean {
  if (item.anchor !== body.anchor) return false
  if (body.anchor !== 'at') return item.offset_minutes === (body.offset_minutes ?? 0)
  if (!item.fire_at || !body.fire_at) return false
  return Math.floor(Date.parse(item.fire_at) / 60_000) === Math.floor(Date.parse(body.fire_at) / 60_000)
}

export function useCreateReminder(taskId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: ReminderCreateBody) => taskRemindersApi.create(taskId, body),
    meta: { errorMessage: 'Не удалось поставить напоминание' },
    onSuccess: (data, body) => {
      qc.setQueryData(reminderKeys.list(taskId), data)
      // Текст — из ОТВЕТА: момент считает сервер (срок мог уже поменяться).
      const created = data.items.find((i) => sameReminder(i, body))
      toast.success(
        created?.fire_at ? `Напомню ${momentText(created.fire_at, Date.now())}` : 'Напоминание поставлено',
      )
    },
  })
}

export function useDeleteReminder(taskId: string) {
  const qc = useQueryClient()
  return useMutation({
    // 404 — задачу уже не видно; сама ручка на пропавшее напоминание отвечает
    // 204. В обоих случаях человеку показывать нечего.
    mutationFn: (reminderId: string) =>
      taskRemindersApi.remove(taskId, reminderId).catch((e: unknown) => {
        if (isAxiosError(e) && e.response?.status === 404) return
        throw e
      }),
    meta: { errorMessage: 'Не удалось удалить напоминание' },
    onMutate: async (reminderId) => {
      await qc.cancelQueries({ queryKey: reminderKeys.list(taskId) })
      const prev = qc.getQueryData<TaskRemindersResponse>(reminderKeys.list(taskId))
      if (prev) {
        qc.setQueryData<TaskRemindersResponse>(reminderKeys.list(taskId), {
          ...prev,
          items: prev.items.filter((i) => i.id !== reminderId),
        })
      }
      return { prev }
    },
    onError: (_e, _id, ctx) => {
      if (ctx?.prev) qc.setQueryData(reminderKeys.list(taskId), ctx.prev)
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: reminderKeys.list(taskId) })
    },
  })
}
