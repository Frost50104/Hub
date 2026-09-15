import { describe, expect, it } from 'vitest'

import { DONE_PREVIEW_LIMIT, personalListView } from './personalTasks'
import { type Task } from './tasks'

function task(over: Partial<Task> & { id: string }): Task {
  return {
    project_id: 'p1',
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
describe('вкладка «Личные» — выполненные скрыты по умолчанию', () => {
  const t = (id: string, done: boolean) =>
    ({ id, done, parent_task_id: null }) as unknown as Task

  const view = (showAllDone: boolean) =>
    personalListView([t('a', false), t('b', true), t('c', true)], {
      doneLimit: 0,
      showAllDone,
    })

  it('по умолчанию выполненных в списке нет, но счётчик их помнит', () => {
    // ОС 15.09: «в личных показывать по умолчанию не выполненные, а
    // выполненные скрыть за фильтром или чипом». Число нужно чипу.
    const v = view(false)
    expect(v.done).toEqual([])
    expect(v.counts).toEqual({ open: 1, done: 2 })
  })

  it('чип раскрывает все выполненные, а не первые три', () => {
    const v = view(true)
    expect(v.done.map((x) => x.id)).toEqual(['b', 'c'])
    expect(v.hiddenDone).toBe(0)
  })
})
