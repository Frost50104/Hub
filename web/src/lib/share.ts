import { api } from './api'

export interface ShareResponse {
  id: string
  scope: 'task' | 'project'
  entity_id: string
  token: string
  url: string
  created_at: string
  expires_at: string | null
  revoked_at: string | null
}

export const shareApi = {
  createForProject: (
    projectId: string,
    body: { expires_at?: string | null } = {},
  ): Promise<ShareResponse> =>
    api
      .post<ShareResponse>(`/projects/${projectId}/share`, body)
      .then((r) => r.data),
  createForTask: (
    taskId: string,
    body: { expires_at?: string | null } = {},
  ): Promise<ShareResponse> =>
    api.post<ShareResponse>(`/tasks/${taskId}/share`, body).then((r) => r.data),
  listForProject: (projectId: string): Promise<ShareResponse[]> =>
    api
      .get<ShareResponse[]>(`/projects/${projectId}/shares`)
      .then((r) => r.data),
  listForTask: (taskId: string): Promise<ShareResponse[]> =>
    api.get<ShareResponse[]>(`/tasks/${taskId}/shares`).then((r) => r.data),
  revoke: (token: string): Promise<void> =>
    api.delete(`/share/${token}`).then(() => undefined),
}
