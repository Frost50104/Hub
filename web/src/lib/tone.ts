import { type TaskPriority } from './tasks'

/**
 * Словарь тонов трекера — ЕДИНСТВЕННЫЙ источник цвета статуса и приоритета.
 *
 * Правило спеки («Палитра графиков», «Приоритет», «Статусы и метки»):
 * - красный — только просрочка и ошибка; падение метрики красным не красится;
 * - зелёный — только «сделано»;
 * - амбер — текущее/активное (в работе, на проверке, основной ряд графика);
 * - `--blue-deep` — нейтрально-информативное (низкий приоритет, сравнение);
 * - `--text2` — «ничего особенного» (к выполнению, прочее).
 *
 * До этого файла у списка, календаря, Ганта и дашборда были четыре разные
 * палитры, и один факт («задача горит») выглядел по-разному в каждом
 * представлении. Сюда же ходят Donut/MeterRow дашборда: новый цвет графика не
 * изобретается — берётся отсюда.
 */

/** Краска иконки состояния в строке/карточке (текстовые классы). */
export const DONE_INK: Record<'open' | 'done', string> = {
  open: 'text-text2',
  done: 'text-green',
}

/** Плотная заливка плашки состояния + краска на ней (календарь, легенды). */
export const DONE_FILL: Record<'open' | 'done', string> = {
  open: 'bg-text2 text-bg',
  done: 'bg-green-deep text-bg',
}

/** CSS-выражение цвета состояния — для inline-стилей (Donut, точки легенды). */
export const DONE_COLOR: Record<'open' | 'done', string> = {
  open: 'rgb(var(--text2))',
  done: 'rgb(var(--green-deep))',
}

/** Ключ тона по состоянию задачи. */
export function doneTone(done: boolean): 'open' | 'done' {
  return done ? 'done' : 'open'
}

/** Планка 3px у левого края. У `medium` планки нет — это пустое место. */
export const PRIORITY_BAR: Record<TaskPriority, string | null> = {
  urgent: 'bg-red',
  high: 'bg-amber',
  low: 'bg-blue-deep',
  medium: null,
}

/** CSS-выражение цвета приоритета — для графиков. `medium` нейтральный. */
export const PRIORITY_COLOR: Record<TaskPriority, string> = {
  urgent: 'rgb(var(--red))',
  high: 'rgb(var(--amber))',
  medium: 'rgb(var(--text2))',
  low: 'rgb(var(--blue-deep))',
}

/**
 * Ряды многорядного графика: максимум три (амбер — «сейчас», синий —
 * «раньше/сравнение», нейтральный — «прочее»). Четвёртого ряда быть не
 * должно — это второй график, а не четвёртый цвет.
 */
export const SERIES_COLOR = [
  'rgb(var(--amber))',
  'rgb(var(--blue-deep))',
  'rgb(var(--text2))',
] as const

/** Просрочка везде одна: плотный `--red` с краской `--bg`. */
export const OVERDUE_FILL = 'bg-red text-bg'
