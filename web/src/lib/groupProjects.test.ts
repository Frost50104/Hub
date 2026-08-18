import { describe, expect, it } from 'vitest'

import { groupProjectsByFolder } from './groupProjects'
import { type ProjectFolder } from './projectFolders'
import { type Project } from './projects'

function project(id: string, name: string, folder_id: string | null = null): Project {
  return {
    id,
    key: id.toUpperCase(),
    name,
    description: null,
    archived_at: null,
    folder_id,
    created_by: 'u1',
    created_at: '',
    updated_at: '',
    my_role: 'owner',
    is_favorite: false,
    can_edit: true,
    can_manage: true,
  }
}

function folder(id: string, name: string, position: number): ProjectFolder {
  return { id, name, position, created_at: '' }
}

describe('groupProjectsByFolder', () => {
  it('без папок возвращает одну безымянную группу', () => {
    const groups = groupProjectsByFolder([project('a', 'Альфа')], [])
    expect(groups).toHaveLength(1)
    expect(groups[0]!.folder).toBeNull()
    expect(groups[0]!.projects.map((p) => p.id)).toEqual(['a'])
  })

  it('раскладывает проекты в порядке folders', () => {
    const f1 = folder('f1', 'Первая', 0)
    const f2 = folder('f2', 'Вторая', 1)
    const groups = groupProjectsByFolder(
      [project('a', 'Альфа', 'f2'), project('b', 'Бета', 'f1')],
      [f1, f2],
    )
    expect(groups.map((g) => g.folder?.id ?? null)).toEqual(['f1', 'f2', null])
    expect(groups[0]!.projects.map((p) => p.id)).toEqual(['b'])
    expect(groups[1]!.projects.map((p) => p.id)).toEqual(['a'])
  })

  it('группа «Без папки» идёт последней', () => {
    const groups = groupProjectsByFolder(
      [project('a', 'Альфа')],
      [folder('f1', 'Первая', 0)],
    )
    expect(groups.at(-1)!.folder).toBeNull()
    expect(groups.at(-1)!.projects.map((p) => p.id)).toEqual(['a'])
  })

  it('проект со ссылкой на удалённую папку не теряется', () => {
    const groups = groupProjectsByFolder(
      [project('a', 'Альфа', 'ghost')],
      [folder('f1', 'Первая', 0)],
    )
    const unfiled = groups.at(-1)!
    expect(unfiled.folder).toBeNull()
    expect(unfiled.projects.map((p) => p.id)).toEqual(['a'])
  })

  it('пустые папки сохраняются — они нужны как drop-зоны', () => {
    const groups = groupProjectsByFolder([], [folder('f1', 'Пустая', 0)])
    expect(groups[0]!.folder?.id).toBe('f1')
    expect(groups[0]!.projects).toEqual([])
  })

  it('внутри группы сортирует по имени с русской локалью', () => {
    const f1 = folder('f1', 'Папка', 0)
    const groups = groupProjectsByFolder(
      [project('c', 'Ёлка', 'f1'), project('a', 'Аврора', 'f1'), project('b', 'Ель', 'f1')],
      [f1],
    )
    // «Ё» приравнивается к «Е», дальше посимвольно: Ёлка < Ель (к < ь).
    expect(groups[0]!.projects.map((p) => p.name)).toEqual(['Аврора', 'Ёлка', 'Ель'])
  })
})
