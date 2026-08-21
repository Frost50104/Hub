import { addDaysKey, dayEndIso, dayStartIso, todayKey } from './taskDates'
import {
  type CalendarFilters,
  type Task,
  type TaskListFilters,
  type TaskPriority,
  type TaskSortField,
  type TaskStatusFilter,
} from './tasks'

export type DuePreset = 'today' | 'week' | 'overdue'

/** Состояние фильтр-бара проекта. Живёт в URL searchParams (переживает F5 и шарится ссылкой). */
export interface TaskViewFilters {
  assignee?: string
  status?: TaskStatusFilter
  priority?: TaskPriority
  /** id метки проекта. */
  label?: string
  due?: DuePreset
  sort?: TaskSortField
  order?: 'asc' | 'desc'
}

const STATUSES: TaskStatusFilter[] = ['open', 'todo', 'in_progress', 'in_review', 'done']
const PRIORITIES: TaskPriority[] = ['low', 'medium', 'high', 'urgent']
const DUE_PRESETS: DuePreset[] = ['today', 'week', 'overdue']
const SORTS: TaskSortField[] = ['position', 'due_at', 'priority', 'created_at', 'title']

// URL-ключи с префиксом f_, чтобы не конфликтовать с ?task=
const KEYS = {
  assignee: 'f_assignee',
  status: 'f_status',
  priority: 'f_priority',
  label: 'f_label',
  due: 'f_due',
  sort: 'sort',
  order: 'order',
} as const

function pick<T extends string>(raw: string | null, allowed: readonly T[]): T | undefined {
  return raw && (allowed as readonly string[]).includes(raw) ? (raw as T) : undefined
}

export function filtersFromSearchParams(sp: URLSearchParams): TaskViewFilters {
  return {
    assignee: sp.get(KEYS.assignee) ?? undefined,
    status: pick(sp.get(KEYS.status), STATUSES),
    priority: pick(sp.get(KEYS.priority), PRIORITIES),
    label: sp.get(KEYS.label) ?? undefined,
    due: pick(sp.get(KEYS.due), DUE_PRESETS),
    sort: pick(sp.get(KEYS.sort), SORTS),
    order: pick(sp.get(KEYS.order), ['asc', 'desc'] as const),
  }
}

export function applyFiltersToSearchParams(
  sp: URLSearchParams,
  filters: TaskViewFilters,
): void {
  for (const [field, key] of Object.entries(KEYS)) {
    const value = filters[field as keyof TaskViewFilters]
    if (value) sp.set(key, value)
    else sp.delete(key)
  }
}

/** Число активных фильтров (сортировка не считается фильтром). */
export function activeFilterCount(filters: TaskViewFilters): number {
  return [
    filters.assignee,
    filters.status,
    filters.priority,
    filters.label,
    filters.due,
  ].filter(Boolean).length
}

/** Человеческие названия фильтров — для строки контекста и кнопки снятия. */
const FILTER_LABEL: Record<NarrowableFilter, string> = {
  assignee: 'исполнителя',
  status: 'статус',
  priority: 'приоритет',
  label: 'метку',
  due: 'срок',
}

export type NarrowableFilter = 'assignee' | 'status' | 'priority' | 'label' | 'due'

/**
 * Какой ОДИН фильтр предложить снять, когда под фильтры не попало ничего.
 *
 * Предлагаем только когда активен ровно один: сняв один из трёх, человек с
 * большой вероятностью снова увидит пустой список, и кнопка будет выглядеть
 * сломанной. В этом случае честнее обычное «Сбросить фильтры».
 */
export function narrowableFilter(
  filters: TaskViewFilters,
): { key: NarrowableFilter; label: string } | null {
  const active = (['assignee', 'status', 'priority', 'label', 'due'] as const).filter(
    (k) => filters[k],
  )
  if (active.length !== 1) return null
  const key = active[0]!
  return { key, label: FILTER_LABEL[key] }
}

