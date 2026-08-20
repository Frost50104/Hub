import { useQuery, type UseQueryResult } from '@tanstack/react-query'

import { timelineApi, type TimelineResponse } from '@/lib/timeline'

export function useTimeline(
  projectId: string | undefined,
  from: string,
  to: string,
  opts?: { includeUndated?: boolean },
): UseQueryResult<TimelineResponse> {
  const includeUndated = opts?.includeUndated ?? false
  return useQuery({
    queryKey: projectId
      ? ['timeline', projectId, from, to, { includeUndated }]
      : ['timeline', 'none', from, to],
    queryFn: () => timelineApi.get(projectId!, { from, to }, { includeUndated }),
    enabled: !!projectId,
    staleTime: 30_000,
  })
}
