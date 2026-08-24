import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from '@tanstack/react-query'
import { toast } from 'sonner'

import { taskAssignees } from '@/lib/taskAssignees'
import {
  tasksApi,
  type Task,
  type TaskAssigneeBrief,
  type TaskCreateBody,
  type TaskListFilters,
  type TaskUpdateBody,
} from '@/lib/tasks'
import { type TaskStage } from '@/lib/stages'

export const taskKeys = {
  all: ['tasks'] as const,
  list: (projectId: string, filters?: TaskListFilters) =>
    ['tasks', projectId, filters ?? {}] as const,
  detail: (id: string) => ['tasks', 'detail', id] as const,
}

export function useTasks(
  projectId: string | undefined,
  filters?: TaskListFilters,
): UseQueryResult<Task[]> {
  return useQuery({
    queryKey: projectId ? taskKeys.list(projectId, filters) : ['tasks', 'none'],
    queryFn: () => tasksApi.list(projectId!, filters),
    enabled: !!projectId,
  })
}

export function useTask(id: string | undefined): UseQueryResult<Task> {
  return useQuery({
    queryKey: id ? taskKeys.detail(id) : ['tasks', 'none-detail'],
    queryFn: () => tasksApi.get(id!),
    enabled: !!id,
  })
}

export function useCreateTask(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: TaskCreateBody) => tasksApi.create(projectId, body),
    meta: { errorMessage: 'Не удалось создать задачу' },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['tasks', projectId] })
      // «N задач» в шапке и списке проектов считает сервер по списку —
      // без инвалидации шапка держала «0 задач» до рефетча (QA-0821 #6).
      qc.invalidateQueries({ queryKey: ['projects'] })
      // Задача, созданная сразу с исполнителем, обязана появиться в «Моих
      // задачах» — раньше она ждала staleTime/фокуса окна.
      qc.invalidateQueries({ queryKey: ['me-tasks'] })
    },
  })
}

/** Поля, которых нет в теле запроса, но которые надо положить в кэш сразу:
 *  тело шлёт `assignee_ids`, а рендер читает `assignees` (brief'ы). Без этого
 *  стек аватаров не обновлялся бы до рефетча. */
export type UpdateVars = TaskUpdateBody & {
  id: string
  __optimistic?: Partial<Task>
}

export function useUpdateTask(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    // __optimistic обязан отрезаться здесь — иначе улетит в тело PATCH.
    mutationFn: ({ id, __optimistic: _drop, ...body }: UpdateVars) =>
      tasksApi.update(id, body),
    meta: { errorMessage: 'Не удалось обновить задачу' },
    // Оптимистично: патчим все кэши списков (включая calendar-варианты и
    // «Мои задачи») и карточку сразу, откатываем из снапшота при ошибке.
    onMutate: async ({ id, __optimistic, ...body }) => {
      await Promise.all([
        qc.cancelQueries({ queryKey: ['tasks', projectId] }),
        qc.cancelQueries({ queryKey: ['me-tasks'] }),
        qc.cancelQueries({ queryKey: taskKeys.detail(id) }),
      ])
      const patch: Partial<Task> = { ...(body as Partial<Task>), ...__optimistic }
      // Зеркало этапа: патч {stage_id} без status оставил бы иконку статуса и
      // зачёркивание старыми до рефетча — дополняем из кэша этапов проекта.
      // И наоборот: legacy {status} кладёт в первый этап этого статуса.
      const stages = qc.getQueryData<TaskStage[]>(['stages', projectId])
      if (stages) {
        if (patch.stage_id && patch.status === undefined) {
          const st = stages.find((s) => s.id === patch.stage_id)
          if (st) patch.status = st.system_status
        } else if (patch.status && patch.stage_id === undefined) {
          const st = stages.find((s) => s.system_status === patch.status)
          if (st) patch.stage_id = st.id
        }
      }
      const apply = (old: Task[] | undefined) =>
        old?.map((t) => (t.id === id ? { ...t, ...patch } : t))

      const prevLists = qc.getQueriesData<Task[]>({ queryKey: ['tasks', projectId] })
      const prevMy = qc.getQueriesData<Task[]>({ queryKey: ['me-tasks'] })
      const prevDetail = qc.getQueryData<Task>(taskKeys.detail(id))

      qc.setQueriesData<Task[]>({ queryKey: ['tasks', projectId] }, apply)
      qc.setQueriesData<Task[]>({ queryKey: ['me-tasks'] }, apply)
      if (prevDetail) {
        qc.setQueryData<Task>(taskKeys.detail(id), { ...prevDetail, ...patch })
      }
      return { prevLists, prevMy, prevDetail, id }
    },
    onError: (_err, _vars, ctx) => {
      if (!ctx) return
      for (const [key, data] of [...ctx.prevLists, ...ctx.prevMy]) {
        qc.setQueryData(key, data)
      }
      if (ctx.prevDetail) {
        qc.setQueryData(taskKeys.detail(ctx.id), ctx.prevDetail)
      }
    },
    // Сервер мог поменять больше, чем мы патчили (completed_at, position
    // при смене статуса) — сверяемся в любом исходе.
    onSettled: (_data, _err, vars) => {
      qc.invalidateQueries({ queryKey: ['tasks', projectId] })
      qc.invalidateQueries({ queryKey: ['me-tasks'] })
      qc.invalidateQueries({ queryKey: taskKeys.detail(vars.id) })
      qc.invalidateQueries({ queryKey: ['task', vars.id, 'activity'] })
      // «N из M» в шапках колонок живёт в кэше этапов; done_count проекта —
      // в его карточке.
      if (vars.stage_id !== undefined || vars.status !== undefined) {
        qc.invalidateQueries({ queryKey: ['stages', projectId] })
        qc.invalidateQueries({ queryKey: ['projects', projectId] })
      }
    },
  })
}

