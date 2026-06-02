import { useQuery, type UseQueryResult } from '@tanstack/react-query'

import { statsApi, type ProjectStats } from '@/lib/stats'

export function useProjectStats(
  projectId: string | undefined,
): UseQueryResult<ProjectStats> {
  return useQuery({
    queryKey: projectId ? ['stats', projectId] : ['stats', 'none'],
    queryFn: () => statsApi.forProject(projectId!),
    enabled: !!projectId,
    staleTime: 60_000,
  })
}
