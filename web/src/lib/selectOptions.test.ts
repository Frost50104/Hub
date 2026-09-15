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
    expect(filterOptions(people, 'Попов Пётр').map((o) => o.value)).toEqual(['1'])
  })

  it('одно слово находит всех однофамильцев', () => {
    expect(filterOptions(people, 'попов').map((o) => o.value)).toEqual(['1', '2'])
  })

  it('больше четырёх слов в запрос не берём', () => {
    expect(queryTokens('а б в г д е')).toEqual(['а', 'б', 'в', 'г'])
  })
})

describe('нормализация', () => {
  it('ё и регистр не различаются', () => {
    expect(normalize('Пётр')).toBe('петр')
    expect(filterOptions(people, 'петр').map((o) => o.value)).toEqual(['1'])
    expect(filterOptions(people, 'ПЁТР').map((o) => o.value)).toEqual(['1'])
  })
})

describe('поле meta', () => {
  it('ищется наравне с подписью', () => {
    // Двух полных тёзок на проде различает именно почта.
    expect(filterOptions(people, 'anna@').map((o) => o.value)).toEqual(['2'])
  })

  it('пункт без meta не роняет поиск', () => {
    expect(optionMatches({ value: 'x', label: 'Без почты' }, ['без'])).toBe(true)
  })
})

describe('пустой запрос', () => {
  it('отдаёт всё', () => {
    expect(filterOptions(people, '')).toHaveLength(3)
    expect(filterOptions(people, '   ')).toHaveLength(3)
  })
})

describe('выдача не обрезается', () => {
  const many: SelectOption[] = Array.from({ length: 315 }, (_, i) => ({
    value: String(i),
    label: `Сотрудник ${i}`,
  }))

  it('315 сотрудников отдаются все 315', () => {
    // Регресс на живой баг 16.09: выдача резалась до 50 строк, и «Пётр Попов»,
    // стоящий 246-м из 313 по алфавиту, просто отсутствовал в списке
    // руководителей. Нативный select, который мы заменяли, показывал всех.
    expect(filterOptions(many, '')).toHaveLength(315)
  })

  it('дальний по алфавиту находится и без запроса, и с запросом', () => {
    expect(filterOptions(many, '').map((o) => o.value)).toContain('300')
    expect(filterOptions(many, 'Сотрудник 300').map((o) => o.value)).toEqual(['300'])
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
