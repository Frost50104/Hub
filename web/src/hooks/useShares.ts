import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from '@tanstack/react-query'

import { shareApi, type ShareResponse } from '@/lib/share'

const projectKey = (projectId: string) => ['shares', 'project', projectId] as const
const taskKey = (taskId: string) => ['shares', 'task', taskId] as const

export function useProjectShares(
  projectId: string | undefined,
  enabled: boolean,
): UseQueryResult<ShareResponse[]> {
  return useQuery({
    queryKey: projectId ? projectKey(projectId) : ['shares', 'project', 'none'],
    queryFn: () => shareApi.listForProject(projectId!),
    enabled: !!projectId && enabled,
    staleTime: 30_000,
  })
}

export function useTaskShares(
  taskId: string | undefined,
  enabled: boolean,
): UseQueryResult<ShareResponse[]> {
  return useQuery({
    queryKey: taskId ? taskKey(taskId) : ['shares', 'task', 'none'],
    queryFn: () => shareApi.listForTask(taskId!),
    enabled: !!taskId && enabled,
    staleTime: 30_000,
  })
}

export function useCreateProjectShare(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { expires_at?: string | null } = {}) =>
      shareApi.createForProject(projectId, body),
    meta: { errorMessage: 'Не удалось создать ссылку' },
    onSuccess: () => qc.invalidateQueries({ queryKey: projectKey(projectId) }),
  })
}

export function useCreateTaskShare(taskId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { expires_at?: string | null } = {}) =>
      shareApi.createForTask(taskId, body),
    meta: { errorMessage: 'Не удалось создать ссылку' },
    onSuccess: () => qc.invalidateQueries({ queryKey: taskKey(taskId) }),
  })
}

export function useRevokeShare(scope: 'project' | 'task', entityId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (token: string) => shareApi.revoke(token),
    meta: { errorMessage: 'Не удалось отозвать ссылку' },
    onSuccess: () =>
      qc.invalidateQueries({
        queryKey: scope === 'project' ? projectKey(entityId) : taskKey(entityId),
      }),
  })
}
