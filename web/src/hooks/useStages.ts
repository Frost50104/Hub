import { useMutation, useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query'

import { renameStage, reorderStages } from '@/lib/stageOrder'
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

/**
 * Правка колонки: имя и позиция — обе оптимистично.
 *
 * Без оптимистики перетащенная колонка на кадр возвращается на прежнее место
 * (мутация ждёт ответ и рефетч), а переименование мигает старым именем. Порядок
 * считает та же чистая функция, что и отправку, — сервер и кэш обязаны прийти
 * к одному результату (`lib/stageOrder.ts`).
 */
export function useUpdateStage(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ stageId, ...body }: StageUpdateBody & { stageId: string }) =>
      stagesApi.update(stageId, body),
    meta: { errorMessage: 'Не удалось обновить этап' },
    onMutate: async ({ stageId, name, position }) => {
      await qc.cancelQueries({ queryKey: stageKeys.list(projectId) })
      const previous = qc.getQueryData<TaskStage[]>(stageKeys.list(projectId))
      if (previous) {
        let next = previous
        if (name !== undefined) next = renameStage(next, stageId, name)
        if (position !== undefined) {
          const target = next[position]
          // Целимся в id соседа, а не в индекс: `reorderStages` — единственное
          // место, где считается новый порядок, и оно работает с id.
          const move = target ? reorderStages(next, stageId, target.id) : null
          if (move) next = move.next
        }
        qc.setQueryData(stageKeys.list(projectId), next)
      }
      return { previous }
    },
    onError: (_err, _vars, ctx) => {
      // Откат обязателен: иначе кэш останется переставленным, сервер — нет, и
      // расхождение проживёт до следующего рефетча как «порядок сам съехал».
      if (ctx?.previous) qc.setQueryData(stageKeys.list(projectId), ctx.previous)
    },
    onSettled: () => {
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
    mutationFn: ({
      stageId,
      moveTo,
      detach,
    }: {
      stageId: string
      moveTo?: string | null
      detach?: boolean
    }) => stagesApi.remove(stageId, { moveTo, detach }),
    meta: { errorMessage: 'Не удалось удалить этап' },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: stageKeys.list(projectId) })
      qc.invalidateQueries({ queryKey: ['tasks', projectId] })
    },
  })
}
