/** HTTP-клиент шаблонов проектов (0060). Чистые правила — `projectTemplates.ts`:
 *  vitest бежит без jsdom, а `api` тянет браузерный auth-клиент. */

import { api } from '@/lib/api'
import type {
  CopyPreview,
  CopyReport,
  ProjectFromTemplateBody,
  SaveAsTemplateBody,
  TemplateCreateBody,
  TemplateListItem,
  TemplateSettings,
} from '@/lib/projectTemplates'
import type { Project } from '@/lib/projects'

export const templatesApi = {
  list: (): Promise<TemplateListItem[]> =>
    api.get<TemplateListItem[]>('/templates').then((r) => r.data),
  create: (body: TemplateCreateBody): Promise<Project> =>
    api.post<Project>('/templates', body).then((r) => r.data),
  setAnchor: (id: string, anchorOn: string): Promise<Project> =>
    api.patch<Project>(`/templates/${id}`, { anchor_on: anchorOn }).then((r) => r.data),
  saveAsPreview: (projectId: string): Promise<CopyPreview> =>
    api.get<CopyPreview>(`/projects/${projectId}/template-preview`).then((r) => r.data),
  saveAs: (projectId: string, body: SaveAsTemplateBody): Promise<Project> =>
    api.post<Project>(`/projects/${projectId}/save-as-template`, body).then((r) => r.data),
  preview: (id: string, startOn: string | null): Promise<CopyPreview> =>
    api
      .get<CopyPreview>(`/templates/${id}/preview`, {
        params: startOn ? { start_on: startOn } : {},
      })
      .then((r) => r.data),
  createProject: (
    id: string,
    body: ProjectFromTemplateBody,
  ): Promise<{ project: Project; report: CopyReport }> =>
    api
      .post<{ project: Project; report: CopyReport }>(`/templates/${id}/projects`, body)
      .then((r) => r.data),
  settings: (): Promise<TemplateSettings> =>
    api.get<TemplateSettings>('/templates/settings').then((r) => r.data),
  setEnabled: (enabled: boolean): Promise<TemplateSettings> =>
    api.put<TemplateSettings>('/templates/settings', { enabled }).then((r) => r.data),
}
