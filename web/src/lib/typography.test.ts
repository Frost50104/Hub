import { describe, expect, it } from 'vitest'

import { formatMinutes, nbsp, plural } from './typography'

const NBSP = ' '

describe('nbsp', () => {
  it('связывает разряды числа', () => {
    expect(nbsp('1 240 баллов')).toBe(`1${NBSP}240${NBSP}баллов`)
  })

  it('связывает число с единицей', () => {
    expect(nbsp('6,8 МБ')).toBe(`6,8${NBSP}МБ`)
    expect(nbsp('12 мин чтения')).toBe(`12${NBSP}мин чтения`)
  })

  it('связывает номер со знаком и дату с месяцем', () => {
    expect(nbsp('№ 4187')).toBe(`№${NBSP}4187`)
    expect(nbsp('до 12 августа')).toBe(`до 12${NBSP}августа`)
  })

  it('связывает дробь места и содержимое скобок', () => {
    expect(nbsp('7 / 62')).toBe(`7${NBSP}/${NBSP}62`)
    expect(nbsp('(0 из 1)')).toBe(`(0${NBSP}из${NBSP}1)`)
  })

  it('не склеивает единицы между собой — перенос по «·» остаётся', () => {
    expect(nbsp('владелец: Пётр Попов')).toBe('владелец: Пётр Попов')
  })

  it('не ломает слова, начинающиеся как единица измерения', () => {
    expect(nbsp('3 читателя')).toBe('3 читателя')
  })
})

describe('plural', () => {
  it('склоняет по русским правилам', () => {
    expect(plural(1, 'урок', 'урока', 'уроков')).toBe(`1${NBSP}урок`)
    expect(plural(4, 'урок', 'урока', 'уроков')).toBe(`4${NBSP}урока`)
    expect(plural(11, 'урок', 'урока', 'уроков')).toBe(`11${NBSP}уроков`)
    expect(plural(22, 'урок', 'урока', 'уроков')).toBe(`22${NBSP}урока`)
  })
})

describe('formatMinutes', () => {
  it('минуты и часы', () => {
    expect(formatMinutes(12)).toBe(`12${NBSP}мин`)
    expect(formatMinutes(130)).toBe(`~2${NBSP}ч${NBSP}10${NBSP}мин`)
    expect(formatMinutes(120)).toBe(`~2${NBSP}ч`)
    expect(formatMinutes(0)).toBe(`1${NBSP}мин`)
  })
})
