import { describe, expect, it } from 'vitest'

import { favoriteProjects } from './favoriteProjects'
import { type Project } from './projects'

function project(id: string, name: string, is_favorite: boolean): Project {
  return {
    id,
    key: id.toUpperCase(),
    name,
    description: null,
    archived_at: null,
    folder_id: null,
    created_by: 'u1',
    created_at: '',
    updated_at: '',
    my_role: 'owner',
    is_favorite,
    can_edit: true,
    can_manage: true,
  }
}

describe('favoriteProjects', () => {
  it('отбирает только избранные', () => {
    const result = favoriteProjects([
      project('a', 'Альфа', false),
      project('b', 'Бета', true),
      project('c', 'Гамма', false),
    ])
    expect(result.map((p) => p.id)).toEqual(['b'])
  })

  it('сортирует по имени с русской локалью, а не в серверном порядке', () => {
    const result = favoriteProjects([
      project('c', 'Ёлка', true),
      project('a', 'Аврора', true),
      project('b', 'Ель', true),
    ])
    // «Ё» приравнивается к «Е», дальше посимвольно: Ёлка < Ель (к < ь).
    expect(result.map((p) => p.name)).toEqual(['Аврора', 'Ёлка', 'Ель'])
  })

  it('без данных и без избранных отдаёт пустой список', () => {
    expect(favoriteProjects(undefined)).toEqual([])
    expect(favoriteProjects([])).toEqual([])
    expect(favoriteProjects([project('a', 'Альфа', false)])).toEqual([])
  })

  it('не мутирует входной массив — это объект кэша, от него зависит блок «Проекты»', () => {
    const input = [project('b', 'Бета', true), project('a', 'Альфа', true)]
    const before = input.map((p) => p.id)
    favoriteProjects(input)
    expect(input.map((p) => p.id)).toEqual(before)
  })
})
