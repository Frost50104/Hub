import { api } from './api'

export type TaskPriority = 'low' | 'medium' | 'high' | 'urgent'

export interface TaskAssigneeBrief {
  employee_id: string
  email: string | null
  full_name: string | null
}

export interface Task {
  id: string
  project_id: string
  parent_task_id: string | null
  title: string
  description: string | null
  /** Состояние задачи (0044). Колонка доски к нему отношения не имеет. */
  done: boolean
  /** Колонка доски. `null` — «без статуса»: задача есть в списке, календаре
   *  и поиске, но на доске её нет (0046). Поле необязательное ещё и потому,
   *  что объект из кэша старого бандла его не несёт. */
  stage_id?: string | null
  priority: TaskPriority
  /** Источник истины по исполнителям. Optional: объекта из кэша, пережившего
   *  деплой (или из ответа откаченного бэка) поля не будет — читать ТОЛЬКО
   *  через `taskAssignees()`, иначе `.map` упадёт в рантайме. */
  assignees?: TaskAssigneeBrief[]
  /** @deprecated Первый из `assignees`. Оставлено для старых PWA-бандлов. */
  assignee_id: string | null
  /** @deprecated Первый из `assignees`. */
  assignee: TaskAssigneeBrief | null
  created_by: string
  start_at: string | null
  due_at: string | null
  position: string | number
  /** Номер в проекте («KEY-42»). Optional: optimistic-объекты его не знают —
   * бейдж просто не рендерится до ответа сервера. */
  seq?: number
  /** Ключ проекта — заполняют только кросс-проектные ручки (/me/tasks);
   * в контексте страницы проекта фронт берёт key из project-запроса. */
  project_key?: string | null
  /** Имя колонки доски — тоже только кросс-проектные ручки: колонки чужого
   *  проекта фронту взять неоткуда (`useStages` — на текущий проект). */
  stage_name?: string | null
  created_at: string
  updated_at: string
  completed_at: string | null
  archived_at: string | null
  /** Может ли текущий пользователь закрыть задачу и двигать её по доске:
   *  сервер считает роль в проекте ПЛЮС «я среди исполнителей». Заполняют
   *  только список задач проекта и карточка задачи; `undefined` — «не знаем»,
   *  решает общий can_edit проекта. Ответ PATCH поле не несёт — и не должен:
   *  в кэш кладётся сам патч, а не ответ (useTasks.ts). */
  can_complete?: boolean | null
  /** Счётчики строки контекста в списке. Заполняет ТОЛЬКО список задач проекта;
   *  у одиночных ручек и оптимистичных объектов их нет. `undefined` = «не знаем,
   *  чип не рисуем», `0` = «знаем, что нет» — иначе чип мигал бы при каждом
   *  оптимистичном обновлении. */
  comment_count?: number | null
  attachment_count?: number | null
  blocker_count?: number | null
}

/** «KEY-42» или null, если чего-то не хватает (optimistic-объект, нет key). */
export function taskKey(
  projectKey: string | null | undefined,
  seq: number | null | undefined,
): string | null {
  return projectKey && seq != null ? `${projectKey}-${seq}` : null
}

export type TaskSortField = 'position' | 'due_at' | 'priority' | 'created_at' | 'title'

/** Счётчик подзадач для чипа «k/N» на строке/карточке родителя. */
export interface SubtaskStats {
  total: number
  done: number
}

export interface TaskListFilters {
  include_archived?: boolean
  /** `false` — невыполненные, `true` — выполненные, отсутствие — все. */
  done?: boolean
  assignee?: string
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
  done?: boolean
  assignee?: string
  priority?: TaskPriority
}

export interface TaskCreateBody {
  /** Колонка; без неё сервер кладёт задачу в первую по позиции. */
  stage_id?: string | null
  title: string
  description?: string
  parent_task_id?: string
  priority?: TaskPriority
  assignee_id?: string | null
  assignee_ids?: string[]
  start_at?: string | null
  due_at?: string | null
}

