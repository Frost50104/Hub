import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from '@tanstack/react-query'

import { attachmentsApi, type Attachment } from '@/lib/attachments'

const keys = {
  list: (taskId: string) => ['task', taskId, 'attachments'] as const,
}

export function useAttachments(
  taskId: string | undefined,
): UseQueryResult<Attachment[]> {
  return useQuery({
    queryKey: taskId ? keys.list(taskId) : ['task', 'none', 'attachments'],
    queryFn: () => attachmentsApi.list(taskId!),
    enabled: !!taskId,
  })
}

/**
 * Переменные мутации — объект, а не голый `File`, ради `onProgress`.
 *
 * Состояние прогресса живёт в КОМПОНЕНТЕ, а не в хуке: гигабайтная загрузка
 * идёт десятки минут, и это ровно то время, когда пользователь ждёт обратной
 * связи именно от той дропзоны, в которую бросил файл.
 */
export interface UploadAttachmentVars {
  file: File
  onProgress?: (fraction: number) => void
}

export function useUploadAttachment(taskId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ file, onProgress }: UploadAttachmentVars) =>
      attachmentsApi.upload(taskId, file, onProgress),
    meta: { errorMessage: 'Не удалось загрузить файл' },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.list(taskId) })
      qc.invalidateQueries({ queryKey: ['task', taskId, 'activity'] })
    },
  })
}

export function useDeleteAttachment(taskId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (attachmentId: string) => attachmentsApi.remove(attachmentId),
    meta: { errorMessage: 'Не удалось удалить файл' },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.list(taskId) })
      qc.invalidateQueries({ queryKey: ['task', taskId, 'activity'] })
    },
  })
}
