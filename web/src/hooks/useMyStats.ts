import { useQuery, type UseQueryResult } from '@tanstack/react-query'

import { statsApi, type MyStats } from '@/lib/stats'

/**
 * Личная статистика «Главной».
 *
 * Периода в ключе НЕТ намеренно: ответ несёт и 7, и 30 дней, переключатель
 * режет данные на клиенте и в сеть не ходит.
 */
export function useMyStats(): UseQueryResult<MyStats> {
  return useQuery({
    queryKey: ['me-stats'],
    queryFn: () => statsApi.forMe(),
    // `staleTime` НЕ задаём: опции хука в TanStack v5 перебивают
    // `setQueryDefaults`, и превью-стенд (`dev/tracker.tsx`, где всё
    // `Infinity`) уходил бы в несуществующую сеть. Глобальные 30 с из
    // `lib/queryClient.ts` для блока «Главной» в самый раз.
  })
}
