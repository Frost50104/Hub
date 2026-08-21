import { describe, expect, it } from 'vitest'

import { gateRows, quizBlocksCompletion } from './lessonGates'

const base = {
  gate_blocks: [] as string[],
  required_videos: [] as string[],
  quiz_required: false,
  quiz_state: 'none' as const,
}

describe('lessonGates', () => {
  it('без гейтов — пустой чек-лист и ничего не блокирует', () => {
    expect(gateRows(base, new Set(), {})).toEqual([])
    expect(quizBlocksCompletion(base)).toBe(false)
  })

  it('обязательный тест даёт строку по состоянию и блокирует, пока не сдан', () => {
    const failed = { ...base, quiz_required: true, quiz_state: 'failed' as const }
    expect(gateRows(failed, new Set(), {})).toEqual([{ label: 'Сдать тест урока', done: false }])
    expect(quizBlocksCompletion(failed)).toBe(true)
    const pending = { ...base, quiz_required: true, quiz_state: 'pending_review' as const }
    expect(gateRows(pending, new Set(), {})[0]?.label).toContain('на проверке')
    const passed = { ...base, quiz_required: true, quiz_state: 'passed' as const }
    expect(gateRows(passed, new Set(), {})).toEqual([{ label: 'Сдать тест урока', done: true }])
    expect(quizBlocksCompletion(passed)).toBe(false)
  })

  it('вопросы и видео считаются как раньше', () => {
    const lesson = { ...base, gate_blocks: ['q1', 'q2'], required_videos: ['v1'] }
    const rows = gateRows(lesson, new Set(['q1']), { v1: 0.95 })
    expect(rows).toEqual([
      { label: 'Ответить на контрольные вопросы (1 из 2)', done: false },
      { label: 'Досмотреть видео — минимум 90%', done: true },
    ])
  })
})
