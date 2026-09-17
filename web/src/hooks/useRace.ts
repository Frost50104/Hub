import { useMutation, useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query'

import {
  raceApi,
  type ContestAdmin,
  type RaceBoard,
  type RaceChart,
  type RaceContest,
  type RaceHistory,
  type RaceResults,
  type RaceSettings,
} from '@/lib/race'

/** Один префикс на всё: любая админ-мутация инвалидирует доску, историю,
 *  график и все админ-подключи разом. */
export const raceKeys = {
  all: ['learn-race'] as const,
  board: ['learn-race', 'board'] as const,
  result: (raceId: string) => ['learn-race', 'race', raceId] as const,
  history: (storeId: string | null, contestId: string | null) =>
    ['learn-race', 'history', storeId, contestId] as const,
  chart: (raceId: string, storeId: string | null) => ['learn-race', 'chart', raceId, storeId] as const,
  settings: ['learn-race', 'admin', 'settings'] as const,
  adminContests: ['learn-race', 'admin', 'contests'] as const,
  adminContest: (id: string) => ['learn-race', 'admin', 'contest', id] as const,
  baselines: (id: string, raceId: string | null) =>
    ['learn-race', 'admin', 'baselines', id, raceId ?? 'contest'] as const,
}

/** Сервер обновляет данные раз в час; опрос раз в 5 минут ловит тик без
 *  лишней нагрузки. `placeholderData` держит дерево дорожек между опросами —
 *  CSS-переезд гусей живёт на непрерывности DOM. */
export function useRaceBoard(enabled = true): UseQueryResult<RaceBoard> {
  return useQuery({
    queryKey: raceKeys.board,
    queryFn: raceApi.board,
    enabled,
    staleTime: 60_000,
    refetchInterval: 5 * 60_000,
    placeholderData: (prev) => prev,
  })
}

export function useRaceResults(raceId: string | null): UseQueryResult<RaceResults> {
  return useQuery({
    queryKey: raceKeys.result(raceId ?? ''),
    queryFn: () => raceApi.results(raceId!),
    enabled: !!raceId,
    staleTime: 5 * 60_000,
  })
}

export function useRaceHistory(storeId: string | null, contestId: string | null): UseQueryResult<RaceHistory> {
  return useQuery({
    queryKey: raceKeys.history(storeId, contestId),
    queryFn: () => raceApi.history(storeId, contestId),
    enabled: !!storeId,
    staleTime: 5 * 60_000,
    placeholderData: (prev) => prev,
  })
}

export function useRaceChart(raceId: string | null, storeId: string | null): UseQueryResult<RaceChart> {
  return useQuery({
    queryKey: raceKeys.chart(raceId ?? '', storeId),
    queryFn: () => raceApi.chart(raceId!, storeId),
    enabled: !!raceId && !!storeId,
    staleTime: 5 * 60_000,
    placeholderData: (prev) => prev,
  })
}

// ─── админ ──────────────────────────────────────────────────────────────────

export function useRaceSettings(enabled = true): UseQueryResult<RaceSettings> {
  return useQuery({ queryKey: raceKeys.settings, queryFn: raceApi.settings, enabled, staleTime: 60_000 })
}

export function useAdminContests(enabled = true): UseQueryResult<RaceContest[]> {
  return useQuery({
    queryKey: raceKeys.adminContests,
    queryFn: raceApi.adminContests,
    enabled,
    staleTime: 30_000,
  })
}

export function useAdminContest(id: string | null): UseQueryResult<ContestAdmin> {
  return useQuery({
    queryKey: raceKeys.adminContest(id ?? ''),
    queryFn: () => raceApi.adminContest(id!),
    enabled: !!id,
    staleTime: 30_000,
    placeholderData: (prev) => prev,
  })
}

export function useBaselines(contestId: string | null, raceId: string | null) {
  return useQuery({
    queryKey: raceKeys.baselines(contestId ?? '', raceId),
    queryFn: () => raceApi.baselines(contestId!, raceId),
    enabled: !!contestId,
    staleTime: 30_000,
    placeholderData: (prev) => prev,
  })
}

/** Любая админ-мутация: инвалидирует весь префикс гонки; ошибка — в общий тост
 *  (`lib/queryClient.ts`) с текстом из `meta.errorMessage`. */
export function useRaceAdminMutation<TArgs, TResult>(
  fn: (args: TArgs) => Promise<TResult>,
  errorMessage: string,
  onSuccess?: (result: TResult, args: TArgs) => void,
) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: fn,
    meta: { errorMessage },
    onSuccess: async (result, args) => {
      await qc.invalidateQueries({ queryKey: raceKeys.all })
      onSuccess?.(result, args)
    },
  })
}
