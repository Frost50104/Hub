import { useQuery, type UseQueryResult } from '@tanstack/react-query'

import { publicShareApi, type PublicView } from '@/lib/publicApi'

export function usePublicShare(token: string | undefined): UseQueryResult<PublicView> {
  return useQuery({
    queryKey: ['public-share', token],
    queryFn: () => publicShareApi.resolve(token!),
    enabled: !!token,
    // Aggressive cache — token resolves rarely change. Refetch on mount only.
    staleTime: 5 * 60_000,
    retry: (failureCount, err) => {
      // 404 means revoked/expired — don't retry; otherwise allow 1 retry.
      const status = (err as { response?: { status?: number } }).response?.status
      if (status === 404 || status === 503) return false
      return failureCount < 1
    },
  })
}
