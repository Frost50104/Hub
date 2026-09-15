import { describe, expect, it } from 'vitest'

import {
  filterOptions,
  normalize,
  optionMatches,
  queryTokens,
  selectedLabel,
  type SelectOption,
} from './selectOptions'

const people: SelectOption[] = [
  { value: '1', label: 'Пётр Попов', meta: 'petr@t.ru' },
  { value: '2', label: 'Попова Анна', meta: 'anna@t.ru' },
  { value: '3', label: 'Иван Сидоров', meta: 'ivan@t.ru' },
]

describe('порядок слов', () => {
  it('«Попов Пётр» находит «Пётр Попов»', () => {
    // Ради этого кейса поиск и пословный. Справочник записан в смешанном
    // порядке (139 «Имя Фамилия» против 70 «Фамилия Имя»), и подстрочный
    // includes находил 0 из 225 двухсловных ФИО при обратном порядке.
    expect(filterOptions(people, 'Попов Пётр').visible.map((o) => o.value)).toEqual(['1'])
  })

  it('одно слово находит всех однофамильцев', () => {
    expect(filterOptions(people, 'попов').visible.map((o) => o.value)).toEqual(['1', '2'])
  })

  it('больше четырёх слов в запрос не берём', () => {
    expect(queryTokens('а б в г д е')).toEqual(['а', 'б', 'в', 'г'])
  })
})

describe('нормализация', () => {
  it('ё и регистр не различаются', () => {
    expect(normalize('Пётр')).toBe('петр')
    expect(filterOptions(people, 'петр').visible.map((o) => o.value)).toEqual(['1'])
    expect(filterOptions(people, 'ПЁТР').visible.map((o) => o.value)).toEqual(['1'])
  })
})

describe('поле meta', () => {
  it('ищется наравне с подписью', () => {
    // Двух полных тёзок на проде различает именно почта.
    expect(filterOptions(people, 'anna@').visible.map((o) => o.value)).toEqual(['2'])
  })

  it('пункт без meta не роняет поиск', () => {
    expect(optionMatches({ value: 'x', label: 'Без почты' }, ['без'])).toBe(true)
  })
})

describe('пустой запрос', () => {
  it('отдаёт всё', () => {
    expect(filterOptions(people, '').visible).toHaveLength(3)
    expect(filterOptions(people, '   ').visible).toHaveLength(3)
  })
})

describe('потолок выдачи', () => {
  const many: SelectOption[] = Array.from({ length: 315 }, (_, i) => ({
    value: String(i),
    label: `Сотрудник ${i}`,
  }))

  it('315 сотрудников превращаются в 50 видимых и 265 скрытых', () => {
    // Список добирается до 2000 строк — столько узлов DOM в меню не нужно.
    const { visible, hidden } = filterOptions(many, '')
    expect(visible).toHaveLength(50)
    expect(hidden).toBe(265)
  })

  it('скрытых нет, когда всё поместилось', () => {
    expect(filterOptions(people, '').hidden).toBe(0)
  })

  it('потолок считается ПОСЛЕ фильтра, а не до', () => {
    // Иначе запрос находил бы только среди первых 50 строк исходного списка.
    const { visible, hidden } = filterOptions(many, 'Сотрудник 300')
    expect(visible.map((o) => o.value)).toEqual(['300'])
    expect(hidden).toBe(0)
  })
})

describe('подпись выбранного', () => {
  it('берётся из списка', () => {
    expect(selectedLabel(people, '2')).toBe('Попова Анна')
  })

  it('пустое значение — нет подписи', () => {
    expect(selectedLabel(people, null)).toBeNull()
  })

  it('выбранного нет в списке — спасает fallback', () => {
    // Архивный магазин или архивная карточка руководителя: в options их нет,
    // а значение в форме есть. Без fallback поле выглядело бы пустым, и его
    // перезаписали бы, не заметив.
    expect(selectedLabel(people, '99', 'Магазин на Блохина')).toBe('Магазин на Блохина')
    expect(selectedLabel(people, '99')).toBeNull()
  })
})
