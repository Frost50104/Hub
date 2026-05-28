import { api } from './api'

export interface Comment {
  id: string
  task_id: string
  author_id: string
  body: string
  mentioned_ids: string[]
  edited_at: string | null
  created_at: string
  author_email: string | null
  author_full_name: string | null
}

export type WatcherReason = 'assignee' | 'creator' | 'mentioned' | 'manual'

export interface Watcher {
  employee_id: string
  added_reason: WatcherReason
  added_at: string
  email: string | null
  full_name: string | null
}

export interface Activity {
  id: number
  task_id: string
  actor_id: string
  kind: string
  payload: Record<string, unknown> | null
  created_at: string
  actor_email: string | null
  actor_full_name: string | null
}

export const commentsApi = {
  list: (taskId: string): Promise<Comment[]> =>
    api.get<Comment[]>(`/tasks/${taskId}/comments`).then((r) => r.data),
  create: (taskId: string, body: string): Promise<Comment> =>
    api.post<Comment>(`/tasks/${taskId}/comments`, { body }).then((r) => r.data),
  update: (commentId: string, body: string): Promise<Comment> =>
    api.patch<Comment>(`/comments/${commentId}`, { body }).then((r) => r.data),
  remove: (commentId: string): Promise<void> =>
    api.delete(`/comments/${commentId}`).then(() => undefined),
}

export const watchersApi = {
  list: (taskId: string): Promise<Watcher[]> =>
    api.get<Watcher[]>(`/tasks/${taskId}/watchers`).then((r) => r.data),
  join: (taskId: string): Promise<Watcher> =>
    api.post<Watcher>(`/tasks/${taskId}/watchers/me`).then((r) => r.data),
  leave: (taskId: string): Promise<void> =>
    api.delete(`/tasks/${taskId}/watchers/me`).then(() => undefined),
}

export const activityApi = {
  list: (taskId: string): Promise<Activity[]> =>
    api.get<Activity[]>(`/tasks/${taskId}/activity`).then((r) => r.data),
}
