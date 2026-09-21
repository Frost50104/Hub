import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { projectKeys } from '@/hooks/useProjects'
import type {
  ProjectFromTemplateBody,
  SaveAsTemplateBody,
  TemplateCreateBody,
} from '@/lib/projectTemplates'
import { templatesApi } from '@/lib/projectTemplatesApi'

/**
 * Ключи библиотеки — СВОИ, не под `['projects']`: создание задачи
 * инвалидирует `['projects']` (`useTasks.ts`), и библиотека иначе
 * перезапрашивалась бы на каждой правке задачи.
 */
export const templateKeys = {
  all: ['project-templates'] as const,
  list: ['project-templates', 'list'] as const,
  settings: ['project-templates', 'settings'] as const,
  preview: (id: string, startOn: string | null) =>
    ['project-templates', 'preview', id, startOn] as const,
  saveAsPreview: (projectId: string) =>
    ['project-templates', 'save-as-preview', projectId] as const,
}

export function useTemplates(enabled = true) {
  return useQuery({ queryKey: templateKeys.list, queryFn: templatesApi.list, enabled })
}

export function useTemplateSettings(enabled: boolean) {
  return useQuery({ queryKey: templateKeys.settings, queryFn: templatesApi.settings, enabled })
}

export function useSetTemplatesEnabled() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (enabled: boolean) => templatesApi.setEnabled(enabled),
    meta: { errorMessage: 'Не удалось переключить шаблоны' },
    onSuccess: () => {
      // `/me` живёт 5 минут — без этого пункт меню и режим «По шаблону»
      // появлялись бы у самого админа с опозданием (у гонки так и было).
      qc.invalidateQueries({ queryKey: ['me'] })
      qc.invalidateQueries({ queryKey: templateKeys.all })
    },
  })
}

export function useCreateTemplate() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: TemplateCreateBody) => templatesApi.create(body),
    meta: { errorMessage: 'Не удалось создать шаблон' },
    onSuccess: () => qc.invalidateQueries({ queryKey: templateKeys.all }),
  })
}

export function useSetTemplateAnchor(templateId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (anchorOn: string) => templatesApi.setAnchor(templateId, anchorOn),
    meta: { errorMessage: 'Не удалось изменить точку отсчёта' },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: projectKeys.detail(templateId) })
      qc.invalidateQueries({ queryKey: templateKeys.all })
    },
  })
}

export function useSaveAsTemplatePreview(projectId: string, enabled: boolean) {
  return useQuery({
    queryKey: templateKeys.saveAsPreview(projectId),
    queryFn: () => templatesApi.saveAsPreview(projectId),
    enabled,
    // Предпросмотр — снимок на момент открытия диалога; устаревший между
    // открытиями он не должен показывать.
    gcTime: 0,
  })
}

export function useSaveAsTemplate(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: SaveAsTemplateBody) => templatesApi.saveAs(projectId, body),
    meta: { errorMessage: 'Не удалось сохранить шаблон' },
    onSuccess: () => qc.invalidateQueries({ queryKey: templateKeys.all }),
  })
}

export function useTemplatePreview(templateId: string | null, startOn: string | null) {
  return useQuery({
    queryKey: templateKeys.preview(templateId ?? '', startOn),
    queryFn: () => templatesApi.preview(templateId ?? '', startOn),
    enabled: templateId !== null,
    gcTime: 0,
  })
}

export function useCreateProjectFromTemplate() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ templateId, body }: { templateId: string; body: ProjectFromTemplateBody }) =>
      templatesApi.createProject(templateId, body),
    meta: { errorMessage: 'Не удалось создать проект по шаблону' },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: projectKeys.all })
      qc.invalidateQueries({ queryKey: templateKeys.all })
      // Создающий может оказаться исполнителем — задачи сразу в «Моих».
      qc.invalidateQueries({ queryKey: ['me-tasks'] })
      qc.invalidateQueries({ queryKey: ['me-stats'] })
    },
  })
}