export interface TaskUpdateBody {
  /** Колонка доски. Явный `null` — прочерк в поле «Статус»: задача уходит
   *  с доски, оставаясь в списке и поиске (0046). Не передать поле и
   *  передать null — разные вещи. */
  stage_id?: string | null
  title?: string
  description?: string
  /** Выполнена или нет — независимо от колонки. */
  done?: boolean
  priority?: TaskPriority
  /** @deprecated Прислать легаси-поле = заменить весь набор одним человеком. */
  assignee_id?: string | null
  /** Полная замена набора. Для точечных правок — addAssignee/removeAssignee. */
  assignee_ids?: string[]
  start_at?: string | null
  due_at?: string | null
  position?: string | number
}

/** Ответ `move-preview` и `move` — один силуэт на «что будет» и «что стало».
 *  Считает их один и тот же код на сервере (`services/task_move.py`), поэтому
 *  и тип один: разные формы развели бы текст диалога с текстом тоста. */
export interface TaskMoveReport {
  project_id: string
  project_name: string
  /** «KEY-42» в новом проекте. `null` у предпросмотра: номер выдаёт только сам
   *  перенос, а показывать несуществующий номер нельзя. */
  new_key: string | null
  subtasks: number
  labels_kept: number
  labels_total: number
  values_kept: number
  values_total: number
  watchers_dropped: number
  dependencies_dropped: number
  shares_revoked: number
  /** У цели активна публичная ссылка на проект — задача станет видна по ней
   *  анонимам, хотя публиковать её отдельно никто не просил. */
  target_public: boolean
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
  /** Импорт из CSV: dry_run — разбор и отчёт без записи. */
  importCsv: (
    projectId: string,
    file: File,
    opts: { dryRun: boolean },
  ): Promise<TaskImportReport> => {
    const form = new FormData()
    form.append('file', file)
    return api
      .post<TaskImportReport>(`/projects/${projectId}/tasks/import`, form, {
        params: { dry_run: opts.dryRun },
      })
      .then((r) => r.data)
  },
  create: (projectId: string, body: TaskCreateBody): Promise<Task> =>
    api.post<Task>(`/projects/${projectId}/tasks`, body).then((r) => r.data),
  update: (id: string, body: TaskUpdateBody): Promise<Task> =>
    api.patch<Task>(`/tasks/${id}`, body).then((r) => r.data),
  /** Что случится при переносе. `stage_id` уходит только непустым: у null
   *  axios сериализует `stage_id=`, а FastAPI ждёт UUID и отвечает 422. */
  movePreview: (
    id: string,
    projectId: string,
    stageId: string | null,
  ): Promise<TaskMoveReport> =>
    api
      .get<TaskMoveReport>(`/tasks/${id}/move-preview`, {
        params: { project_id: projectId, stage_id: stageId ?? undefined },
      })
      .then((r) => r.data),
  move: (
    id: string,
    body: { project_id: string; stage_id: string | null },
  ): Promise<TaskMoveReport> =>
    api.post<TaskMoveReport>(`/tasks/${id}/move`, body).then((r) => r.data),
  archive: (id: string): Promise<Task> =>
    api.post<Task>(`/tasks/${id}/archive`).then((r) => r.data),
  unarchive: (id: string): Promise<Task> =>
    api.post<Task>(`/tasks/${id}/unarchive`).then((r) => r.data),
  remove: (id: string): Promise<void> =>
    api.delete(`/tasks/${id}`).then(() => undefined),
  // Инкрементальные правки состава: PATCH с полным списком — это
  // last-writer-wins, и параллельное добавление другим человеком терялось бы.
  addAssignee: (taskId: string, employeeId: string): Promise<Task> =>
    api
      .post<Task>(`/tasks/${taskId}/assignees`, { employee_id: employeeId })
      .then((r) => r.data),
  removeAssignee: (taskId: string, employeeId: string): Promise<Task> =>
    api
      .delete<Task>(`/tasks/${taskId}/assignees/${employeeId}`)
      .then((r) => r.data),
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

export interface TaskImportReport {
  created: number
  skipped: number
  errors: string[]
  dry_run: boolean
}

/** Подписи фильтра состояния: «Не выполнено» первым — главный срез списка. */
export const DONE_FILTER_LABEL: Record<'open' | 'done', string> = {
  open: 'Не выполнено',
  done: 'Выполнено',
}

export const PRIORITY_LABEL: Record<TaskPriority, string> = {
  low: 'низкий',
  medium: 'средний',
  high: 'высокий',
  urgent: 'срочно',
}
