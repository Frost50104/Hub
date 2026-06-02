import { api } from './api'
import { type Task } from './tasks'

export interface TimelineDependency {
  predecessor_id: string
  successor_id: string
  created_at: string
}

export interface TimelineSection {
  id: string
  name: string
  position: number
}

export interface TimelineResponse {
  tasks: Task[]
  dependencies: TimelineDependency[]
  sections: TimelineSection[]
}

export interface DependencyPeer {
  id: string
  title: string
  status: 'todo' | 'in_progress' | 'in_review' | 'done'
}

export interface TaskDependencies {
  predecessors: DependencyPeer[]
  successors: DependencyPeer[]
}

export const timelineApi = {
  get: (projectId: string, range: { from: string; to: string }): Promise<TimelineResponse> =>
    api
      .get<TimelineResponse>(`/projects/${projectId}/timeline`, { params: range })
      .then((r) => r.data),

  taskDependencies: (taskId: string): Promise<TaskDependencies> =>
    api
      .get<TaskDependencies>(`/tasks/${taskId}/dependencies`)
      .then((r) => r.data),
  addDependency: (
    successorId: string,
    predecessorId: string,
  ): Promise<TimelineDependency> =>
    api
      .post<TimelineDependency>(
        `/tasks/${successorId}/dependencies/${predecessorId}`,
      )
      .then((r) => r.data),
  removeDependency: (
    successorId: string,
    predecessorId: string,
  ): Promise<void> =>
    api
      .delete(`/tasks/${successorId}/dependencies/${predecessorId}`)
      .then(() => undefined),
}
