import { describe, expect, it } from 'vitest'

import { canonicalJson, quizDraftDirty, quizSnapshot, sameQuestion } from './quizDraft'
import { type QuizManage, type QuizQuestionDraft } from './learn'

const q = (over: Partial<QuizQuestionDraft> = {}): QuizQuestionDraft => ({
  qtype: 'single',
  prompt: 'Вопрос',
  options: { choices: ['А', 'Б'] },
  answer: { correct: 0 },
  points: 1,
  ...over,
})

describe('canonicalJson', () => {
  it('порядок ключей не влияет — иначе диалог спрашивал бы на ровном месте', () => {
    expect(canonicalJson({ a: 1, b: 2 })).toBe(canonicalJson({ b: 2, a: 1 }))
  })

  it('порядок в массиве влияет: варианты ответа переставлять нельзя молча', () => {
    expect(canonicalJson(['А', 'Б'])).not.toBe(canonicalJson(['Б', 'А']))
  })

  it('вложенность разбирается рекурсивно', () => {
    expect(canonicalJson({ x: { b: 1, a: 2 } })).toBe(canonicalJson({ x: { a: 2, b: 1 } }))
  })

  it('null и примитивы не ломают', () => {
    expect(canonicalJson(null)).toBe('null')
    expect(canonicalJson(5)).toBe('5')
    expect(canonicalJson('т')).toBe('"т"')
  })
})

describe('sameQuestion', () => {
  it('одинаковые — одинаковы', () => {
    expect(sameQuestion(q(), q())).toBe(true)
  })

  it('media_id: undefined и null — это одно и то же', () => {
    expect(sameQuestion(q({ media_id: undefined }), q({ media_id: null }))).toBe(true)
  })

  it.each([
    ['текст', q({ prompt: 'Другой' })],
    ['тип', q({ qtype: 'multi' })],
    ['баллы', q({ points: 2 })],
    ['варианты', q({ options: { choices: ['А', 'В'] } })],
    ['правильный ответ', q({ answer: { correct: 1 } })],
    ['картинку', q({ media_id: 'm1' })],
  ])('замечает изменённый %s', (_label, changed) => {
    expect(sameQuestion(q(), changed)).toBe(false)
  })
})

describe('quizDraftDirty', () => {
  const seeded = { passScore: 80, attemptsLimit: '1', questions: [q()] }

  it('до засева не спрашивает', () => {
    expect(quizDraftDirty({ ...seeded }, null)).toBe(false)
  })

  it('ничего не тронули — не спрашивает', () => {
    expect(quizDraftDirty({ passScore: 80, attemptsLimit: '1', questions: [q()] }, seeded)).toBe(
      false,
    )
  })

  it('лишние пробелы в лимите изменением не считаются', () => {
    expect(
      quizDraftDirty({ passScore: 80, attemptsLimit: ' 1 ', questions: [q()] }, seeded),
    ).toBe(false)
  })

  it.each([
    ['порог', { passScore: 55, attemptsLimit: '1', questions: [q()] }],
    ['лимит попыток', { passScore: 80, attemptsLimit: '', questions: [q()] }],
    ['добавленный вопрос', { passScore: 80, attemptsLimit: '1', questions: [q(), q()] }],
    ['удалённый вопрос', { passScore: 80, attemptsLimit: '1', questions: [] }],
    [
      'правку вопроса',
      { passScore: 80, attemptsLimit: '1', questions: [q({ prompt: 'Иначе' })] },
    ],
  ])('замечает %s', (_label, current) => {
    expect(quizDraftDirty(current, seeded)).toBe(true)
  })
})

describe('снимок формы вопроса', () => {
  const form = (over: Record<string, unknown> = {}) => ({
    qtype: 'single',
    prompt: '',
    points: 1,
    options: ['', ''],
    correct: [] as number[],
    pairs: [] as unknown[],
    items: ['', ''],
    ...over,
  })

  it('нетронутая пустая форма нового вопроса совпадает со своим снимком', () => {
    expect(canonicalJson(form())).toBe(canonicalJson(form()))
  })

  it('набранный текст меняет снимок', () => {
    expect(canonicalJson(form({ prompt: 'Что такое эспрессо?' }))).not.toBe(
      canonicalJson(form()),
    )
  })

  it('заполненный вариант ответа меняет снимок', () => {
    expect(canonicalJson(form({ options: ['Молоко', ''] }))).not.toBe(canonicalJson(form()))
  })

  it('смена типа вопроса меняет снимок', () => {
    expect(canonicalJson(form({ qtype: 'open' }))).not.toBe(canonicalJson(form()))
  })

  it('отметка правильного ответа меняет снимок', () => {
    expect(canonicalJson(form({ correct: [0] }))).not.toBe(canonicalJson(form()))
  })
})

const manage = (over: Partial<QuizManage> = {}): QuizManage => ({
  id: 'quiz-1',
  course_id: 'course-1',
  lesson_id: null,
  title: 'Аттестация',
  description: null,
  status: 'draft',
  pass_score_pct: 70,
  attempts_limit: 2,
  shuffle_questions: false,
  shuffle_options: false,
  show_correct_answers: false,
  is_required: false,
  questions: [
    { id: 'q1', qtype: 'single', prompt: 'Первый', media_id: null, options: { choices: ['А', 'Б'] }, answer: { correct: 0 }, points: 1, position: 0 },
  ],
  ...over,
})

describe('quizSnapshot', () => {
  it('«без лимита» — пустая строка, а не ноль: ноль означал бы «ни одной попытки»', () => {
    expect(quizSnapshot(manage({ attempts_limit: null })).attemptsLimit).toBe('')
    expect(quizSnapshot(manage({ attempts_limit: 3 })).attemptsLimit).toBe('3')
  })

  it('снимок совпадает сам с собой — иначе диалог спросит «выйти без сохранения?» сразу', () => {
    // Ровно то, что делает `applyQuiz` после импорта вопросов: состояние и
    // снимок засеиваются ОДНОЙ функцией, поэтому свежий набор не считается
    // изменённым.
    const fresh = quizSnapshot(manage())
    expect(quizDraftDirty(fresh, fresh)).toBe(false)
  })

  it('импортированные вопросы попадают в черновик целиком', () => {
    const before = quizSnapshot(manage())
    const after = quizSnapshot(
      manage({
        questions: [
          ...manage().questions,
          { id: 'q2', qtype: 'single', prompt: 'Импортированный', media_id: null, options: { choices: ['Да', 'Нет'] }, answer: { correct: 1 }, points: 2, position: 1 },
        ],
      }),
    )
    expect(after.questions).toHaveLength(2)
    expect(after.questions[1]?.prompt).toBe('Импортированный')
    // Пока пересева не было, набор на экране отстаёт от серверного — именно
    // из-за этого «Сохранить» стирал импорт (ручка кампании делает replace).
    expect(quizDraftDirty(before, after)).toBe(true)
  })

  it('id и position с сервера в черновик не переносятся: PUT их не принимает', () => {
    const first = quizSnapshot(manage()).questions[0] as unknown as Record<string, unknown>
    expect(first).not.toHaveProperty('id')
    expect(first).not.toHaveProperty('position')
  })
})
