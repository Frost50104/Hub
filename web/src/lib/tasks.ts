import { api } from './api'

export type TaskStatus = 'todo' | 'in_progress' | 'in_review' | 'done'
export type TaskPriority = 'low' | 'medium' | 'high' | 'urgent'

export interface TaskAssigneeBrief {
  employee_id: string
  email: string | null
  full_name: string | null
}

export interface Task {
  id: string
  project_id: string
  section_id: string | null
  parent_task_id: string | null
  title: string
  description: string | null
  status: TaskStatus
  priority: TaskPriority
  assignee_id: string | null
  assignee: TaskAssigneeBrief | null
  created_by: string
  start_at: string | null
  due_at: string | null
  position: string | number
  created_at: string
  updated_at: string
  completed_at: string | null
  archived_at: string | null
}

export type TaskSortField = 'position' | 'due_at' | 'priority' | 'created_at' | 'title'

/** Счётчик подзадач для чипа «k/N» на строке/карточке родителя. */
export interface SubtaskStats {
  total: number
  done: number
}

export interface TaskListFilters {
  include_archived?: boolean
  status?: TaskStatus
  assignee?: string
  section_id?: string
  priority?: TaskPriority
  /** id метки — задачи, на которых она висит. */
  label?: string
  /** ISO datetime — сервер сравнивает с due_at. */
  due_from?: string
  due_to?: string
  sort?: TaskSortField
  order?: 'asc' | 'desc'
}

/** Фильтры, применимые к calendar-эндпоинту (диапазон дат у него свой). */
export interface CalendarFilters {
  status?: TaskStatus
  assignee?: string
  priority?: TaskPriority
}

export interface TaskCreateBody {
  title: string
  description?: string
  section_id?: string | null
  parent_task_id?: string
  status?: TaskStatus
  priority?: TaskPriority
  assignee_id?: string | null
  start_at?: string | null
  due_at?: string | null
}

export interface TaskUpdateBody {
  title?: string
  description?: string
  section_id?: string | null
  status?: TaskStatus
  priority?: TaskPriority
  assignee_id?: string | null
  start_at?: string | null
  due_at?: string | null
  position?: string | number
}

export interface CalendarRange {
  /** Inclusive YYYY-MM-DD. */
  from: string
  /** Inclusive YYYY-MM-DD. */
  to: string
}

export const tasksApi = {
  list: (projectId: string, filters?: TaskListFilters): Promise<Task[]> =>
    api.get<Task[]>(`/projects/${projectId}/tasks`, { params: filters }).then((r) => r.data),
  get: (id: string): Promise<Task> => api.get<Task>(`/tasks/${id}`).then((r) => r.data),
  create: (projectId: string, body: TaskCreateBody): Promise<Task> =>
    api.post<Task>(`/projects/${projectId}/tasks`, body).then((r) => r.data),
  update: (id: string, body: TaskUpdateBody): Promise<Task> =>
    api.patch<Task>(`/tasks/${id}`, body).then((r) => r.data),
  archive: (id: string): Promise<Task> =>
    api.post<Task>(`/tasks/${id}/archive`).then((r) => r.data),
  unarchive: (id: string): Promise<Task> =>
    api.post<Task>(`/tasks/${id}/unarchive`).then((r) => r.data),
  remove: (id: string): Promise<void> =>
    api.delete(`/tasks/${id}`).then(() => undefined),
  calendar: (
    projectId: string,
    range: CalendarRange,
    filters?: CalendarFilters,
  ): Promise<Task[]> =>
    api
      .get<Task[]>(`/projects/${projectId}/tasks/calendar`, {
        params: { ...range, ...filters },
      })
      .then((r) => r.data),
}

export const STATUS_LABEL: Record<TaskStatus, string> = {
  todo: 'К выполнению',
  in_progress: 'В работе',
  in_review: 'На проверке',
  done: 'Готово',
}

export const PRIORITY_LABEL: Record<TaskPriority, string> = {
  low: 'низкий',
  medium: 'средний',
  high: 'высокий',
  urgent: 'срочно',
}
