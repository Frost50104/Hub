import { describe, expect, it } from 'vitest'

import { hasTaskContext } from '@/components/task/TaskContextLine'

/**
 * `hasTaskContext` — единый источник истины для строки контекста И для списков,
 * решающих, резервировать ли под неё полосу. Новый признак обязан попасть
 * именно сюда: иначе у задачи, у которой из контекста только повтор, полоса
 * схлопнется, а фиксированная высота строки поедет.
 */
const bare = { comment_count: 0, attachment_count: 0, blocker_count: 0, recurrence: null }

describe('hasTaskContext', () => {
  it('пустой задаче показывать нечего', () => {
    expect(hasTaskContext(bare)).toBe(false)
  })

  it('повтор — сам по себе контекст', () => {
    expect(
      hasTaskContext({
        ...bare,
        recurrence: {
          freq: 'week',
          step: 1,
          anchor: '2026-09-14',
          occurrence: 0,
          next_due: '2026-09-21',
          text: 'каждую неделю',
        },
      }),
    ).toBe(true)
  })

  it('режим fallback перебивает всё', () => {
    expect(hasTaskContext(bare, { mode: 'fallback', stage: 'В работе' })).toBe(false)
  })
})
