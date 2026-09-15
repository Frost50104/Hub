import { describe, expect, it } from 'vitest'

import { hasChips, hasTaskContext } from './taskContext'

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

  it('режим plain перебивает чипы, но не подпись проекта', () => {
    // Узкие списки «Главной»: там проект важнее меток и счётчиков.
    expect(hasChips(bare, { mode: 'plain', stage: 'В работе' })).toBe(false)
    expect(hasTaskContext(bare, { mode: 'plain', stage: 'В работе' })).toBe(false)
    expect(hasTaskContext(bare, { mode: 'plain', project: 'Развитие Hub' })).toBe(true)
  })

  it('проект и колонка живут в строке ВМЕСТЕ', () => {
    // Регресс на ОС владельца 16.09. Раньше подпись была альтернативой чипам,
    // и колонка (а она есть у 25 задач из 28) молча съедала имя проекта — при
    // том что «В работе» встречается в 44 проектах, а имя проекта уникально.
    const opts = { project: 'Развитие Hub', stage: 'Входящие' }
    expect(hasChips(bare, opts)).toBe(true)
    expect(hasTaskContext(bare, opts)).toBe(true)
  })

  it('один проект без чипов — строка всё равно есть', () => {
    expect(hasChips(bare, { project: 'Развитие Hub' })).toBe(false)
    expect(hasTaskContext(bare, { project: 'Развитие Hub' })).toBe(true)
  })
})
