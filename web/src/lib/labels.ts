import { api } from './api'

export interface Label {
  id: string
  project_id: string
  name: string
  color: string
}

export interface LabelAssignment {
  task_id: string
  label_id: string
}

export interface LabelCreateBody {
  name: string
  color?: string
}

export interface LabelUpdateBody {
  name?: string
  color?: string
}

export const labelsApi = {
  list: (projectId: string): Promise<Label[]> =>
    api.get<Label[]>(`/projects/${projectId}/labels`).then((r) => r.data),
  /** Все назначения проекта одним запросом — чипы в List/Board без N+1. */
  assignments: (projectId: string): Promise<LabelAssignment[]> =>
    api
      .get<LabelAssignment[]>(`/projects/${projectId}/label-assignments`)
      .then((r) => r.data),
  create: (projectId: string, body: LabelCreateBody): Promise<Label> =>
    api.post<Label>(`/projects/${projectId}/labels`, body).then((r) => r.data),
  update: (projectId: string, labelId: string, body: LabelUpdateBody): Promise<Label> =>
    api
      .patch<Label>(`/projects/${projectId}/labels/${labelId}`, body)
      .then((r) => r.data),
  remove: (projectId: string, labelId: string): Promise<void> =>
    api.delete(`/projects/${projectId}/labels/${labelId}`).then(() => undefined),
  assign: (taskId: string, labelId: string): Promise<void> =>
    api.put(`/tasks/${taskId}/labels/${labelId}`).then(() => undefined),
  unassign: (taskId: string, labelId: string): Promise<void> =>
    api.delete(`/tasks/${taskId}/labels/${labelId}`).then(() => undefined),
}
