import { describe, expect, it } from 'vitest'

import {
  describeCampaignDeletion,
  resolveAssessmentView,
  type AssessmentView,
} from './assessments'

const c = (over: Partial<Parameters<typeof describeCampaignDeletion>[0]> = {}) => ({
  status: 'closed' as const,
  question_count: 3,
  attempt_count: 0,
  ...over,
})

describe('describeCampaignDeletion', () => {
  it('без попыток прямо говорит, что результатов нет', () => {
    const d = describeCampaignDeletion(c())
    expect(d.losesResults).toBe(false)
    expect(d.summary).toContain('результатов нет')
    expect(d.summary).toContain('3')
  })

  it('пустая кампания не выдумывает потерь', () => {
    const d = describeCampaignDeletion(c({ question_count: 0 }))
    expect(d.summary).toContain('пуста')
    expect(d.losesResults).toBe(false)
  })

  it('с попытками предупреждает про запись об аттестации', () => {
    const d = describeCampaignDeletion(c({ attempt_count: 12 }))
    expect(d.losesResults).toBe(true)
    expect(d.summary).toContain('12')
    expect(d.summary).toContain('навсегда')
  })

  it('одна попытка склоняется правильно', () => {
    expect(describeCampaignDeletion(c({ attempt_count: 1 })).summary).toContain('попытка')
  })

  it('пять попыток склоняются правильно', () => {
    expect(describeCampaignDeletion(c({ attempt_count: 5 })).summary).toContain('попыток')
  })

  it('попытки есть, а вопросов нет — про вопросы не врём', () => {
    const d = describeCampaignDeletion(c({ attempt_count: 2, question_count: 0 }))
    expect(d.summary).toContain('2')
    expect(d.summary).not.toContain('вопрос')
  })
})

describe('resolveAssessmentView', () => {
  const all: AssessmentView[] = ['my', 'report', 'manage']

  it('администратор попадает на «Кампании» — кнопка создания живёт только там', () => {
    expect(resolveAssessmentView(null, all, true)).toBe('manage')
  })

  it('сотрудник остаётся на «Моих»', () => {
    expect(resolveAssessmentView(null, ['my'], false)).toBe('my')
  })

  it('выбор человека сильнее роли — иначе вкладка «сама» уезжала бы под рукой', () => {
    expect(resolveAssessmentView('my', all, true)).toBe('my')
    expect(resolveAssessmentView('report', all, true)).toBe('report')
  })

  it('вкладка, на которую прав больше нет, откатывается к дефолту роли', () => {
    expect(resolveAssessmentView('manage', ['my', 'report'], false)).toBe('my')
  })

  it('роль есть, а вкладки в списке нет — «Мои» как последний рубеж', () => {
    // Такого набора сегодня не бывает, но функция не должна возвращать
    // значение, которого нет в переключателе: SegmentGroup показал бы
    // выбранным ничто.
    expect(resolveAssessmentView(null, ['my'], true)).toBe('my')
  })
})
