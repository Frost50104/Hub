import { describe, expect, it } from 'vitest'

import { boardHint, stageDeletePrompt } from './boardHints'
import { NBSP } from './typography'

describe('boardHint', () => {
  it('колонок нет, задачи есть — зовёт создать колонку', () => {
    const hint = boardHint({ stages: 0, stageless: 2, visible: 0 })
    expect(hint).toContain(`2${NBSP}задачи`)
    expect(hint).toContain('Создайте колонку')
  })

  it('колонки есть, но задачи не разложены — объясняет, где они', () => {
    const hint = boardHint({ stages: 8, stageless: 1277, visible: 0 })
    expect(hint).toContain(`1277${NBSP}задач`)
    expect(hint).toContain('в списке')
    // Главное: не «задач нет» — у проекта их 1 277.
    expect(hint).not.toContain('нет задач')
  })

  it('часть задач разложена — строка всё равно про остальные', () => {
    expect(boardHint({ stages: 3, stageless: 5, visible: 10 })).toContain(`5${NBSP}задач`)
  })

  it.each([
    [1, 'она', 'они'],
    [2, 'они', 'она'],
  ])('число согласовано: %i', (stageless, expected, forbidden) => {
    const hint = boardHint({ stages: 0, stageless, visible: 0 }) ?? ''
    expect(hint).toContain(expected)
    expect(hint).not.toContain(forbidden)
  })

  it('задач нет вовсе, колонки есть — зовёт создать задачу', () => {
    expect(boardHint({ stages: 4, stageless: 0, visible: 0 })).toBe(
      'На доске пока нет задач — добавьте первую в любой колонке.',
    )
  })

  it('пустой проект без колонок — молчим: на экране одна кнопка', () => {
    expect(boardHint({ stages: 0, stageless: 0, visible: 0 })).toBeNull()
  })

  it('доска с карточками — подсказка не нужна', () => {
    expect(boardHint({ stages: 3, stageless: 0, visible: 12 })).toBeNull()
  })
})

describe('stageDeletePrompt', () => {
  it('пустая колонка — переносить нечего', () => {
    expect(stageDeletePrompt(0, true)).toContain('пуста')
  })

  it('одна задача и есть куда переносить — число согласовано', () => {
    const text = stageDeletePrompt(1, true)
    expect(text).toContain('что с ней сделать')
    expect(text).not.toContain('с ними')
  })

  it('несколько задач — множественное число', () => {
    expect(stageDeletePrompt(3, true)).toContain('что с ними сделать')
  })

  it('последняя колонка — называет цену, а не предлагает перенос', () => {
    const text = stageDeletePrompt(12, false)
    expect(text).toContain('последняя колонка')
    expect(text).toContain('без колонки')
    expect(text).not.toContain('выберите')
  })
})
