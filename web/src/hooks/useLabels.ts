import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from '@tanstack/react-query'

import {
  labelsApi,
  type Label,
  type LabelAssignment,
  type LabelCreateBody,
  type LabelUpdateBody,
} from '@/lib/labels'

export const labelKeys = {
  all: (projectId: string) => ['labels', projectId] as const,
  list: (projectId: string) => ['labels', projectId, 'list'] as const,
  assignments: (projectId: string) => ['labels', projectId, 'assignments'] as const,
}

export function useLabels(projectId: string | undefined): UseQueryResult<Label[]> {
  return useQuery({
    queryKey: projectId ? labelKeys.list(projectId) : ['labels', 'none', 'list'],
    queryFn: () => labelsApi.list(projectId!),
    enabled: !!projectId,
    staleTime: 60_000,
  })
}

export function useLabelAssignments(
  projectId: string | undefined,
): UseQueryResult<LabelAssignment[]> {
  return useQuery({
    queryKey: projectId
      ? labelKeys.assignments(projectId)
      : ['labels', 'none', 'assignments'],
    queryFn: () => labelsApi.assignments(projectId!),
    enabled: !!projectId,
    staleTime: 30_000,
  })
}

export function useCreateLabel(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: LabelCreateBody) => labelsApi.create(projectId, body),
    meta: { errorMessage: 'Не удалось создать метку' },
    onSuccess: () => qc.invalidateQueries({ queryKey: labelKeys.list(projectId) }),
  })
}

export function useUpdateLabel(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ labelId, body }: { labelId: string; body: LabelUpdateBody }) =>
      labelsApi.update(projectId, labelId, body),
    meta: { errorMessage: 'Не удалось обновить метку' },
    onSuccess: () => qc.invalidateQueries({ queryKey: labelKeys.list(projectId) }),
  })
}

export function useDeleteLabel(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (labelId: string) => labelsApi.remove(projectId, labelId),
    meta: { errorMessage: 'Не удалось удалить метку' },
    // Назначения уходят каскадом на бэке — сносим оба кэша разом.
    onSuccess: () => qc.invalidateQueries({ queryKey: labelKeys.all(projectId) }),
  })
}

export function useAssignLabel(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ taskId, labelId }: { taskId: string; labelId: string }) =>
      labelsApi.assign(taskId, labelId),
    meta: { errorMessage: 'Не удалось назначить метку' },
    onSuccess: (_data, { taskId }) => {
      qc.invalidateQueries({ queryKey: labelKeys.assignments(projectId) })
      qc.invalidateQueries({ queryKey: ['task', taskId, 'activity'] })
      // При активном фильтре по метке членство в списке меняется.
      qc.invalidateQueries({ queryKey: ['tasks', projectId] })
    },
  })
}

export function useUnassignLabel(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ taskId, labelId }: { taskId: string; labelId: string }) =>
      labelsApi.unassign(taskId, labelId),
    meta: { errorMessage: 'Не удалось снять метку' },
    onSuccess: (_data, { taskId }) => {
      qc.invalidateQueries({ queryKey: labelKeys.assignments(projectId) })
      qc.invalidateQueries({ queryKey: ['task', taskId, 'activity'] })
      qc.invalidateQueries({ queryKey: ['tasks', projectId] })
    },
  })
}
