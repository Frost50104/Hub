import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
  type UseQueryResult,
} from '@tanstack/react-query'

import {
  activityApi,
  commentsApi,
  watchersApi,
  type Activity,
  type Comment,
  type Watcher,
} from '@/lib/threads'

export const threadKeys = {
  comments: (taskId: string) => ['task', taskId, 'comments'] as const,
  watchers: (taskId: string) => ['task', taskId, 'watchers'] as const,
  activity: (taskId: string) => ['task', taskId, 'activity'] as const,
}

/**
 * Всё, что карточка показывает ПОД задачей: обсуждение, ленту, наблюдателей,
 * вложения, напоминания (всё под префиксом `['task', id]`).
 *
 * Зовётся переходом из уведомления (пуш, «Входящие»): он обязан показать
 * свежее обсуждение, а не кэш — `staleTime` 30 с, реалтайма нет, а клик по
 * пушу с 25.09 на уже открытой карточке страницу не перезагружает (ОС 08.09,
 * RH-23). Деталь задачи (`['tasks', 'detail', id]` — другой префикс) НЕ
 * трогаем: карточка пересоздаёт заголовок и описание на каждый новый объект
 * задачи, и незаконченная правка пропала бы.
 */
export function invalidateTaskThread(qc: QueryClient, taskId: string): Promise<void> {
  return qc.invalidateQueries({ queryKey: ['task', taskId] })
}

/** «💬 N» в строке списка считает сервер — своя правка не ждёт staleTime. */
function invalidateCommentCounters(qc: QueryClient, projectId: string): void {
  void qc.invalidateQueries({ queryKey: ['tasks', projectId] })
  void qc.invalidateQueries({ queryKey: ['me-tasks'] })
  void qc.invalidateQueries({ queryKey: ['me-assigned-by-me'] })
}

export function useComments(taskId: string | undefined): UseQueryResult<Comment[]> {
  return useQuery({
    queryKey: taskId ? threadKeys.comments(taskId) : ['task', 'none', 'comments'],
    queryFn: () => commentsApi.list(taskId!),
    enabled: !!taskId,
  })
}

export function useWatchers(taskId: string | undefined): UseQueryResult<Watcher[]> {
  return useQuery({
    queryKey: taskId ? threadKeys.watchers(taskId) : ['task', 'none', 'watchers'],
    queryFn: () => watchersApi.list(taskId!),
    enabled: !!taskId,
  })
}

export function useActivity(taskId: string | undefined): UseQueryResult<Activity[]> {
  return useQuery({
    queryKey: taskId ? threadKeys.activity(taskId) : ['task', 'none', 'activity'],
    queryFn: () => activityApi.list(taskId!),
    enabled: !!taskId,
  })
}

export function useCreateComment(taskId: string, projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: string) => commentsApi.create(taskId, body),
    meta: { errorMessage: 'Не удалось отправить комментарий' },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: threadKeys.comments(taskId) })
      qc.invalidateQueries({ queryKey: threadKeys.activity(taskId) })
      qc.invalidateQueries({ queryKey: threadKeys.watchers(taskId) })
      invalidateCommentCounters(qc, projectId)
    },
  })
}

export function useDeleteComment(taskId: string, projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (commentId: string) => commentsApi.remove(commentId),
    meta: { errorMessage: 'Не удалось удалить комментарий' },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: threadKeys.comments(taskId) })
      invalidateCommentCounters(qc, projectId)
    },
  })
}

/** Редакторское добавление/снятие ДРУГОГО наблюдателя (02.09).
 *  Оптимистично патчит список наблюдателей — пикер в карточке отзывается
 *  мгновенно; на ошибке снимок возвращается. */
export function useToggleWatcher(taskId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ person, next }: { person: Watcher; next: boolean }) =>
      next
        ? watchersApi.add(taskId, person.employee_id).then(() => undefined)
        : watchersApi.remove(taskId, person.employee_id),
    meta: { errorMessage: 'Не удалось изменить наблюдателей' },
    onMutate: async ({ person, next }) => {
      await qc.cancelQueries({ queryKey: threadKeys.watchers(taskId) })
      const prev = qc.getQueryData<Watcher[]>(threadKeys.watchers(taskId))
      qc.setQueryData<Watcher[]>(threadKeys.watchers(taskId), (list) => {
        const cur = list ?? []
        if (next) {
          if (cur.some((w) => w.employee_id === person.employee_id)) return cur
          return [...cur, { ...person, added_reason: 'manual', added_at: new Date().toISOString() }]
        }
        return cur.filter((w) => w.employee_id !== person.employee_id)
      })
      return { prev }
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.prev) qc.setQueryData(threadKeys.watchers(taskId), ctx.prev)
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: threadKeys.watchers(taskId) })
      void qc.invalidateQueries({ queryKey: threadKeys.activity(taskId) })
    },
  })
}

export function useToggleWatch(taskId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (currentlyWatching: boolean) => {
      if (currentlyWatching) {
        await watchersApi.leave(taskId)
      } else {
        await watchersApi.join(taskId)
      }
    },
    meta: { errorMessage: 'Не удалось изменить подписку' },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: threadKeys.watchers(taskId) })
      qc.invalidateQueries({ queryKey: threadKeys.activity(taskId) })
    },
  })
}
