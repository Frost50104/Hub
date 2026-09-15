/**
 * Секция «ЛИЧНОЕ» на «Моих задачах»: вся условная логика без React.
 *
 * Компонент остаётся раскладкой — соглашение проекта (эталон пары
 * `inlineDraft.ts` ↔ `TaskInlineCreate.tsx`): jsdom в проекте нет, тестируются
 * только чистые функции.
 */

import { type SubtaskStats, type Task } from './tasks'

/** Сколько выполненных личных задач показываем без «показать все». */
export const DONE_PREVIEW_LIMIT = 3

/**
 * Выкинуть задачи личного проекта из кросс-проектного списка.
 *
 * Личная задача не должна стоять на экране дважды — в секции «ЛИЧНОЕ» и в окне
 * дедлайнов. Основной фильтр серверный (`/me/tasks?include_personal=false`);
 * это страховка на окно деплоя, когда новый бандл живёт со старым бэкендом.
 */
export function excludeProject<T extends Pick<Task, 'project_id'>>(
  tasks: readonly T[],
  projectId: string | null | undefined,
): T[] {
  if (!projectId) return [...tasks]
  return tasks.filter((t) => t.project_id !== projectId)
}

export interface PersonalListView<T> {
  /** Верхнеуровневые незавершённые, в порядке ответа сервера. */
  open: T[]
  /** Выполненные, обрезанные до лимита. */
  done: T[]
  /** Сколько выполненных скрыто за «Показать все выполненные». */
  hiddenDone: number
  /** Для шапки: «3 · 1 выполнено». */
  counts: { open: number; done: number }
  /** Чип «k/N» у родителя: подзадачи приезжают тем же ответом. */
  subtasksByParent: Map<string, SubtaskStats>
}

/**
 * Разложить ответ `GET /projects/{personal}/tasks` в то, что рисует секция.
 *
 * Подзадачи в строки не попадают (как на странице проекта), но считаются в чип
 * родителя. Выполненные тонут вниз и по умолчанию урезаются: личный список —
 * это inbox, за полгода под инпутом накопилась бы стена «Готово». Сколько
 * именно показывать, решает вызывающий: секция «ЛИЧНОЕ» передаёт `doneLimit: 0`
 * и раскрывает их чипом.
 */
export function personalListView<
  T extends Pick<Task, 'id' | 'done' | 'parent_task_id'>,
>(
  tasks: readonly T[] | undefined,
  opts: { doneLimit?: number; showAllDone?: boolean } = {},
): PersonalListView<T> {
  const { doneLimit = DONE_PREVIEW_LIMIT, showAllDone = false } = opts
  const open: T[] = []
  const done: T[] = []
  const subtasksByParent = new Map<string, SubtaskStats>()

  for (const task of tasks ?? []) {
    if (task.parent_task_id) {
      const stats = subtasksByParent.get(task.parent_task_id) ?? { total: 0, done: 0 }
      stats.total += 1
      if (task.done) stats.done += 1
      subtasksByParent.set(task.parent_task_id, stats)
      continue
    }
    ;(task.done ? done : open).push(task)
  }

  const shown = showAllDone ? done : done.slice(0, doneLimit)
  return {
    open,
    done: shown,
    hiddenDone: done.length - shown.length,
    counts: { open: open.length, done: done.length },
    subtasksByParent,
  }
}

/** Что делать с `?task=` на `/my`. */
export type PersonalTaskParam =
  | { kind: 'none' }
  /** Список ещё грузится — URL не трогаем, иначе потеряем ссылку. */
  | { kind: 'wait' }
  | { kind: 'open'; taskId: string }
  /** Чужая или несуществующая задача — параметр вычистить. */
  | { kind: 'drop' }

/**
 * «Эту задачу мы только что создали»: списка с ней ещё нет, но id заведомо наш
 * и заведомо личный — его вернул POST в этой же вкладке.
 */
export interface JustCreatedHint {
  taskId: string
  /** `Date.now()` в момент создания. */
  at: number
}

/** Хинт живёт минуту: он едет в `history.state` и переживает перезагрузку. */
export const JUST_CREATED_TTL_MS = 60_000

/**
 * Карточку на `/my` открываем ТОЛЬКО для задач личного проекта: у drawer'а
 * `projectId` фиксирован, и для чужой задачи он показал бы чужие этапы,
 * чужую секцию и чужой `can_edit`.
 *
 * `hint` — единственное послабление, и оно НЕ белый список: id обязан совпасть.
 * Без него создание личной задачи молча закрывало бы карточку: `useCreateTask`
 * инвалидирует список с `refetchType: 'active'`, а неактивный кэш только
 * помечается протухшим и на маунте отдаётся синхронно — то есть без новой
 * задачи. Мы попадали в `drop`, и эффект страницы стирал `?task=`. Ждать
 * рефетча негде: тот же промах случается, когда человек УЖЕ на `/my`.
 *
 * `now` параметром — чтобы срок годности проверялся тестом (приём
 * `dates.ts::dataAgeLabel`, `taskDates.ts::todayKey`).
 */
export function resolvePersonalTaskParam(
  taskId: string | null,
  personal: { tasks: readonly Pick<Task, 'id'>[] | undefined; isPending: boolean },
  hint?: JustCreatedHint | null,
  now: number = Date.now(),
): PersonalTaskParam {
  if (!taskId) return { kind: 'none' }
  if (hint && hint.taskId === taskId && now - hint.at < JUST_CREATED_TTL_MS) {
    return { kind: 'open', taskId }
  }
  if (personal.isPending || personal.tasks === undefined) return { kind: 'wait' }
  return personal.tasks.some((t) => t.id === taskId)
    ? { kind: 'open', taskId }
    : { kind: 'drop' }
}

export type PersonalSectionState =
  /** `/me` ещё грузится ИЛИ бэкенд поля не отдал — секции нет вовсе. */
  | { kind: 'hidden' }
  | { kind: 'loading'; projectId: string }
  | { kind: 'error'; projectId: string }
  | { kind: 'ready'; projectId: string; view: PersonalListView<Task> }

export function personalSectionState(input: {
  meIsPending: boolean
  personalProjectId: string | undefined
  isPending: boolean
  isError: boolean
  tasks: Task[] | undefined
  showAllDone: boolean
}): PersonalSectionState {
  const { personalProjectId: projectId } = input
  if (input.meIsPending || !projectId) return { kind: 'hidden' }
  if (input.isError) return { kind: 'error', projectId }
  if (input.isPending || input.tasks === undefined) {
    return { kind: 'loading', projectId }
  }
  return {
    kind: 'ready',
    projectId,
    // `doneLimit: 0` — выполненных в списке по умолчанию НЕТ (ОС 15.09:
    // «в личных показывать по умолчанию не выполненные, а выполненные скрыть
    // за фильтром или чипом»). Дефолт самой `personalListView` (3) не трогаем:
    // на нём стоят её тесты, а решение «сколько показывать» принимает экран.
    view: personalListView(input.tasks, {
      doneLimit: 0,
      showAllDone: input.showAllDone,
    }),
  }
}

/** FAB привёл на `/my` с просьбой поставить курсор в поле создания. */
export function shouldFocusPersonalCreate(params: URLSearchParams): boolean {
  return params.get('new') === 'personal'
}
