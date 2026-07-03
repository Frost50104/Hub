import { api } from './api'

export type ProjectRole = 'owner' | 'editor' | 'viewer'

export const PROJECT_ROLE_LABEL: Record<ProjectRole, string> = {
  owner: 'Владелец',
  editor: 'Редактор',
  viewer: 'Наблюдатель',
}

export interface Project {
  id: string
  key: string
  name: string
  description: string | null
  archived_at: string | null
  created_by: string
  created_at: string
  updated_at: string
  my_role: ProjectRole | null
  /** Личное избранное текущего пользователя. */
  is_favorite: boolean
}

export interface ProjectMember {
  id: string
  employee_id: string
  role: ProjectRole
  added_at: string
  email: string | null
  full_name: string | null
}

export interface Section {
  id: string
  project_id: string
  name: string
  position: number
  created_at: string
}

export interface CreateProjectBody {
  name: string
  /** Optional — backend auto-generates from name if omitted. */
  key?: string
  description?: string
}

export interface UpdateProjectBody {
  name?: string
  description?: string
}

export const projectsApi = {
  list: (includeArchived = false): Promise<Project[]> =>
    api
      .get<Project[]>('/projects', { params: { include_archived: includeArchived } })
      .then((r) => r.data),
  get: (id: string): Promise<Project> =>
    api.get<Project>(`/projects/${id}`).then((r) => r.data),
  create: (body: CreateProjectBody): Promise<Project> =>
    api.post<Project>('/projects', body).then((r) => r.data),
  update: (id: string, body: UpdateProjectBody): Promise<Project> =>
    api.patch<Project>(`/projects/${id}`, body).then((r) => r.data),
  archive: (id: string): Promise<Project> =>
    api.post<Project>(`/projects/${id}/archive`).then((r) => r.data),
  unarchive: (id: string): Promise<Project> =>
    api.post<Project>(`/projects/${id}/unarchive`).then((r) => r.data),
  setFavorite: (id: string, isFavorite: boolean): Promise<Project> =>
    api
      .put<Project>(`/projects/${id}/favorite`, { is_favorite: isFavorite })
      .then((r) => r.data),
}

export const membersApi = {
  list: (projectId: string): Promise<ProjectMember[]> =>
    api.get<ProjectMember[]>(`/projects/${projectId}/members`).then((r) => r.data),
  add: (
    projectId: string,
    body: { employee_id: string; role: ProjectRole },
  ): Promise<ProjectMember> =>
    api.post<ProjectMember>(`/projects/${projectId}/members`, body).then((r) => r.data),
  update: (
    projectId: string,
    memberId: string,
    body: { role: ProjectRole },
  ): Promise<ProjectMember> =>
    api
      .patch<ProjectMember>(`/projects/${projectId}/members/${memberId}`, body)
      .then((r) => r.data),
  remove: (projectId: string, memberId: string): Promise<void> =>
    api.delete(`/projects/${projectId}/members/${memberId}`).then(() => undefined),
}

export const sectionsApi = {
  list: (projectId: string): Promise<Section[]> =>
    api.get<Section[]>(`/projects/${projectId}/sections`).then((r) => r.data),
  create: (
    projectId: string,
    body: { name: string; position?: number },
  ): Promise<Section> =>
    api.post<Section>(`/projects/${projectId}/sections`, body).then((r) => r.data),
  update: (
    sectionId: string,
    body: { name?: string; position?: number },
  ): Promise<Section> =>
    api.patch<Section>(`/sections/${sectionId}`, body).then((r) => r.data),
  remove: (sectionId: string): Promise<void> =>
    api.delete(`/sections/${sectionId}`).then(() => undefined),
}