/**
 * Тоггл исполнителя на задаче — по одному человеку за раз.
 *
 * Инкрементальный путь вместо PATCH со всем набором: PATCH — это
 * last-writer-wins, и если состав правят двое одновременно, добавленный
 * одним молча исчезает. Оптимистично патчим `assignees` целиком (brief'ы
 * приходят из пикера), поэтому стек аватаров обновляется мгновенно.
 */
export function useToggleAssignee(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      taskId,
      person,
      next,
    }: {
      taskId: string
      person: TaskAssigneeBrief
      /** true — добавить, false — снять. */
      next: boolean
    }) =>
      next
        ? tasksApi.addAssignee(taskId, person.employee_id)
        : tasksApi.removeAssignee(taskId, person.employee_id),
    meta: { errorMessage: 'Не удалось изменить исполнителей' },
    onMutate: async ({ taskId, person, next }) => {
      await Promise.all([
        qc.cancelQueries({ queryKey: ['tasks', projectId] }),
        qc.cancelQueries({ queryKey: ['me-tasks'] }),
        qc.cancelQueries({ queryKey: taskKeys.detail(taskId) }),
      ])
      const patched = (t: Task): Task => {
        const current = taskAssignees(t)
        const assignees = next
          ? current.some((a) => a.employee_id === person.employee_id)
            ? current
            : [...current, person]
          : current.filter((a) => a.employee_id !== person.employee_id)
        const first = assignees[0] ?? null
        return { ...t, assignees, assignee: first, assignee_id: first?.employee_id ?? null }
      }
      const apply = (old: Task[] | undefined) =>
        old?.map((t) => (t.id === taskId ? patched(t) : t))

      const prevLists = qc.getQueriesData<Task[]>({ queryKey: ['tasks', projectId] })
      const prevMy = qc.getQueriesData<Task[]>({ queryKey: ['me-tasks'] })
      const prevDetail = qc.getQueryData<Task>(taskKeys.detail(taskId))

      qc.setQueriesData<Task[]>({ queryKey: ['tasks', projectId] }, apply)
      qc.setQueriesData<Task[]>({ queryKey: ['me-tasks'] }, apply)
      if (prevDetail) {
        qc.setQueryData<Task>(taskKeys.detail(taskId), patched(prevDetail))
      }
      return { prevLists, prevMy, prevDetail, taskId }
    },
    onError: (_err, _vars, ctx) => {
      if (!ctx) return
      for (const [key, data] of [...ctx.prevLists, ...ctx.prevMy]) {
        qc.setQueryData(key, data)
      }
      if (ctx.prevDetail) {
        qc.setQueryData(taskKeys.detail(ctx.taskId), ctx.prevDetail)
      }
    },
    onSettled: (_data, _err, vars) => {
      qc.invalidateQueries({ queryKey: ['tasks', projectId] })
      qc.invalidateQueries({ queryKey: ['me-tasks'] })
      qc.invalidateQueries({ queryKey: taskKeys.detail(vars.taskId) })
      qc.invalidateQueries({ queryKey: ['task', vars.taskId, 'activity'] })
    },
  })
}

/**
 * Тоггл «готово» с undo-тостом (как в Asana). Возвращает колбэк для
 * чекбоксов в списках/карточках; предыдущий статус восстанавливается
 * кнопкой «Отменить».
 */
/**
 * «Закрыть»/«вернуть» задачу — в ПЕРВЫЙ этап статуса done/todo; отмена
 * возвращает исходный ЭТАП (не только статус): у проекта может быть
 * несколько этапов одного статуса, и «Проверка ТУ» после undo не должна
 * превращаться в «На проверке».
 */
export function useToggleDone(projectId: string) {
  const update = useUpdateTask(projectId)
  const qc = useQueryClient()
  return (task: Pick<Task, 'id' | 'status'> & { stage_id?: string | null }) => {
    const stages = qc.getQueryData<TaskStage[]>(['stages', projectId])
    const next = task.status === 'done' ? 'todo' : 'done'
    const target = stages?.find((s) => s.system_status === next)
    update.mutate(target ? { id: task.id, stage_id: target.id } : { id: task.id, status: next })
    if (next === 'done') {
      toast.success('Задача завершена', {
        action: {
          label: 'Отменить',
          onClick: () =>
            update.mutate(
              task.stage_id
                ? { id: task.id, stage_id: task.stage_id }
                : { id: task.id, status: task.status },
            ),
        },
      })
    }
  }
}

export function useArchiveTask(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, archive }: { id: string; archive: boolean }) =>
      archive ? tasksApi.archive(id) : tasksApi.unarchive(id),
    meta: { errorMessage: 'Не удалось обновить задачу' },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['tasks', projectId] })
      qc.invalidateQueries({ queryKey: ['me-tasks'] })
      qc.invalidateQueries({ queryKey: ['projects', projectId] })
    },
  })
}

export function useDeleteTask(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => tasksApi.remove(id),
    meta: { errorMessage: 'Не удалось удалить задачу' },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['tasks', projectId] })
      qc.invalidateQueries({ queryKey: ['projects'] })
    },
  })
}
