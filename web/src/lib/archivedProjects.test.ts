import { describe, expect, it } from 'vitest'

import { archivedProjects } from './archivedProjects'
import { type Project } from './projects'

const p = (over: Partial<Project>): Project =>
  ({
    id: 'p',
    key: 'P',
    name: 'Проект',
    description: null,
    archived_at: null,
    folder_id: null,
    created_by: 'u',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    my_role: 'owner',
    is_favorite: false,
    can_edit: true,
    can_manage: true,
    ...over,
  }) as Project

describe('archivedProjects', () => {
  it('живые проекты не просачиваются', () => {
    const rows = archivedProjects([
      p({ id: 'a', archived_at: null }),
      p({ id: 'b', archived_at: '2026-08-22T10:00:00Z' }),
    ])
    expect(rows.map((r) => r.id)).toEqual(['b'])
  })

  it('последний убранный — сверху', () => {
    const rows = archivedProjects([
      p({ id: 'старый', archived_at: '2026-08-01T00:00:00Z' }),
      p({ id: 'новый', archived_at: '2026-08-25T00:00:00Z' }),
    ])
    expect(rows.map((r) => r.id)).toEqual(['новый', 'старый'])
  })

  it('при равных датах порядок стабилен — по имени', () => {
    const same = '2026-08-22T10:00:00Z'
    const rows = archivedProjects([
      p({ id: '1', name: 'Яблоко', archived_at: same }),
      p({ id: '2', name: 'Апельсин', archived_at: same }),
    ])
    expect(rows.map((r) => r.name)).toEqual(['Апельсин', 'Яблоко'])
  })

  it('пустой ответ не роняет', () => {
    expect(archivedProjects(undefined)).toEqual([])
    expect(archivedProjects([])).toEqual([])
  })

  it('исходный массив не мутируется', () => {
    const input = [
      p({ id: 'a', archived_at: '2026-08-01T00:00:00Z' }),
      p({ id: 'b', archived_at: '2026-08-25T00:00:00Z' }),
    ]
    const before = input.map((x) => x.id)
    archivedProjects(input)
    expect(input.map((x) => x.id)).toEqual(before)
  })

  it('только живые — пустой список, а не падение', () => {
    expect(archivedProjects([p({ archived_at: null })])).toEqual([])
  })
})
