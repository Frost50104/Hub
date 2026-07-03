import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from '@tanstack/react-query'

import {
  customFieldsApi,
  type CustomFieldDefinition,
  type CustomFieldDefinitionCreate,
  type CustomFieldDefinitionUpdate,
  type CustomFieldValue,
} from '@/lib/customFields'

export const customFieldKeys = {
  defs: (projectId: string) => ['custom-fields', 'defs', projectId] as const,
  values: (taskId: string) => ['custom-fields', 'values', taskId] as const,
  projectValues: (projectId: string) =>
    ['custom-fields', 'project-values', projectId] as const,
}

export function useCustomFieldDefinitions(
  projectId: string | undefined,
): UseQueryResult<CustomFieldDefinition[]> {
  return useQuery({
    queryKey: projectId
      ? customFieldKeys.defs(projectId)
      : ['custom-fields', 'defs', 'none'],
    queryFn: () => customFieldsApi.list(projectId!),
    enabled: !!projectId,
    staleTime: 60_000,
  })
}

export function useTaskCustomValues(
  taskId: string | undefined,
): UseQueryResult<CustomFieldValue[]> {
  return useQuery({
    queryKey: taskId
      ? customFieldKeys.values(taskId)
      : ['custom-fields', 'values', 'none'],
    queryFn: () => customFieldsApi.taskValues(taskId!),
    enabled: !!taskId,
  })
}

/**
 * Batch fetch — all custom values for all tasks in a project. Used by the
 * List view to render columns without an N+1.
 */
export function useProjectCustomValues(
  projectId: string | undefined,
  enabled = true,
): UseQueryResult<CustomFieldValue[]> {
  return useQuery({
    queryKey: projectId
      ? customFieldKeys.projectValues(projectId)
      : ['custom-fields', 'project-values', 'none'],
    queryFn: () => customFieldsApi.projectValues(projectId!),
    enabled: !!projectId && enabled,
    staleTime: 30_000,
  })
}

export function useCreateCustomField(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: CustomFieldDefinitionCreate) =>
      customFieldsApi.create(projectId, body),
    meta: { errorMessage: 'Не удалось создать поле' },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: customFieldKeys.defs(projectId) })
    },
  })
}

export function useUpdateCustomField(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      fieldId,
      body,
    }: {
      fieldId: string
      body: CustomFieldDefinitionUpdate
    }) => customFieldsApi.update(projectId, fieldId, body),
    meta: { errorMessage: 'Не удалось обновить поле' },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: customFieldKeys.defs(projectId) })
    },
  })
}

export function useDeleteCustomField(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (fieldId: string) => customFieldsApi.remove(projectId, fieldId),
    meta: { errorMessage: 'Не удалось удалить поле' },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: customFieldKeys.defs(projectId) })
    },
  })
}

export function useSetTaskCustomValue(taskId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ fieldId, value }: { fieldId: string; value: unknown }) =>
      customFieldsApi.setValue(taskId, fieldId, value),
    meta: { errorMessage: 'Не удалось сохранить значение' },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: customFieldKeys.values(taskId) })
      // Also blow away batch project-values cache — without this, the List
      // view shows stale column data right after editing in the drawer.
      qc.invalidateQueries({ queryKey: ['custom-fields', 'project-values'] })
    },
  })
}

export function useClearTaskCustomValue(taskId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (fieldId: string) => customFieldsApi.clearValue(taskId, fieldId),
    meta: { errorMessage: 'Не удалось очистить значение' },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: customFieldKeys.values(taskId) })
      qc.invalidateQueries({ queryKey: ['custom-fields', 'project-values'] })
    },
  })
}
