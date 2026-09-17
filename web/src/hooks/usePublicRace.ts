import { useQuery, type UseQueryResult } from '@tanstack/react-query'

import { publicRaceApi, type RaceBoard } from '@/lib/race'

/** ТВ-панель: опрос каждые 5 минут и в фоне; 404/503 не ретраим (ссылка
 *  отозвана или модуль выключен — «недействительна»). */
export function usePublicRace(token: string | undefined): UseQueryResult<RaceBoard> {
  return useQuery({
    queryKey: ['public-race', token],
    queryFn: () => publicRaceApi.board(token!),
    enabled: !!token,
    staleTime: 60_000,
    refetchInterval: 5 * 60_000,
    refetchIntervalInBackground: true,
    placeholderData: (prev) => prev,
    retry: (failureCount, err) => {
      const status = (err as { response?: { status?: number } }).response?.status
      if (status === 404 || status === 503) return false
      return failureCount < 1
    },
  })
}
