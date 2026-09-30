import { describe, expect, it } from 'vitest'

import { isTrackerQueryKey } from './trackerCache'

describe('isTrackerQueryKey', () => {
  it('экраны задач — внутри', () => {
    expect(isTrackerQueryKey(['tasks', 'p1', {}])).toBe(true)
    expect(isTrackerQueryKey(['tasks', 'detail', 't1'])).toBe(true)
    expect(isTrackerQueryKey(['task', 't1', 'comments'])).toBe(true)
    expect(isTrackerQueryKey(['me-tasks', {}])).toBe(true)
    expect(isTrackerQueryKey(['me-assigned-by-me'])).toBe(true)
    expect(isTrackerQueryKey(['me-stats'])).toBe(true)
    expect(isTrackerQueryKey(['projects', { includeArchived: false }])).toBe(true)
    expect(isTrackerQueryKey(['stages', 'p1'])).toBe(true)
    expect(isTrackerQueryKey(['timeline', 'p1'])).toBe(true)
    // Дашборд проекта: до 30.09 его не перечитывала ни одна мутация задач.
    expect(isTrackerQueryKey(['stats', 'p1'])).toBe(true)
  })

  it('ассистент, обучение, уведомления и профиль — снаружи', () => {
    // Журнал ассистента перечитывается отдельно и с ожиданием: иначе кнопки
    // плана мигали бы после «Выполнить».
    expect(isTrackerQueryKey(['assistant-messages', 'c1'])).toBe(false)
    expect(isTrackerQueryKey(['assistant-conversations'])).toBe(false)
    expect(isTrackerQueryKey(['learn-courses'])).toBe(false)
    expect(isTrackerQueryKey(['notifications', 'unread-count'])).toBe(false)
    expect(isTrackerQueryKey(['me'])).toBe(false)
    expect(isTrackerQueryKey([])).toBe(false)
  })
})
