import { useQuery, type UseQueryResult } from '@tanstack/react-query'

import { timelineApi, type TimelineResponse } from '@/lib/timeline'

export function useTimeline(
  projectId: string | undefined,
  from: string,
  to: string,
): UseQueryResult<TimelineResponse> {
  return useQuery({
    queryKey: projectId
      ? ['timeline', projectId, from, to]
      : ['timeline', 'none', from, to],
    queryFn: () => timelineApi.get(projectId!, { from, to }),
    enabled: !!projectId,
    staleTime: 30_000,
  })
}
