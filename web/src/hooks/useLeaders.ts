import { useQuery, type UseQueryResult } from '@tanstack/react-query'

import { statsApi, type Leaders } from '@/lib/stats'

/**
 * «Команда за 30 дней» на «Главной».
 *
 * `staleTime` НЕ задаём — по той же причине, что у `useMyStats`: опции хука
 * перебивают `setQueryDefaults` стенда. Глобальные 30 с хватает: чужие цифры
 * не горят, свои инвалидирует `useToggleDone`.
 */
export function useLeaders(): UseQueryResult<Leaders> {
  return useQuery({
    queryKey: ['leaders'],
    queryFn: () => statsApi.leaders(),
  })
}
