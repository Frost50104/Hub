import { plural } from '@/lib/typography'

/**
 * Повтор задачи: тексты правила и разбор пресетов.
 *
 * Календарной арифметики здесь НЕТ намеренно — следующую дату считает сервер и
 * присылает в `recurrence.next_due` (тот же принцип, что у переноса задачи:
 * второй реализации на клиенте не заводим, иначе две сетки разъедутся на
 * «каждом месяце» от 31-го числа).
 *
 * Тексты — зеркало `app/services/recurrence_dates.py::describe`: их видит один
 * и тот же человек в ленте задачи и на кнопке.
 */

export type RecurrenceFreq = 'day' | 'weekday' | 'week' | 'month'

export interface Recurrence {
  freq: RecurrenceFreq
  /** `step`, а не `interval`: INTERVAL — зарезервированное слово Postgres. */
  step: number
  anchor: string
  occurrence: number
  /** Считает СЕРВЕР. */
  next_due: string
  /** Готовая формулировка с сервера; клиент может показать свою. */
  text: string
}

export type RecurrencePreset = RecurrenceFreq | 'custom'

export const RECURRENCE_PRESETS: { value: RecurrencePreset; label: string }[] = [
  { value: 'day', label: 'Каждый день' },
  { value: 'weekday', label: 'По будням' },
  { value: 'week', label: 'Каждую неделю' },
  { value: 'month', label: 'Каждый месяц' },
  { value: 'custom', label: 'Свой интервал' },
]

export const CUSTOM_UNITS: { value: Exclude<RecurrenceFreq, 'weekday'>; label: string }[] = [
  { value: 'day', label: 'дней' },
  { value: 'week', label: 'недель' },
  { value: 'month', label: 'месяцев' },
]

const SIMPLE: Record<RecurrenceFreq, string> = {
  day: 'каждый день',
  weekday: 'по будням',
  week: 'каждую неделю',
  month: 'каждый месяц',
}

const NOUNS: Record<Exclude<RecurrenceFreq, 'weekday'>, [string, string, string]> = {
  day: ['день', 'дня', 'дней'],
  week: ['неделю', 'недели', 'недель'],
  month: ['месяц', 'месяца', 'месяцев'],
}

/** «каждую неделю», «каждые 2 недели», «по будням». */
export function describeRecurrence(r: Pick<Recurrence, 'freq' | 'step'>): string {
  if (r.freq === 'weekday' || r.step <= 1) return SIMPLE[r.freq]
  // plural() уже возвращает число вместе со словом — склеивать с числом нельзя.
  const [one, few, many] = NOUNS[r.freq]
  return `каждые ${plural(r.step, one, few, many)}`
}

/** Короткая подпись для чипа в списке и на доске: «нед», «2 нед», «будни». */
export function shortRecurrence(r: Pick<Recurrence, 'freq' | 'step'>): string {
  if (r.freq === 'weekday') return 'будни'
  const unit = { day: 'дн', week: 'нед', month: 'мес' }[r.freq]
  return r.step <= 1 ? unit : `${r.step} ${unit}`
}

/** Какой вариант подсвечен в диалоге: «каждые 2 недели» — это «Свой интервал». */
export function presetOf(r: Pick<Recurrence, 'freq' | 'step'> | null | undefined): RecurrencePreset | null {
  if (!r) return null
  return r.step > 1 ? 'custom' : r.freq
}

/** Пресет + свой интервал → тело запроса. */
export function bodyFor(
  preset: RecurrencePreset,
  step: number,
  unit: Exclude<RecurrenceFreq, 'weekday'>,
): { freq: RecurrenceFreq; step: number } {
  if (preset === 'custom') {
    const safe = Number.isFinite(step) ? Math.min(365, Math.max(1, Math.trunc(step))) : 1
    return { freq: unit, step: safe }
  }
  return { freq: preset, step: 1 }
}

/**
 * Можно ли вообще включить повтор. Зеркало серверных гейтов: 422 без срока
 * (считать не от чего) и 409 на подзадаче (копия осиротела бы у выполненного
 * родителя).
 */
export function canSetRecurrence(task: {
  due_at: string | null
  parent_task_id: string | null
}): boolean {
  return task.due_at !== null && task.parent_task_id === null
}

/** Почему кнопка недоступна — одной фразой для подсказки. */
export function recurrenceBlockReason(task: {
  due_at: string | null
  parent_task_id: string | null
}): string | null {
  if (task.parent_task_id !== null) return 'Повтор ставится на задачу, а не на подзадачу'
  if (task.due_at === null) return 'Сначала поставьте срок — повтор считается от него'
  return null
}
