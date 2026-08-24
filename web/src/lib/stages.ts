import { api } from './api'

/**
 * Колонки доски (0044). Колонка — это только имя и позиция: системного
 * смысла у неё нет, состояние задачи живёт в `task.done`. Имя колонки фронт
 * берёт из одного запроса на проект (`useStages`), а не из каждой задачи.
 */
export interface TaskStage {
  id: string
  project_id: string
  name: string
  position: number
  created_at: string
  /** Неархивных задач верхнего уровня в этапе — для «N из M». Только из списка. */
  task_count?: number | null
}

export interface StageCreateBody {
  name: string
  position?: number
}

export interface StageUpdateBody {
  name?: string
  position?: number
}

export const stagesApi = {
  list: (projectId: string): Promise<TaskStage[]> =>
    api.get<TaskStage[]>(`/projects/${projectId}/stages`).then((r) => r.data),
  create: (projectId: string, body: StageCreateBody): Promise<TaskStage> =>
    api.post<TaskStage>(`/projects/${projectId}/stages`, body).then((r) => r.data),
  update: (stageId: string, body: StageUpdateBody): Promise<TaskStage> =>
    api.patch<TaskStage>(`/stages/${stageId}`, body).then((r) => r.data),
  remove: (stageId: string, moveTo?: string | null): Promise<void> =>
    api
      .delete(`/stages/${stageId}`, { params: moveTo ? { move_to: moveTo } : undefined })
      .then(() => undefined),
}

/** Первая колонка проекта — дом для задачи, созданной без явной колонки. */
export function firstStage(stages: TaskStage[] | undefined): TaskStage | undefined {
  return stages?.[0]
}

export function stageById(stages: TaskStage[] | undefined, id: string | null | undefined) {
  if (!id) return undefined
  return stages?.find((s) => s.id === id)
}
