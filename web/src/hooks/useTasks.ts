import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from '@tanstack/react-query'

import {
  tasksApi,
  type Task,
  type TaskCreateBody,
  type TaskListFilters,
  type TaskUpdateBody,
} from '@/lib/tasks'

export const taskKeys = {
  all: ['tasks'] as const,
  list: (projectId: string, filters?: TaskListFilters) =>
    ['tasks', projectId, filters ?? {}] as const,
  detail: (id: string) => ['tasks', 'detail', id] as const,
}

export function useTasks(
  projectId: string | undefined,
  filters?: TaskListFilters,
): UseQueryResult<Task[]> {
  return useQuery({
    queryKey: projectId ? taskKeys.list(projectId, filters) : ['tasks', 'none'],
    queryFn: () => tasksApi.list(projectId!, filters),
    enabled: !!projectId,
  })
}

export function useTask(id: string | undefined): UseQueryResult<Task> {
  return useQuery({
    queryKey: id ? taskKeys.detail(id) : ['tasks', 'none-detail'],
    queryFn: () => tasksApi.get(id!),
    enabled: !!id,
  })
}

export function useCreateTask(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: TaskCreateBody) => tasksApi.create(projectId, body),
    meta: { errorMessage: 'Не удалось создать задачу' },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['tasks', projectId] })
    },
  })
}

export function useUpdateTask(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...body }: TaskUpdateBody & { id: string }) =>
      tasksApi.update(id, body),
    meta: { errorMessage: 'Не удалось обновить задачу' },
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['tasks', projectId] })
      qc.invalidateQueries({ queryKey: taskKeys.detail(data.id) })
    },
  })
}

export function useArchiveTask(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, archive }: { id: string; archive: boolean }) =>
      archive ? tasksApi.archive(id) : tasksApi.unarchive(id),
    meta: { errorMessage: 'Не удалось обновить задачу' },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['tasks', projectId] }),
  })
}

export function useDeleteTask(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => tasksApi.remove(id),
    meta: { errorMessage: 'Не удалось удалить задачу' },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['tasks', projectId] }),
  })
}
