import { describe, expect, it } from 'vitest'

import {
  DONE_PREVIEW_LIMIT,
  excludeProject,
  personalListView,
  personalSectionState,
  resolvePersonalTaskParam,
  shouldFocusPersonalCreate,
} from './personalTasks'
import { type Task } from './tasks'

function task(over: Partial<Task> & { id: string }): Task {
  return {
    project_id: 'p1',
    section_id: null,
    parent_task_id: null,
    title: over.id,
    description: null,
    done: false,
    priority: 'medium',
    assignee_id: null,
    assignee: null,
    created_by: 'u1',
    start_at: null,
    due_at: null,
    position: 1,
    created_at: '2026-08-24T10:00:00Z',
    updated_at: '2026-08-24T10:00:00Z',
    completed_at: null,
    archived_at: null,
    ...over,
  } as Task
}

describe('excludeProject', () => {
  it('выкидывает задачи личного проекта', () => {
    const list = [task({ id: 'a' }), task({ id: 'b', project_id: 'personal' })]
    expect(excludeProject(list, 'personal').map((t) => t.id)).toEqual(['a'])
  })

  it('без id личного проекта отдаёт список как есть (старый бэкенд)', () => {
    const list = [task({ id: 'a' }), task({ id: 'b' })]
    expect(excludeProject(list, undefined)).toHaveLength(2)
    expect(excludeProject(list, null)).toHaveLength(2)
  })

  it('не мутирует вход', () => {
    const list = [task({ id: 'a', project_id: 'personal' })]
    excludeProject(list, 'personal')
    expect(list).toHaveLength(1)
  })
})

describe('personalListView', () => {
  it('подзадачи не строки, а чип родителя', () => {
    const view = personalListView([
      task({ id: 'parent' }),
      task({ id: 'kid1', parent_task_id: 'parent' }),
      task({ id: 'kid2', parent_task_id: 'parent', done: true }),
    ])
    expect(view.open.map((t) => t.id)).toEqual(['parent'])
    expect(view.subtasksByParent.get('parent')).toEqual({ total: 2, done: 1 })
  })

  it('выполненные идут после незавершённых и режутся лимитом', () => {
    const view = personalListView([
      task({ id: 'd1', done: true }),
      task({ id: 'o1' }),
      task({ id: 'd2', done: true }),
      task({ id: 'd3', done: true }),
      task({ id: 'd4', done: true }),
    ])
    expect(view.open.map((t) => t.id)).toEqual(['o1'])
    expect(view.done).toHaveLength(DONE_PREVIEW_LIMIT)
    expect(view.hiddenDone).toBe(1)
    expect(view.counts).toEqual({ open: 1, done: 4 })
  })

  it('showAllDone снимает лимит', () => {
    const list = Array.from({ length: 5 }, (_, i) =>
      task({ id: `d${i}`, done: true }),
    )
    const view = personalListView(list, { showAllDone: true })
    expect(view.done).toHaveLength(5)
    expect(view.hiddenDone).toBe(0)
  })

  it('undefined — пустой вид без падения', () => {
    const view = personalListView(undefined)
    expect(view.open).toEqual([])
    expect(view.counts).toEqual({ open: 0, done: 0 })
  })
})

describe('resolvePersonalTaskParam', () => {
  const tasks = [task({ id: 'mine' })]

  it('нет параметра — nothing to do', () => {
    expect(resolvePersonalTaskParam(null, { tasks, isPending: false })).toEqual({
      kind: 'none',
    })
  })

  it('пока список грузится — ждём, URL не трогаем', () => {
    expect(
      resolvePersonalTaskParam('mine', { tasks: undefined, isPending: true }),
    ).toEqual({ kind: 'wait' })
  })

  it('своя задача открывается', () => {
    expect(resolvePersonalTaskParam('mine', { tasks, isPending: false })).toEqual({
      kind: 'open',
      taskId: 'mine',
    })
  })

  it('чужая — параметр вычищаем', () => {
    expect(resolvePersonalTaskParam('alien', { tasks, isPending: false })).toEqual({
      kind: 'drop',
    })
  })

  it('подзадача из того же ответа тоже открывается', () => {
    const withKid = [...tasks, task({ id: 'kid', parent_task_id: 'mine' })]
    expect(
      resolvePersonalTaskParam('kid', { tasks: withKid, isPending: false }),
    ).toEqual({ kind: 'open', taskId: 'kid' })
  })
})

describe('personalSectionState', () => {
  const base = {
    meIsPending: false,
    personalProjectId: 'personal',
    isPending: false,
    isError: false,
    tasks: [task({ id: 'a' })],
    showAllDone: false,
  }

  it('пока /me грузится — секции нет', () => {
    expect(personalSectionState({ ...base, meIsPending: true }).kind).toBe('hidden')
  })

  it('старый бэкенд без personal_project_id — секции нет', () => {
    expect(personalSectionState({ ...base, personalProjectId: undefined }).kind).toBe(
      'hidden',
    )
  })

  it('ошибка важнее загрузки', () => {
    expect(personalSectionState({ ...base, isError: true, isPending: true }).kind).toBe(
      'error',
    )
  })

  it('данные — ready с разложенным видом', () => {
    const state = personalSectionState(base)
    expect(state.kind).toBe('ready')
    if (state.kind === 'ready') expect(state.view.open).toHaveLength(1)
  })
})

describe('shouldFocusPersonalCreate', () => {
  it('распознаёт только ?new=personal', () => {
    expect(shouldFocusPersonalCreate(new URLSearchParams('new=personal'))).toBe(true)
    expect(shouldFocusPersonalCreate(new URLSearchParams('new=task'))).toBe(false)
    expect(shouldFocusPersonalCreate(new URLSearchParams(''))).toBe(false)
  })
})
