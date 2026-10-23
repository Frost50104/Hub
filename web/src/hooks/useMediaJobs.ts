import { useMutation, useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query'
import { toast } from 'sonner'

import { extractErrorDetail } from '@/lib/errors'
import { learnApi, type MediaDetail } from '@/lib/learn'
import { pollIntervalMs } from '@/lib/mediaJobs'

/**
 * Состояние файла конвейера (0066). Ключ `['learn-media', id]` делят
 * видеоблок редактора и шторка инструментов; опрос идёт только пока по
 * файлу есть работа (`pollIntervalMs`), и не в фоне. Урок (`['learn-lesson']`)
 * отсюда НЕ инвалидируется: плеер держит `srcRef`, а редактор — состояние
 * контента, и перечитывание сбросило бы и то и другое.
 */
export function useMediaDetail(
  id: string | null | undefined,
  enabled = true,
): UseQueryResult<MediaDetail> {
  return useQuery({
    queryKey: ['learn-media', id],
    queryFn: () => learnApi.mediaDetail(id!),
    enabled: Boolean(id) && enabled,
    staleTime: 5_000,
    retry: false,
    refetchInterval: (query) => pollIntervalMs(query.state.data),
    refetchIntervalInBackground: false,
    meta: { suppressGlobalError: true },
  })
}

export function useStartMediaJob(mediaId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (kind: 'transcribe') => learnApi.createMediaJob(mediaId, kind),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['learn-media', mediaId] })
    },
    onError: (err) => {
      toast.error('Не удалось запустить', {
        description: extractErrorDetail(err),
      })
    },
  })
}

export function useCancelMediaJob(mediaId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (jobId: string) => learnApi.cancelMediaJob(jobId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['learn-media', mediaId] })
    },
    onError: (err) => {
      toast.error('Не удалось отменить', {
        description: extractErrorDetail(err),
      })
    },
  })
}

export function useMediaAdminSettings(enabled = true) {
  return useQuery({
    queryKey: ['learn-media', 'admin', 'settings'],
    queryFn: learnApi.mediaAdminSettings,
    enabled,
    retry: false,
    meta: { suppressGlobalError: true },
  })
}

export function useUpdateMediaAdminSettings() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: learnApi.updateMediaAdminSettings,
    onSuccess: (fresh) => {
      qc.setQueryData(['learn-media', 'admin', 'settings'], fresh)
      // Тумблер тенанта меняет `me.features.media_pipeline` — редактор и
      // загрузка читают его оттуда.
      void qc.invalidateQueries({ queryKey: ['me'] })
    },
    onError: (err) => {
      toast.error('Не удалось сохранить', {
        description: extractErrorDetail(err),
      })
    },
  })
}