/** Границы пресетов — календарные дни display tz (lib/taskDates), как у бэкенда. */
function dueRange(preset: DuePreset): { due_from?: string; due_to?: string } {
  const today = todayKey()
  switch (preset) {
    case 'today':
      return { due_from: dayStartIso(today), due_to: dayEndIso(today) }
    case 'week':
      return { due_from: dayStartIso(today), due_to: dayEndIso(addDaysKey(today, 7)) }
    case 'overdue':
      // Конец вчерашнего дня, а не now(): значение стабильно в течение дня —
      // queryKey не меняется на каждом рендере.
      return { due_to: dayEndIso(addDaysKey(today, -1)) }
  }
}

/**
 * Выполненные — в конец списка секции (стабильная партиция: порядок внутри
 * групп сохраняется). Решение владельца 2026-08-21: не скрывать по умолчанию,
 * а утопить; скрытие — явным фильтром «Статус: Не выполнено».
 */
export function sinkDone<T extends Pick<Task, 'status'>>(tasks: readonly T[]): T[] {
  const open: T[] = []
  const done: T[] = []
  for (const t of tasks) (t.status === 'done' ? done : open).push(t)
  return open.length && done.length ? [...open, ...done] : [...tasks]
}

/** Счётчик шапки секции: «N · M выполнено». */
export function countOpenDone(tasks: readonly Pick<Task, 'status'>[]): {
  open: number
  done: number
} {
  let done = 0
  for (const t of tasks) if (t.status === 'done') done += 1
  return { open: tasks.length - done, done }
}

/**
 * Разворачивает view-фильтры в параметры GET /tasks.
 * `forBoard` — доска всегда получает position-порядок, иначе ломается drag.
 */
export function toListFilters(
  filters: TaskViewFilters,
  opts: { forBoard?: boolean } = {},
): TaskListFilters {
  const out: TaskListFilters = {}
  if (filters.assignee) out.assignee = filters.assignee
  if (filters.status) out.status = filters.status
  if (filters.priority) out.priority = filters.priority
  if (filters.label) out.label = filters.label
  if (filters.due) Object.assign(out, dueRange(filters.due))
  // «Просрочено» без явного статуса — только незавершённые: закрытая с
  // опозданием задача не просрочена.
  if (filters.due === 'overdue' && !filters.status) out.status = 'open'
  if (!opts.forBoard && filters.sort && filters.sort !== 'position') {
    out.sort = filters.sort
    out.order = filters.order ?? 'asc'
  }
  return out
}

export function toCalendarFilters(filters: TaskViewFilters): CalendarFilters {
  const out: CalendarFilters = {}
  if (filters.assignee) out.assignee = filters.assignee
  if (filters.status) out.status = filters.status
  if (filters.priority) out.priority = filters.priority
  return out
}

const DUE_LABEL: Record<DuePreset, string> = {
  today: 'сегодня',
  week: 'неделя',
  overdue: 'просрочено',
}

/**
 * «Исполнитель: Дмитрий Фёдоров · Приоритет: срочно» — перечень применённых
 * фильтров для пустого состояния: человек должен видеть, ЧТО отсекло задачи,
 * а не только что «ни одной». Имена исполнителя/метки передаёт вызывающий
 * (в URL лежат id); без них поле подписывается «выбран», а не id.
 */
export function describeFilters(
  filters: TaskViewFilters,
  names: { assignee?: string | null; label?: string | null } = {},
  labels: {
    status: Record<TaskStatusFilter, string>
    priority: Record<TaskPriority, string>
  },
): string {
  const parts: string[] = []
  if (filters.assignee) parts.push(`Исполнитель: ${names.assignee ?? 'выбран'}`)
  if (filters.status) parts.push(`Статус: ${labels.status[filters.status]}`)
  if (filters.priority) parts.push(`Приоритет: ${labels.priority[filters.priority]}`)
  if (filters.label) parts.push(`Метка: ${names.label ?? 'выбрана'}`)
  if (filters.due) parts.push(`Срок: ${DUE_LABEL[filters.due]}`)
  return parts.join(' · ')
}
