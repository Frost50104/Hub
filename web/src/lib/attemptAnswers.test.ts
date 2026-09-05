import { describe, expect, it } from 'vitest'

import type { QuizSnapshotQuestion } from './learn'

import { describeAnswer, describeCorrect, NO_ANSWER } from './attemptAnswers'

function q(patch: Partial<QuizSnapshotQuestion>): QuizSnapshotQuestion {
  return {
    id: 'q1',
    qtype: 'single',
    prompt: 'Вопрос',
    media_id: null,
    media_url: null,
    options: {},
    points: 1,
    ...patch,
  }
}

const single = q({ qtype: 'single', options: { options: ['Латте', 'Раф', 'Флэт'] } })
const multi = q({ qtype: 'multi', options: { options: ['А', 'Б', 'В'] } })
const match = q({
  qtype: 'match',
  options: { left: ['Эспрессо', 'Капучино'], right: ['30 мл', '180 мл'] },
})
const order = q({ qtype: 'order', options: { items: ['Помол', 'Темпер', 'Пролив'] } })
const open = q({ qtype: 'open' })

describe('describeAnswer', () => {
  it('single/multi — тексты предъявленных вариантов по индексам', () => {
    expect(describeAnswer(single, 1)).toBe('Раф')
    expect(describeAnswer(multi, [0, 2])).toBe('А; В')
  })

  it('match — пары «лево → право», order — последовательность', () => {
    expect(describeAnswer(match, [1, 0])).toBe('Эспрессо → 180 мл; Капучино → 30 мл')
    expect(describeAnswer(order, [2, 0, 1])).toBe('Пролив → Помол → Темпер')
  })

  it('open — текст как есть, пустой → «Без ответа»', () => {
    expect(describeAnswer(open, ' по вкусу ')).toBe(' по вкусу ')
    expect(describeAnswer(open, '   ')).toBe(NO_ANSWER)
  })

  it('пропуск и мусор не роняют: null/undefined/чужие формы → прочерки', () => {
    expect(describeAnswer(single, null)).toBe(NO_ANSWER)
    expect(describeAnswer(single, undefined)).toBe(NO_ANSWER)
    expect(describeAnswer(single, 'not-an-index')).toBe('—')
    expect(describeAnswer(single, 99)).toBe('—')
    expect(describeAnswer(multi, 'oops')).toBe(NO_ANSWER)
    expect(describeAnswer(order, [{ bad: true }])).toBe(NO_ANSWER)
  })
})

describe('describeCorrect', () => {
  it('закрытые типы — из answer снапшота (переиндексирован под шаффл)', () => {
    expect(describeCorrect(single, { correct: [2] })).toBe('Флэт')
    expect(describeCorrect(multi, { correct: [0, 1] })).toBe('А; Б')
    expect(describeCorrect(match, { pairs: [[0, 1], [1, 0]] })).toBe(
      'Эспрессо → 180 мл; Капучино → 30 мл',
    )
    expect(describeCorrect(order, { order: [1, 2, 0] })).toBe('Темпер → Пролив → Помол')
  })

  it('open и отсутствующий answer — прочерк (проверяет человек)', () => {
    expect(describeCorrect(open, { correct: [0] })).toBe('—')
    expect(describeCorrect(single, undefined)).toBe('—')
    expect(describeCorrect(single, { correct: 'мусор' })).toBe('—')
  })
})
