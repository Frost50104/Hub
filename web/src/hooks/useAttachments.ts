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

export function useUploadAttachment(taskId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (file: File) => attachmentsApi.upload(taskId, file),
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
