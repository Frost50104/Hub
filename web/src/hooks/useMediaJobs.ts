import {
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from '@tanstack/react-query'
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

export type StartJobInput =
  | 'transcribe'
  | { kind: 'transcribe' | 'cleanup' | 'analyze' | 'compose'; params?: Record<string, unknown> }

export function useStartMediaJob(mediaId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: StartJobInput) =>
      typeof input === 'string'
        ? learnApi.createMediaJob(mediaId, input)
        : learnApi.createMediaJob(mediaId, input.kind, input.params),
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

export function useStoryboard(mediaId: string | null | undefined, enabled = true) {
  return useQuery({
    queryKey: ['learn-media', mediaId, 'storyboard'],
    queryFn: () => learnApi.mediaStoryboard(mediaId!),
    enabled: Boolean(mediaId) && enabled,
    staleTime: 10_000,
    retry: false,
    meta: { suppressGlobalError: true },
  })
}

export function useUpdateStoryboard(mediaId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (patch: Parameters<typeof learnApi.updateMediaStoryboard>[1]) =>
      learnApi.updateMediaStoryboard(mediaId, patch),
    onSuccess: (fresh) => {
      qc.setQueryData(['learn-media', mediaId, 'storyboard'], fresh)
      void qc.invalidateQueries({ queryKey: ['learn-media', mediaId, 'estimate'] })
    },
    onError: (err) => {
      toast.error('Не удалось сохранить раскадровку', { description: extractErrorDetail(err) })
    },
  })
}

export function useComposeEstimate(
  mediaId: string | null | undefined,
  resolution: '540p' | '720p' | '1080p' | undefined,
  enabled = true,
) {
  return useQuery({
    queryKey: ['learn-media', mediaId, 'estimate', resolution ?? 'default'],
    queryFn: () => learnApi.composeEstimate(mediaId!, resolution),
    enabled: Boolean(mediaId) && enabled,
    staleTime: 10_000,
    retry: false,
    meta: { suppressGlobalError: true },
  })
}

/** Детали вставок раскадровки (имя файла, длина, статус) — по одной на id;
 *  вставок единицы, отдельной батч-ручки нет. */
export function useInsertDetails(ids: string[]) {
  return useQueries({
    queries: ids.map((id) => ({
      queryKey: ['learn-media', id],
      queryFn: () => learnApi.mediaDetail(id),
      staleTime: 30_000,
      retry: false,
      meta: { suppressGlobalError: true },
    })),
  })
}

/** «Проверить на 10 секундах» в админке: задание `avatar_test` на сцене. */
export function useStartAvatarTest() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: learnApi.startAvatarTest,
    onSuccess: (job) => {
      void qc.invalidateQueries({ queryKey: ['learn-media', job.media_id] })
      void qc.invalidateQueries({ queryKey: ['learn-media', 'admin', 'settings'] })
    },
    onError: (err) => {
      toast.error('Не удалось запустить проверку', { description: extractErrorDetail(err) })
    },
  })
}
