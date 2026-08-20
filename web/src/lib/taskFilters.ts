import {
  type CalendarFilters,
  type TaskListFilters,
  type TaskPriority,
  type TaskSortField,
  type TaskStatus,
} from './tasks'

export type DuePreset = 'today' | 'week' | 'overdue'

/** Состояние фильтр-бара проекта. Живёт в URL searchParams (переживает F5 и шарится ссылкой). */
export interface TaskViewFilters {
  assignee?: string
  status?: TaskStatus
  priority?: TaskPriority
  /** id метки проекта. */
  label?: string
  due?: DuePreset
  sort?: TaskSortField
  order?: 'asc' | 'desc'
}

const STATUSES: TaskStatus[] = ['todo', 'in_progress', 'in_review', 'done']
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

function startOfDay(d: Date): Date {
  const out = new Date(d)
  out.setHours(0, 0, 0, 0)
  return out
}

function endOfDay(d: Date): Date {
  const out = new Date(d)
  out.setHours(23, 59, 59, 999)
  return out
}

function dueRange(preset: DuePreset): { due_from?: string; due_to?: string } {
  const now = new Date()
  switch (preset) {
    case 'today':
      return {
        due_from: startOfDay(now).toISOString(),
        due_to: endOfDay(now).toISOString(),
      }
    case 'week': {
      const weekEnd = new Date(now)
      weekEnd.setDate(weekEnd.getDate() + 7)
      return {
        due_from: startOfDay(now).toISOString(),
        due_to: endOfDay(weekEnd).toISOString(),
      }
    }
    case 'overdue':
      // Начало дня, а не now(): значение стабильно в течение дня —
      // queryKey не меняется на каждом рендере.
      return { due_to: startOfDay(now).toISOString() }
  }
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
