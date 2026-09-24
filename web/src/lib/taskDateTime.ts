/**
 * Дата + необязательное время у старта и срока задачи (0061) — правило патча.
 *
 * Зеркало сервера (`app/services/taskdates.py::resolve_date_patch`): дата без
 * флага — календарный день (полдень display tz), дата с `*_has_time: true` —
 * точный момент, снятая дата снимает и время. Флаг шлём ТОЛЬКО со значением
 * `true`: сервер отсутствие читает как `false`, а при откате одного бэкенда
 * `extra="forbid"` отвечал бы 422 лишь на правки со временем, а не на все.
 *
 * Чистый модуль (только `import type`): vitest бежит без jsdom, а `lib/tasks.ts`
 * тянет axios-клиент.
 */

import { addDaysKey, dayKey, dayTimeToIso, dueDayToIso, parseTimeKey, timeKey } from '@/lib/taskDates'
import type { Task, TaskUpdateBody } from '@/lib/tasks'

export type DateTimeField = 'due' | 'start'

/** Значения полей формы: `YYYY-MM-DD` и `HH:MM`, пустая строка — «не задано». */
export interface DateTimeValue {
  day: string
  time: string
}

export const EMPTY_DATE_TIME: DateTimeValue = { day: '', time: '' }

/** Значение полей формы по мгновению с сервера. */
export function splitDateTime(iso: string | null | undefined, hasTime: boolean | undefined): DateTimeValue {
  if (!iso) return EMPTY_DATE_TIME
  return { day: dayKey(iso), time: hasTime ? timeKey(iso) : '' }
}

/** Поля задачи для `splitDateTime` по имени поля. */
export function taskDateTime(
  task: Pick<Task, 'due_at' | 'due_has_time' | 'start_at' | 'start_has_time'>,
  field: DateTimeField,
): DateTimeValue {
  return field === 'due'
    ? splitDateTime(task.due_at, task.due_has_time)
    : splitDateTime(task.start_at, task.start_has_time)
}

export function sameDateTime(a: DateTimeValue, b: DateTimeValue): boolean {
  return a.day === b.day && a.time === b.time
}

/**
 * Сдвиг даты на `days` КАЛЕНДАРНЫХ дней display tz — для перетаскивания в
 * календаре и хронологии. С временем — тот же час в новом дне, без времени —
 * полдень (единая конвенция дня). Раньше сдвиг шёл `setDate` в поясе БРАУЗЕРА.
 */
export function shiftDateTime(iso: string, hasTime: boolean | undefined, days: number): string {
  const day = addDaysKey(dayKey(iso), days)
  return (hasTime && dayTimeToIso(day, timeKey(iso))) || dueDayToIso(day)
}

/**
 * Патч перетаскивания: обе даты сдвигаются на одно число дней, флаги едут
 * вместе с ними. Флаг в теле — только `true` (как у `dateTimePatch`), иначе
 * сервер прочёл бы «дата без флага» как снятие времени.
 */
export function shiftTaskDates(
  task: Pick<Task, 'due_at' | 'due_has_time' | 'start_at' | 'start_has_time'>,
  days: number,
): DateTimePatch | null {
  if (!task.due_at) return null
  const body: DateTimePatch['body'] = {
    due_at: shiftDateTime(task.due_at, task.due_has_time, days),
  }
  if (task.due_has_time) body.due_has_time = true
  if (task.start_at) {
    body.start_at = shiftDateTime(task.start_at, task.start_has_time, days)
    if (task.start_has_time) body.start_has_time = true
  }
  return {
    body,
    cache: {
      ...body,
      due_has_time: task.due_has_time === true,
      ...(task.start_at ? { start_has_time: task.start_has_time === true } : {}),
    },
  }
}

/** Год, ниже которого дата — промежуточное значение набора с клавиатуры
 *  (Chrome шлёт `0002-10-15 → 0020 → 0202 → 2027`, замер 24.09). */
const MIN_YEAR = 1970

export interface DateTimePatch {
  /** Тело PATCH. */
  body: Pick<TaskUpdateBody, 'due_at' | 'due_has_time' | 'start_at' | 'start_has_time'>
  /** Что положить в кэш сразу: флаг явно, даже когда в теле его нет. */
  cache: Partial<Pick<Task, 'due_at' | 'due_has_time' | 'start_at' | 'start_has_time'>>
}

/**
 * Патч по значению полей. null — значение некорректно (обрывок набора,
 * время без даты): сохранять нельзя, черновик откатывается.
 */
export function dateTimePatch(field: DateTimeField, value: DateTimeValue): DateTimePatch | null {
  const atKey = field === 'due' ? 'due_at' : 'start_at'
  const flagKey = field === 'due' ? 'due_has_time' : 'start_has_time'
  // Пустой день при коммите — снять срок вместе со временем (время черновик
  // держит и при пустом дне, см. `dateDraft.withDay`).
  if (!value.day) {
    return { body: { [atKey]: null }, cache: { [atKey]: null, [flagKey]: false } }
  }
  const year = Number(value.day.slice(0, 4))
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value.day) || year < MIN_YEAR) return null
  if (!value.time) {
    const iso = dueDayToIso(value.day)
    return { body: { [atKey]: iso }, cache: { [atKey]: iso, [flagKey]: false } }
  }
  if (!parseTimeKey(value.time)) return null
  const iso = dayTimeToIso(value.day, value.time)
  if (!iso) return null
  return {
    body: { [atKey]: iso, [flagKey]: true },
    cache: { [atKey]: iso, [flagKey]: true },
  }
}
