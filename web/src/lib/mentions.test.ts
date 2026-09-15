import { describe, expect, it } from 'vitest'

import {
  applyMention,
  mentionContext,
  mentionDisplay,
  mentionParts,
  normalizeToken,
} from './mentions'

const ctx = (text: string, cursor = text.length) => mentionContext(text, cursor)

describe('mentionContext — кириллица', () => {
  it('русская буква больше не закрывает попап', () => {
    // Ровно этот случай был в ОС: раньше `@И` давал null и запрос не уходил.
    expect(ctx('@И')?.query).toBe('И')
    expect(ctx('@Иван')?.query).toBe('Иван')
    expect(ctx('Привет @Иван')?.query).toBe('Иван')
  })

  it('латиница и логин по-прежнему работают', () => {
    expect(ctx('@i.petrov')?.query).toBe('i.petrov')
    expect(ctx('@ivan')?.query).toBe('ivan')
  })

  it('пустой запрос сразу после «@» — это открытый попап', () => {
    expect(ctx('@')).toEqual({ anchor: 0, query: '' })
  })
})

describe('mentionContext — пробелы', () => {
  it('один пробел внутри ищет «Имя Фамилия»', () => {
    expect(ctx('@Иван Пет')?.query).toBe('Иван Пет')
  })

  it('второй пробел обрывает упоминание', () => {
    expect(ctx('@Иван Петров сказал')).toBeNull()
  })

  it('пробел сразу после «@» упоминанием не считается', () => {
    // «Стоимость 5 @ 10 руб» не должна открывать попап.
    expect(ctx('Стоимость 5 @ 10')).toBeNull()
    expect(ctx('@ ')).toBeNull()
  })

  it('перевод строки обрывает', () => {
    expect(ctx('@Иван\nещё')).toBeNull()
  })
})

describe('mentionContext — границы', () => {
  it('почта в тексте не упоминание', () => {
    expect(ctx('ivan@host')).toBeNull()
    expect(ctx('Привет@ivan')).toBeNull()
  })

  it('после знака препинания упоминание допустимо', () => {
    expect(ctx('(@Иван')?.query).toBe('Иван')
  })

  it('слишком длинный хвост попап не держит', () => {
    expect(ctx(`@${'я'.repeat(41)}`)).toBeNull()
  })

  it('каретка левее набранного — контекст по позиции каретки', () => {
    const text = '@Иванов текст'
    expect(mentionContext(text, 4)?.query).toBe('Ива')
  })
})

describe('applyMention', () => {
  it('заменяет набранное готовым токеном и ставит каретку после пробела', () => {
    const text = 'Посмотри @Иван Пет'
    const c = mentionContext(text, text.length)!
    const { next, caret } = applyMention(text, c.anchor, text.length, 'Иван_Петров')
    expect(next).toBe('Посмотри @Иван_Петров ')
    expect(caret).toBe(next.length)
  })

  it('хвост строки сохраняется', () => {
    const text = 'Привет @ив, глянь'
    const { next } = applyMention(text, 7, 10, 'Иван_Петров')
    expect(next).toBe('Привет @Иван_Петров , глянь')
  })
})

describe('normalizeToken', () => {
  it('регистр, ё и хвостовая пунктуация', () => {
    expect(normalizeToken('Иван_Петров.')).toBe('иван_петров')
    expect(normalizeToken('Семён_Ёлкин')).toBe('семен_елкин')
    expect(normalizeToken('I.Petrov-')).toBe('i.petrov')
  })
})

describe('mentionDisplay', () => {
  const names = { иван_петров: 'Иван Петров', 'i.petrov': 'Иван Петров' }

  it('известный токен — текущее ФИО', () => {
    expect(mentionDisplay('@Иван_Петров', names)).toBe('@Иван Петров')
    expect(mentionDisplay('@i.petrov', names)).toBe('@Иван Петров')
  })

  it('точка предложения не съедается', () => {
    expect(mentionDisplay('@Иван_Петров.', names)).toBe('@Иван Петров.')
  })

  it('неизвестный токен читается как имя', () => {
    expect(mentionDisplay('@Пётр_Сидоров', names)).toBe('@Пётр Сидоров')
  })

  it('неизвестный логин остаётся логином', () => {
    expect(mentionDisplay('@a.b', names)).toBe('@a.b')
  })

  it('хвост отделяется от чипа — точка не подсвечивается как часть имени', () => {
    expect(mentionParts('@Иван_Петров.', names)).toEqual({
      chip: '@Иван Петров',
      tail: '.',
    })
    expect(mentionParts('@i.petrov', names)).toEqual({ chip: '@Иван Петров', tail: '' })
  })
})
