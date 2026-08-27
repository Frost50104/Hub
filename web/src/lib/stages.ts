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
  /**
   * Удаление колонки. С задачами внутри выбор обязателен: `moveTo` — перенести,
   * `detach` — оставить их без колонки. Без того и другого сервер отвечает 409
   * — молча снимать колонку у пачки задач нельзя.
   */
  remove: (
    stageId: string,
    opts: { moveTo?: string | null; detach?: boolean } = {},
  ): Promise<void> =>
    api
      .delete(`/stages/${stageId}`, {
        params: {
          ...(opts.moveTo ? { move_to: opts.moveTo } : {}),
          ...(opts.detach ? { detach: true } : {}),
        },
      })
      .then(() => undefined),
}

export function stageById(stages: TaskStage[] | undefined, id: string | null | undefined) {
  if (!id) return undefined
  return stages?.find((s) => s.id === id)
}
