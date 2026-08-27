import { describe, expect, it } from 'vitest'

import { buildCheckAttrs } from './checkQuestion'

const draft = (over: Partial<Parameters<typeof buildCheckAttrs>[0]> = {}) => ({
  question: 'Как правильно?',
  options: ['Первый', 'Второй'],
  correct: 0,
  gateNext: true,
  ...over,
})

describe('buildCheckAttrs', () => {
  it('вставка выдаёт новый blockId', () => {
    const a = buildCheckAttrs(draft())
    const b = buildCheckAttrs(draft())
    expect(a?.blockId).toBeTruthy()
    expect(a?.blockId).not.toBe(b?.blockId)
  })

  it('ПРАВКА сохраняет blockId — на нём висят ответы и гейт', () => {
    const attrs = buildCheckAttrs(draft({ question: 'Новый текст' }), 'block-42')
    expect(attrs?.blockId).toBe('block-42')
    expect(attrs?.question).toBe('Новый текст')
  })

  it('пустые варианты выброшены, индекс правильного пересчитан', () => {
    const attrs = buildCheckAttrs(
      draft({ options: ['', 'Верный', '  ', 'Третий'], correct: 1 }),
    )
    expect(attrs?.options).toEqual(['Верный', 'Третий'])
    expect(attrs?.correct).toBe(0)
  })

  it('удалили вариант ВЫШЕ правильного — правильным остаётся тот же текст', () => {
    const attrs = buildCheckAttrs(draft({ options: ['', 'А', 'Б'], correct: 2 }))
    expect(attrs?.options[attrs.correct]).toBe('Б')
  })

  it('правильный вариант стёрли — сохранять нельзя', () => {
    expect(buildCheckAttrs(draft({ options: ['', 'Б', 'В'], correct: 0 }))).toBeNull()
  })

  it('пустой вопрос и один вариант — нельзя', () => {
    expect(buildCheckAttrs(draft({ question: '   ' }))).toBeNull()
    expect(buildCheckAttrs(draft({ options: ['Один', ''] }))).toBeNull()
  })

  it('больше десяти вариантов — нельзя (граница сервера)', () => {
    const many = Array.from({ length: 11 }, (_, i) => `Вариант ${i + 1}`)
    expect(buildCheckAttrs(draft({ options: many }))).toBeNull()
  })

  it('текст вопроса и вариантов триммится', () => {
    const attrs = buildCheckAttrs(draft({ question: '  Вопрос  ', options: [' А ', ' Б '] }))
    expect(attrs?.question).toBe('Вопрос')
    expect(attrs?.options).toEqual(['А', 'Б'])
  })
})
