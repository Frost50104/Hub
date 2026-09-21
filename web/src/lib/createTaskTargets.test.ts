import { describe, expect, it } from 'vitest'

import {
  createdTaskLocation,
  createTaskReady,
  DELEGATE_TARGET,
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

describe('поручение в чужое личное', () => {
  it('проектом не адресуется — его резолвит сервер по человеку', () => {
    expect(resolveProjectId(DELEGATE_TARGET, 'my-personal')).toBeNull()
  })

  it('без выбранного человека форма не отправляется', () => {
    const base = { target: DELEGATE_TARGET, title: 'Собрать акты', projectId: null }
    expect(createTaskReady({ ...base, delegateTo: null })).toBe(false)
    expect(createTaskReady({ ...base, delegateTo: 'emp-1' })).toBe(true)
  })

  it('обычной задаче человек не нужен, а проект обязателен', () => {
    const base = { target: 'proj-1', title: 'Задача', delegateTo: null }
    expect(createTaskReady({ ...base, projectId: 'proj-1' })).toBe(true)
    expect(createTaskReady({ ...base, projectId: null })).toBe(false)
  })

  it('пустое название не отправляется ни в одной ветке', () => {
    expect(
      createTaskReady({
        target: DELEGATE_TARGET,
        title: '   ',
        projectId: null,
        delegateTo: 'emp-1',
      }),
    ).toBe(false)
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

describe('createTaskTargets: текущий проект вне списка (шаблон, 0060)', () => {
  it('шаблон со страницы попадает в цели и выбирается сам', () => {
    const tpl = project({ id: 'tpl', name: 'Открытие точки', can_edit: true, is_template: true })
    const targets = createTaskTargets([project()], tpl)
    expect(targets[0]).toEqual({ value: 'tpl', label: 'Открытие точки (шаблон)' })
    // Иначе FAB/сайдбар на странице шаблона молча клали задачу в личное.
    expect(initialTarget(targets, 'tpl')).toBe('tpl')
  })

  it('без прав — не добавляется; уже в списке — не дублируется', () => {
    const ro = project({ id: 'tpl', can_edit: false, is_template: true })
    expect(createTaskTargets([project()], ro).some((t) => t.value === 'tpl')).toBe(false)
    const p1 = project()
    expect(createTaskTargets([p1], p1)).toHaveLength(1)
  })
})
