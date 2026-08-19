import { describe, expect, it } from 'vitest'

import { type CustomFieldDefinition, type CustomFieldType } from './customFields'
import { projectTaskGrid } from './taskGrid'

function field(type: CustomFieldType, i = 0): CustomFieldDefinition {
  return {
    id: `f${i}`,
    project_id: 'p',
    name: type,
    type,
    options: [],
    position: i,
    created_at: '2026-08-19T00:00:00Z',
  }
}

describe('projectTaskGrid', () => {
  it('без кастом-полей — три трека', () => {
    const g = projectTaskGrid([])
    expect(g.columns).toBe('minmax(0,1fr) 96px 76px')
  })

  it('повторяет треки дизайна для select+number+text', () => {
    const g = projectTaskGrid([field('select', 0), field('number', 1), field('text', 2)])
    expect(g.columns).toBe('minmax(0,1fr) 116px 82px 128px 96px 76px')
  })

  it('число треков всегда = поля + 3', () => {
    for (const n of [0, 1, 3, 10]) {
      const fields = Array.from({ length: n }, (_, i) => field('text', i))
      expect(projectTaskGrid(fields).columns.split(' ')).toHaveLength(n + 3)
    }
  })

  it('minWidth растёт с числом полей и требует скролла на десяти', () => {
    const ten = Array.from({ length: 10 }, (_, i) => field('select', i))
    const g = projectTaskGrid(ten)
    expect(g.minWidth).toBeGreaterThan(projectTaskGrid([]).minWidth)
    // Рабочая область на 1280-экране с сайдбаром — около 990px.
    expect(g.minWidth).toBeGreaterThan(990)
  })
})
