import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from '@tanstack/react-query'
import { toast } from 'sonner'

import { taskAssignees } from '@/lib/taskAssignees'
import { humanDate } from '@/lib/taskDates'
import type { RecurrenceFreq } from '@/lib/taskRecurrence'
import {
  tasksApi,
  type Task,
  type TaskAssigneeBrief,
  type TaskCreateBody,
  type TaskListFilters,
  type TaskUpdateBody,
} from '@/lib/tasks'

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
      // «Ваша статистика» на «Главной» считается на сервере — своей
      // оптимистики у неё нет, только пересчёт.
      qc.invalidateQueries({ queryKey: ['me-stats'] })
      // «N из M» в шапке колонки живёт в кэше этапов (`stage.task_count`):
      // без инвалидации первая же задача в пустой колонке даёт «1 из 0».
      qc.invalidateQueries({ queryKey: ['stages', projectId] })
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

/**
 * Корни кэша трекера, которые задевает переезд задачи.
 *
 * Перечислять ключи по одному тут нельзя: переезд меняет ДВА проекта разом и
 * трогает десять корней — списки и карточку (`tasks`), ленту, комментарии и
 * наблюдателей (`task`), счётчики проектов, колонки, метки, кастом-поля,
 * зависимости, «Мои задачи», статистику «Главной» и хронологию. Забытый корень
 * оставит экран со старыми данными, и выглядеть это будет как «перенос не
 * сработал», хотя сервер отработал.
 */
const MOVE_TOUCHES = [
  'tasks',
  'task',
  'projects',
  'stages',
  'labels',
  'custom-fields',
  'dependencies',
  'me-tasks',
  'me-stats',
  'timeline',
]

/** Перенос задачи в другой проект. Оптимистики нет сознательно: переезд меняет
 *  номер, колонку, метки и значения полей — угадать результат нечем, а
 *  соврать на секунду тут дороже, чем подождать ответ. */
export function useMoveTask() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...body }: MoveVars) => tasksApi.move(id, body),
    meta: { errorMessage: 'Не удалось перенести задачу' },
    onSuccess: () => {
      qc.invalidateQueries({
        predicate: (q) => MOVE_TOUCHES.includes(String(q.queryKey[0])),
      })
    },
  })
}

interface MoveVars {
  id: string
  project_id: string
  stage_id: string | null
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
      // Зеркала больше нет: колонка и «выполнена» — независимые оси (0044),
      // патч применяется как есть.
      const patch: Partial<Task> = { ...(body as Partial<Task>), ...__optimistic }
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
    // Сервер мог поменять больше, чем мы патчили (completed_at при галочке,
    // position при переносе) — сверяемся в любом исходе.
    onSettled: (_data, _err, vars) => {
      qc.invalidateQueries({ queryKey: ['tasks', projectId] })
      qc.invalidateQueries({ queryKey: ['me-tasks'] })
      // «Ваша статистика» на «Главной» считается на сервере — своей
      // оптимистики у неё нет, только пересчёт.
      qc.invalidateQueries({ queryKey: ['me-stats'] })
      qc.invalidateQueries({ queryKey: taskKeys.detail(vars.id) })
      qc.invalidateQueries({ queryKey: ['task', vars.id, 'activity'] })
      // «N из M» в шапках колонок живёт в кэше этапов; done_count проекта —
      // в его карточке.
      if (vars.stage_id !== undefined || vars.done !== undefined) {
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
      // «Ваша статистика» на «Главной» считается на сервере — своей
      // оптимистики у неё нет, только пересчёт.
      qc.invalidateQueries({ queryKey: ['me-stats'] })
      qc.invalidateQueries({ queryKey: taskKeys.detail(vars.taskId) })
      qc.invalidateQueries({ queryKey: ['task', vars.taskId, 'activity'] })
    },
  })
}

/**
 * Тоггл «выполнена» с undo-тостом (как в Asana).
 *
 * Карточку никуда не двигаем (0044): состояние и колонка — независимые оси,
 * поэтому отмена — это просто обратная галочка, а не возврат в прежний этап.
 */
/**
 * Включить или сменить повтор. Только инвалидация, НИКАКОГО setQueryData из
 * ответа: ответ мутирующей ручки не несёт `can_complete` (см. `_serialize_one`),
 * и положив его в кэш, мы погасили бы чекбокс у исполнителя-viewer сразу после
 * включения повтора.
 */
export function useSetRecurrence(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, freq, step }: { id: string; freq: RecurrenceFreq; step: number }) =>
      tasksApi.setRecurrence(id, { freq, step }),
    meta: { errorMessage: 'Не удалось включить повтор' },
    onSuccess: (_data, vars) => {
      void qc.invalidateQueries({ queryKey: ['tasks', projectId] })
      void qc.invalidateQueries({ queryKey: ['me-tasks'] })
      void qc.invalidateQueries({ queryKey: taskKeys.detail(vars.id) })
      void qc.invalidateQueries({ queryKey: ['task', vars.id, 'activity'] })
    },
  })
}

export function useClearRecurrence(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => tasksApi.clearRecurrence(id),
    meta: { errorMessage: 'Не удалось выключить повтор' },
    onSuccess: (_data, id) => {
      void qc.invalidateQueries({ queryKey: ['tasks', projectId] })
      void qc.invalidateQueries({ queryKey: ['me-tasks'] })
      void qc.invalidateQueries({ queryKey: taskKeys.detail(id) })
      void qc.invalidateQueries({ queryKey: ['task', id, 'activity'] })
    },
  })
}

export function useToggleDone(projectId: string) {
  const update = useUpdateTask(projectId)
  return (task: Pick<Task, 'id' | 'done' | 'recurrence'>) => {
    const next = !task.done
    update.mutate({ id: task.id, done: next })
    if (next && task.recurrence) {
      // «Отменить» здесь ВРЁТ: обратная галочка не удалит уже созданную копию
      // и не вернёт правило — оно переехало на неё. Поэтому у повторяющейся
      // задачи действия нет, зато тост говорит, что дальше.
      toast.success(`Выполнено. Следующая — ${humanDate(task.recurrence.next_due)}`)
    } else if (next) {
      toast.success('Задача выполнена', {
        action: {
          label: 'Отменить',
          onClick: () => update.mutate({ id: task.id, done: false }),
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
      // «Ваша статистика» на «Главной» считается на сервере — своей
      // оптимистики у неё нет, только пересчёт.
      qc.invalidateQueries({ queryKey: ['me-stats'] })
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
      // `me-tasks` тут не хватало: удалённая задача висела на «Моих задачах»
      // до протухания кэша. `me-stats` — по той же причине.
      qc.invalidateQueries({ queryKey: ['me-tasks'] })
      qc.invalidateQueries({ queryKey: ['me-stats'] })
      qc.invalidateQueries({ queryKey: ['projects'] })
      // Та же причина, что и в create: иначе «N из M» колонки считает
      // удалённую задачу до перезагрузки страницы.
      qc.invalidateQueries({ queryKey: ['stages', projectId] })
    },
  })
}
