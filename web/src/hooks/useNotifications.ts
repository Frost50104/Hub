import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from '@tanstack/react-query'
import { toast } from 'sonner'

import { INBOX_FETCH_LIMIT, pageCursor } from '@/lib/inboxPaging'
import { bulkReadToast } from '@/lib/inboxSelection'
import { notificationsApi, type UnreadCount } from '@/lib/notifications'

/**
 * Список «Входящих» страницами по 50 — первый `useInfiniteQuery` в проекте.
 *
 * Ключ прежний (`['notifications', { unreadOnly }]`), но форма данных —
 * `{ pages, pageParams }`: сиды стенда (`dev/tracker.tsx`) кладут её же.
 * Просим 51 строку, 51-я — признак следующей страницы, курсор — id 50-й
 * (`lib/inboxPaging.ts`). Инвалидация префикса перезапрашивает страницы
 * ПОСЛЕДОВАТЕЛЬНО, курсор каждой — из свежего ответа предыдущей, хвост за
 * концом отбрасывается: после массовой отметки на «Непрочитанных» список
 * подтягивается без дублей, а «Показать ещё» гаснет сам. Оптимистичных
 * правок нет — пришлось бы переписывать обе ленты с пересчётом курсоров.
 */
export function useNotifications(unreadOnly = false) {
  return useInfiniteQuery({
    queryKey: ['notifications', { unreadOnly }],
    initialPageParam: undefined as number | undefined,
    queryFn: ({ pageParam }) =>
      notificationsApi.list({
        unread_only: unreadOnly,
        limit: INBOX_FETCH_LIMIT,
        before_id: pageParam,
      }),
    getNextPageParam: (last) => pageCursor(last),
  })
}

export function useUnreadCount(): UseQueryResult<UnreadCount> {
  return useQuery({
    queryKey: ['notifications', 'unread-count'],
    queryFn: () => notificationsApi.unreadCount(),
    refetchInterval: 60_000,
    staleTime: 30_000,
  })
}

export function useMarkRead() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => notificationsApi.markRead(id),
    meta: { errorMessage: 'Не удалось отметить прочитанным' },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['notifications'] })
    },
  })
}

export function useMarkAllRead() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => notificationsApi.markAllRead(),
    meta: { errorMessage: 'Не удалось отметить прочитанным' },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['notifications'] })
    },
  })
}

/**
 * Массовая отметка выбранных. Инвалидация в `onSettled`, а не в `onSuccess`:
 * выбор больше 500 уходит чанками, и при провале одного из них часть уже
 * применена — список обязан перечитаться в любом исходе.
 */
export function useSetReadState() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ ids, is_read }: { ids: number[]; is_read: boolean }) =>
      notificationsApi.setReadState(ids, is_read),
    meta: { errorMessage: 'Не удалось изменить отметку' },
    onSuccess: (res, vars) => {
      toast.success(bulkReadToast(res.updated, vars.is_read))
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ['notifications'] })
    },
  })
}
