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

export function useCreateCustomField(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: CustomFieldDefinitionCreate) =>
      customFieldsApi.create(projectId, body),
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
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: customFieldKeys.defs(projectId) })
    },
  })
}

export function useDeleteCustomField(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (fieldId: string) => customFieldsApi.remove(projectId, fieldId),
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
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: customFieldKeys.values(taskId) })
    },
  })
}

export function useClearTaskCustomValue(taskId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (fieldId: string) => customFieldsApi.clearValue(taskId, fieldId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: customFieldKeys.values(taskId) })
    },
  })
}
