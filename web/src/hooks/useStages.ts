import { useMutation, useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query'

import {
  stagesApi,
  type StageCreateBody,
  type StageUpdateBody,
  type TaskStage,
} from '@/lib/stages'

export const stageKeys = {
  list: (projectId: string) => ['stages', projectId] as const,
}

export function useStages(projectId: string | undefined): UseQueryResult<TaskStage[]> {
  return useQuery({
    queryKey: projectId ? stageKeys.list(projectId) : ['stages', 'none'],
    queryFn: () => stagesApi.list(projectId!),
    enabled: !!projectId,
    staleTime: 30_000,
  })
}

export function useCreateStage(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: StageCreateBody) => stagesApi.create(projectId, body),
    meta: { errorMessage: 'Не удалось создать этап' },
    onSuccess: () => qc.invalidateQueries({ queryKey: stageKeys.list(projectId) }),
  })
}

export function useUpdateStage(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ stageId, ...body }: StageUpdateBody & { stageId: string }) =>
      stagesApi.update(stageId, body),
    meta: { errorMessage: 'Не удалось обновить этап' },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: stageKeys.list(projectId) })
      // Строки списка показывают имя колонки (`stage_name`), а карточки
      // доски сгруппированы по `stage_id` — переименование колонки меняет
      // подпись у всех её задач.
      qc.invalidateQueries({ queryKey: ['tasks', projectId] })
    },
  })
}

export function useDeleteStage(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ stageId, moveTo }: { stageId: string; moveTo?: string | null }) =>
      stagesApi.remove(stageId, moveTo),
    meta: { errorMessage: 'Не удалось удалить этап' },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: stageKeys.list(projectId) })
      qc.invalidateQueries({ queryKey: ['tasks', projectId] })
    },
  })
}
