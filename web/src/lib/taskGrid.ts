import { type CustomFieldDefinition, type CustomFieldType } from './customFields'

/**
 * Треки таблицы задач. Шапка колонок и строки ОБЯЗАНЫ брать значения отсюда:
 * две независимые декларации расходятся на пиксели, и подписи перестают
 * стоять над значениями.
 *
 * Дизайн задаёт шесть треков под три кастом-поля демо-проекта
 * (`minmax(0,1fr) 116px 82px 128px 96px 76px`). У проектов их 0..10, поэтому
 * ширина выводится из ТИПА поля, а не из позиции: число и дата узкие, справочные
 * значения средние, свободный текст широкий.
 */

const FIELD_WIDTH: Record<CustomFieldType, number> = {
  number: 82,
  date: 82,
  checkbox: 82,
  select: 116,
  multi_select: 116,
  person: 116,
  text: 128,
}

/** Колонка исполнителей: стек из трёх 24px-аватаров с перекрытием −4px + «+N». */
const ASSIGNEES_WIDTH = 96
/** Срок в формате «16 авг» табличными цифрами. */
const DUE_WIDTH = 76
/** Ниже этого заголовок задачи перестаёт читаться — дальше горизонтальный скролл. */
const TITLE_MIN_WIDTH = 280
/** padding строки: 21px слева (3px отданы планке приоритета) + 24px справа. */
const ROW_PADDING = 45

export interface TaskGrid {
  /** Значение grid-template-columns. */
  columns: string
  /** min-width контейнера: при переполнении включается горизонтальный скролл. */
  minWidth: number
}

export function projectTaskGrid(fields: CustomFieldDefinition[]): TaskGrid {
  const widths = fields.map((f) => FIELD_WIDTH[f.type] ?? 116)
  return {
    columns: [
      'minmax(0,1fr)',
      ...widths.map((w) => `${w}px`),
      `${ASSIGNEES_WIDTH}px`,
      `${DUE_WIDTH}px`,
    ].join(' '),
    minWidth:
      TITLE_MIN_WIDTH +
      widths.reduce((a, b) => a + b, 0) +
      ASSIGNEES_WIDTH +
      DUE_WIDTH +
      ROW_PADDING,
  }
}

/**
 * «Мои задачи» — задачи из разных проектов, поэтому кастом-полей в колонках
 * быть не может (поля принадлежат проекту). Вместо них колонка проекта.
 */
export const MY_TASKS_GRID: TaskGrid = {
  columns: 'minmax(0,1fr) 190px 92px 88px',
  minWidth: TITLE_MIN_WIDTH + 190 + 92 + 88 + 19,
}
