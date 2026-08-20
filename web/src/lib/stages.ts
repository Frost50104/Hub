import { api } from './api'
import { type TaskStatus } from './tasks'

/**
 * Этапы проекта — колонки доски с пользовательскими именами (волна 2).
 * Каждый этап привязан к системному статусу; `tasks.status` — зеркало.
 * Имя/статус этапа фронт берёт из одного запроса на проект (`useStages`),
 * а не из каждой задачи.
 */
export interface TaskStage {
  id: string
  project_id: string
  name: string
  system_status: TaskStatus
  position: number
  created_at: string
  /** Неархивных задач верхнего уровня в этапе — для «N из M». Только из списка. */
  task_count?: number | null
}

export interface StageCreateBody {
  name: string
  system_status: TaskStatus
  position?: number
}

export interface StageUpdateBody {
  name?: string
  system_status?: TaskStatus
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

/** Первый по позиции этап системного статуса — куда попадает «закрыть»/«вернуть». */
export function firstStageOf(
  stages: TaskStage[] | undefined,
  status: TaskStatus,
): TaskStage | undefined {
  return stages?.find((s) => s.system_status === status)
}

export function stageById(stages: TaskStage[] | undefined, id: string | null | undefined) {
  if (!id) return undefined
  return stages?.find((s) => s.id === id)
}
