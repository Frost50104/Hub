import { describe, expect, it } from 'vitest'

import {
  createdTaskLocation,
  PERSONAL_TARGET,
  createTaskTargets,
  initialTarget,
  resolveProjectId,
} from './createTaskTargets'
import type { Project } from './projects'

function project(over: Partial<Project> = {}): Project {
  return {
    id: 'p1',
    key: 'PP',
    name: 'Проект',
    description: null,
    archived_at: null,
    folder_id: null,
    created_by: 'u1',
    created_at: '2026-08-01T00:00:00Z',
    updated_at: '2026-08-01T00:00:00Z',
    my_role: 'editor',
    is_favorite: false,
    can_edit: true,
    can_manage: false,
    ...over,
  }
}

describe('createTaskTargets', () => {
  it('проект-наблюдатель в список не попадает', () => {
    // Ровно исходный баг: единственный проект сотрудника — тот, где он viewer,
    // и создание там вернуло бы 403.
    const targets = createTaskTargets([
      project({ id: 'edit', name: 'Мой', can_edit: true }),
      project({ id: 'view', name: 'Баристика', can_edit: false }),
    ])
    expect(targets.map((t) => t.value)).toEqual(['edit'])
  })

  it('без проектов — пустой список, а не выдумка', () => {
    expect(createTaskTargets(undefined)).toEqual([])
    expect(createTaskTargets([])).toEqual([])
  })
})

describe('initialTarget', () => {
  it('по умолчанию прочерк — задача уйдёт в личные', () => {
    const targets = createTaskTargets([project({ id: 'edit' })])
    expect(initialTarget(targets, undefined)).toBe(PERSONAL_TARGET)
  })

  it('со страницы проекта выбран этот проект', () => {
    const targets = createTaskTargets([project({ id: 'edit' })])
    expect(initialTarget(targets, 'edit')).toBe('edit')
  })

  it('недоступный проект прочерк не перебивает', () => {
    // Кнопка «Задача» в шапке скрыта у наблюдателя, но полагаться на это
    // нельзя: диалог обязан деградировать сам.
    const targets = createTaskTargets([project({ id: 'edit' })])
    expect(initialTarget(targets, 'view')).toBe(PERSONAL_TARGET)
  })
})

describe('resolveProjectId', () => {
  it('прочерк ведёт в личный проект', () => {
    expect(resolveProjectId(PERSONAL_TARGET, 'personal-1')).toBe('personal-1')
  })

  it('выбранный проект — в него', () => {
    expect(resolveProjectId('edit', 'personal-1')).toBe('edit')
  })

  it('нет личного проекта — писать некуда', () => {
    expect(resolveProjectId(PERSONAL_TARGET, null)).toBeNull()
    expect(resolveProjectId(PERSONAL_TARGET, undefined)).toBeNull()
  })
})

describe('createdTaskLocation', () => {
  const base = { taskId: 'T1', projectId: 'P1', isPersonal: false }

  it('личная задача открывается на /my, откуда бы её ни завели', () => {
    expect(
      createdTaskLocation({ ...base, isPersonal: true, pathname: '/assistant', search: '' }),
    ).toEqual({ pathname: '/my', search: '?task=T1' })
  })

  it('в своём проекте вкладка и фильтры остаются на месте', () => {
    const to = createdTaskLocation({
      ...base,
      pathname: '/projects/P1',
      search: '?view=board&f_priority=high',
    })
    expect(to.pathname).toBe('/projects/P1')
    expect(to.search).toContain('view=board')
    expect(to.search).toContain('f_priority=high')
    expect(to.search).toContain('task=T1')
  })

  it('в ЧУЖОЙ проект фильтры текущего не едут', () => {
    expect(
      createdTaskLocation({
        ...base,
        projectId: 'P2',
        pathname: '/projects/P1',
        search: '?view=board&f_priority=high',
      }),
    ).toEqual({ pathname: '/projects/P2', search: '?task=T1' })
  })

  it('уже открытая карточка заменяется, а не задваивается', () => {
    const to = createdTaskLocation({
      ...base,
      isPersonal: true,
      pathname: '/my',
      search: '?task=OLD',
    })
    expect(to.search).toBe('?task=T1')
  })

  it('пустой search не даёт мусорных параметров', () => {
    expect(createdTaskLocation({ ...base, pathname: '/', search: '' })).toEqual({
      pathname: '/projects/P1',
      search: '?task=T1',
    })
  })

  it('личная задача с /my сохраняет прочие параметры страницы', () => {
    const to = createdTaskLocation({
      ...base,
      isPersonal: true,
      pathname: '/my',
      search: '?new=personal',
    })
    expect(to.search).toContain('new=personal')
    expect(to.search).toContain('task=T1')
  })
})
