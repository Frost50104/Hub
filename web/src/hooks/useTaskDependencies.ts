import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from '@tanstack/react-query'

import { timelineApi, type TaskDependencies } from '@/lib/timeline'

const key = (taskId: string) => ['dependencies', taskId] as const

export function useTaskDependencies(
  taskId: string | undefined,
): UseQueryResult<TaskDependencies> {
  return useQuery({
    queryKey: taskId ? key(taskId) : ['dependencies', 'none'],
    queryFn: () => timelineApi.taskDependencies(taskId!),
    enabled: !!taskId,
    staleTime: 30_000,
  })
}

export function useAddDependency(taskId: string, projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (predecessorId: string) =>
      timelineApi.addDependency(taskId, predecessorId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: key(taskId) })
      qc.invalidateQueries({ queryKey: ['timeline', projectId] })
    },
  })
}

export function useRemoveDependency(taskId: string, projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (predecessorId: string) =>
      timelineApi.removeDependency(taskId, predecessorId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: key(taskId) })
      qc.invalidateQueries({ queryKey: ['timeline', projectId] })
    },
  })
}
